"""Data aggregation module building context for the LLM."""
"""
Модуль для создания суммаризаций сообщений (Core V2 Schema).
"""

import json
import re
from .llm_client import ask_llm


def _parse_llm_response(text):
    """Безопасно разбирает ответ LLM в dict.

    Шаги:
    1. Возвращает None, если на входе None или пусто.
    2. Очищает от markdown-обёрток (```json / ```python / ```).
    3. Пытается json.loads.
    4. При неудаче извлекает первый {...}-блок регуляркой и снова json.loads.
    5. Если ничего не получилось — возвращает None.

    Возвращает dict, либо None.
    """
    if text is None:
        return None
    s = str(text).strip()
    if not s:
        return None

    # Снимаем markdown-fence ```json ... ``` / ```python ... ``` / ``` ... ```
    fence = re.search(r"```(?:json|python)?\s*(.*?)```", s, re.DOTALL | re.IGNORECASE)
    if fence:
        s = fence.group(1).strip()

    # Прямой парсинг
    try:
        value = json.loads(s)
        if isinstance(value, dict):
            return value
    except (json.JSONDecodeError, ValueError):
        pass

    # Fallback: найти первый {...}-блок
    match = re.search(r"\{.*\}", s, re.DOTALL)
    if match:
        try:
            value = json.loads(match.group(0))
            if isinstance(value, dict):
                return value
        except (json.JSONDecodeError, ValueError):
            pass

    return None


def _format_messages_for_llm(forming_data, database):
    """Форматирует list[dict] сообщений в читаемую строку для LLM.

    Формат: '[1] username: text (link)\\n[2] ...'
    Использует text_in_msg и link_to_message; не передаёт user_id/timestamp.
    username берётся из database['users'][user_id]['username'] с .get fallback.
    """
    users = database.get('users', {})
    lines = []
    for idx, msg in enumerate(forming_data, start=1):
        user_id = msg.get('user_id')
        username = users.get(user_id, {}).get('username', 'Unknown')
        text = msg.get('text_in_msg', '') or ''
        link = msg.get('link_to_message', '') or ''
        lines.append(f'[{idx}] {username}: {text} ({link})')
    return '\n'.join(lines)


def _format_texts_for_links(only_text):
    """Объединяет список текстов в строку для промпта поиска ссылок.

    Оставляет только тексты (без словарной структуры).
    """
    return '\n'.join(t for t in only_text if t)


