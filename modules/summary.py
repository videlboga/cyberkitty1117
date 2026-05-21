"""Data aggregation module building context for the LLM."""
"""
Модуль для создания суммаризаций сообщений (Core V2 Schema).
"""

import ast
from .llm_client import ask_llm


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
    
    condition_main = 'Твоя задача обработать текст из истории чата по условиям:\n'
    condition_main2 = '''\nВОТ СТРОГИЙ ФОРМАТ ДАННЫХ:
    {"(Here insert an emoticon on the topic) | Юмор, обсуждали последние мемы": [ЧИСЛО СОВПАДЕНИЙ по теме, "(link_to_message)"],
     "(Here insert an emoticon on the topic) | Разговор о политике": [ЧИСЛО СОВПАДЕНИЙ по теме, "(link_to_message)"]}
    ВАЖНО: на РУССКОМ ЯЗЫКЕ. ОТПРАВЬ ТОЛЬКО СЛОВАРЬ без json или python форматирования. (link_to_message) - это первое совпадение text_in_msg по этой теме'''
    
    condition_user = settings.get('prompt_summary', '''
Внимательно прочитай ВСЕ сообщения в чате. Не пропускай ни одного.
Выдели КАЖДУЮ уникальную тему или идею, даже если она упоминалась мельком.
Создай краткий заголовок (4-7 слов) для каждой темы, отражающий её суть.
Объединяй похожие темы под одним заголовком.
Перед завершением проверь список дважды.
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
            llm_answer = await ask_llm(all_condition_text, forming_data)
            dict_info = ast.literal_eval(llm_answer)
            break
        except Exception as e:
            print(f"Ошибка при получении тем (попытка {i+1}): {e}")

    # Получаем информацию о ссылках
    for i in range(2):
        try:
            llm_answer = await ask_llm(all_links_condition, only_text)
            links_data = ast.literal_eval(llm_answer)
            break
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