async def get_summary_data(chat_id, data_needed, database):
    """Получает суммаризованные данные за определенную дату по новой схеме."""
    chat_id_str = str(chat_id)
    
    try:
        messages = database['chats'][chat_id_str]['history'][data_needed]
    except KeyError:
        return None
        
    if not messages:
        return None
        
    forming_data = []
    only_text = []
    
    for msg_data in messages:
        forming_data.append(msg_data)
        only_text.append(msg_data.get('text_in_msg', ''))

    # Настройки промптов берем из настроек чата (или дефолтные)
    settings = database['chats'][chat_id_str].get('settings', {})
    
    # Лимит тем за день: без нижней границы, максимум topic_limit (по умолчанию 10)
    topic_limit = settings.get('summary_topic_limit', 10)

    condition_main = f'Твоя задача обработать текст из истории чата по условиям:\n- Выдели все значимые темы за день, но не больше {topic_limit}.\n- НЕ дроби близкие темы. Если сообщения обсуждают одно и то же — это ОДНА тема, а не несколько.\n- Количество тем должно быть оправдано содержанием, а не стремлением набрать максимум.\n- Мелкие упоминания объедини с ближайшей по смыслу темой или отнеси к "Прочее".\n'
    condition_main2 = '''\nВОТ СТРОГИЙ ФОРМАТ ДАННЫХ:
    {"(Here insert an emoticon on the topic) | Юмор, обсуждали последние мемы": [ЧИСЛО СОВПАДЕНИЙ по теме, "(link_to_message)"],
     "(Here insert an emoticon on the topic) | Разговор о политике": [ЧИСЛО СОВПАДЕНИЙ по теме, "(link_to_message)"]}
    ВАЖНО: на РУССКОМ ЯЗЫКЕ. ОТПРАВЬ ТОЛЬКО СЛОВАРЬ без json или python форматирования. (link_to_message) - это первое совпадение text_in_msg по этой теме'''

    condition_user = settings.get('prompt_summary', f'''
Группируй сообщения по темам. Объединяй похожие сообщения под одним заголовком.
Создай краткий заголовок (4-7 слов) для каждой темы, отражающий её суть.
Если сообщение не вписывается в основную тему — отнеси к теме "Прочее".
Перед завершением проверь список дважды — объединяй темы, которые пересекаются по смыслу.
Если за день обсуждалась по сути одна тема — оставь ОДНУ тему, не выдумывай искусственное разбиение.

Пример ожидаемого вывода (словарь тем):
{{"🔥 | Юмор и мемы": [5, "https://t.me/c/123/42"],
 "💻 | Работа и проекты": [3, "https://t.me/c/123/10"],
 "📋 | Прочее": [1, "https://t.me/c/123/7"]}}
    ''')
        
    all_condition_text = condition_main + condition_user + condition_main2

    condition_link_user = settings.get('prompt_links', 'Краткое описание ссылки 5 - 7 слов максимум. Названия не должны повторяться')
        
    condition_link_start = ('Найди ссылки (не допускай повторений) в тексте (если ссылки есть в тексте) '
                           'и отправь мне списком питон словарь, где ключ это ссылка, а данные внутри ключа '
                           'это краткое описание ссылки. Вот критерии поиска ссылок:\n')
    condition_link_over = '\nОписание на РУССКОМ ЯЗЫКЕ. ОТПРАВЬ ТОЛЬКО СЛОВАРЬ без ```json или ```python форматирования'
    all_links_condition = condition_link_start + condition_link_user + condition_link_over
    
    dict_info = None
    links_data = None
    
    # Получаем информацию о темах
    for i in range(2):
        try:
            llm_answer = await ask_llm(all_condition_text, _format_messages_for_llm(forming_data, database))
            if llm_answer is None:
                print(f"Пустой ответ LLM при получении тем (попытка {i+1})")
                continue
            dict_info = _parse_llm_response(llm_answer)
            if dict_info is not None:
                break
            print(f"Не удалось разобрать ответ LLM тем (попытка {i+1})")
        except Exception as e:
            print(f"Ошибка при получении тем (попытка {i+1}): {e}")

    # Получаем информацию о ссылках
    for i in range(2):
        try:
            llm_answer = await ask_llm(all_links_condition, _format_texts_for_links(only_text))
            if llm_answer is None:
                print(f"Пустой ответ LLM при получении ссылок (попытка {i+1})")
                continue
            links_data = _parse_llm_response(llm_answer)
            if links_data is not None:
                break
            print(f"Не удалось разобрать ответ LLM ссылок (попытка {i+1})")
        except Exception as e:
            print(f"Ошибка при получении ссылок (попытка {i+1}): {e}")
    
    total_msg = f'🔥 Самые обсуждаемые темы на {data_needed}\n\n'
    
    if dict_info is not None and isinstance(dict_info, dict):
        for items in dict_info:
            count_msg = f"<a href='{dict_info[items][1]}'>{dict_info[items][0]} сообщ.</a>"
            total_msg += f'{items} ({count_msg})\n'

    if links_data is not None and isinstance(links_data, dict) and len(links_data) > 0:
        i = 0
        for links in links_data:
            if 'http://' in links or 'https://' in links:
                if i == 0:
                    total_msg += '\n\nСсылки по темам:\n\n'
                    i += 1
                total_msg += f"🔗 <a href='{links}'>{links_data[links]}</a>\n"

    if dict_info is not None and isinstance(dict_info, dict) and len(dict_info) > 0:
        total_msg += '\n\n#CyberKittySummary'
        return total_msg
    else:
        return None


async def save_message_to_database(message, database, chat_id):
    """Сохраняет сообщение в базу данных по новой архитектуре ролей."""
    from datetime import datetime as dt
    
    user_id = str(message.from_user.id)
    username = message.from_user.username or message.from_user.first_name or "Unknown"
    chat_id_str = str(chat_id)
    
    # 1. Записываем профиль юзера
    if 'users' not in database:
        database['users'] = {}
    if user_id not in database['users']:
        database['users'][user_id] = {'username': username, 'first_seen': dt.now().isoformat()}

    # 2. Инициализация чата, если он еще не прописан (если пишут пользователи)
    if 'chats' not in database:
        database['chats'] = {}
        
    if chat_id_str not in database['chats']:
        database['chats'][chat_id_str] = {
            'admins': [],
            'settings': {},
            'history': {},
            'last_summary_date': ""
        }
        
    chat_data = database['chats'][chat_id_str]
    if 'history' not in chat_data:
         chat_data['history'] = {}
         
    today = str(dt.now().date())
    if today not in chat_data['history']:
        chat_data['history'][today] = []
        
    link_base = f"https://t.me/c/{chat_id_str[4:]}/{message.message_id}" if chat_id_str.startswith("-100") else f"https://t.me/c/{chat_id_str}/{message.message_id}"
    
    message_data = {
        "user_id": user_id,
        "link_to_message": link_base,
        "text_in_msg": message.text or message.caption or "",
        "timestamp": dt.now().isoformat()
    }
    
    chat_data['history'][today].append(message_data)
