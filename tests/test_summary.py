"""Тесты парсинга ответа LLM (_parse_llm_response)."""
import os
import sys

# Делаем корень проекта импортируемым
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from modules.summary import _parse_llm_response, get_summary_data


def test_parse_valid_json_string():
    """(1) Валидный JSON-строка → dict."""
    text = '{"🔥 | Юмор": [3, "https://t.me/c/1/10"], "📚 | Учёба": [1, "https://t.me/c/1/11"]}'
    result = _parse_llm_response(text)
    assert isinstance(result, dict)
    assert "🔥 | Юмор" in result
    assert result["🔥 | Юмор"][0] == 3


def test_parse_json_in_markdown_fence():
    """(2) JSON в markdown-обёртке ```json...``` → dict."""
    text = '```json\n{"🚀 | Космос": [2, "https://t.me/c/1/5"]}\n```'
    result = _parse_llm_response(text)
    assert isinstance(result, dict)
    assert "🚀 | Космос" in result
    assert result["🚀 | Космос"][0] == 2


def test_parse_json_in_python_fence():
    """JSON в markdown-обёртке ```python...``` → dict."""
    text = '```python\n{"🎮 | Игры": [4, "https://t.me/c/1/7"]}\n```'
    result = _parse_llm_response(text)
    assert isinstance(result, dict)
    assert "🎮 | Игры" in result


def test_parse_dict_inside_text():
    """(3) dict внутри текста → dict (fallback по регулярке)."""
    text = 'Вот ваш ответ:\n{"💡 | Идеи": [5, "https://t.me/c/1/99"]}\nСпасибо!'
    result = _parse_llm_response(text)
    assert isinstance(result, dict)
    assert "💡 | Идеи" in result
    assert result["💡 | Идеи"][0] == 5


def test_parse_invalid_returns_none():
    """(4) Невалидный ответ → None."""
    assert _parse_llm_response("это вообще не json") is None
    assert _parse_llm_response("   ") is None
    assert _parse_llm_response(None) is None
    assert _parse_llm_response("") is None


def test_parse_non_dict_json_returns_none():
    """JSON-список (не dict) → None."""
    assert _parse_llm_response("[1, 2, 3]") is None


def test_parse_plain_fence_no_lang():
    """Обёртка ``` ... ``` без указания языка."""
    text = '```\n{"🎲 | Рандом": [1, "https://t.me/c/1/1"]}\n```'
    result = _parse_llm_response(text)
    assert isinstance(result, dict)
    assert "🎲 | Рандом" in result


# ---------------------------------------------------------------------------
# Тесты промпта кластеризации тем в get_summary_data.
# Мокаем ask_llm, перехватываем condition_text и проверяем его содержание.
# ---------------------------------------------------------------------------

import asyncio
import os
import sys
from unittest.mock import patch, AsyncMock

# Делаем модули config/db доступными без реального окружения (по образцу test_export.py)
try:
    import modules.config  # noqa: F401
except Exception:
    sys.modules.setdefault('aiogram', __import__('unittest.mock', fromlist=['MagicMock']).MagicMock())


def _make_db_with_chat(chat_id_str, date, messages):
    """Собирает минимальную db с одним чатом и историей за указанную дату.

    Формат повторяет users_database.json (см. modules/db.py и test_export.py).
    """
    db = {
        "users": {},
        "chats": {
            chat_id_str: {
                "admins": [],
                "settings": {},
                "history": {date: messages},
                "last_summary_date": "",
            }
        },
    }
    for msg in messages:
        uid = str(msg.get("user_id", "1"))
        db["users"].setdefault(uid, {"username": f"user{uid}", "first_seen": ""})
    return db


def _run_async(coro):
    """Запускает корутину в синхронном тесте."""
    try:
        loop = asyncio.get_event_loop()
        if loop.is_closed():
            raise RuntimeError("loop closed")
        return loop.run_until_complete(coro)
    except RuntimeError:
        return asyncio.new_event_loop().run_until_complete(coro)


def _make_fake_ask_llm(captured_list):
    """Возвращает async-mock, который записывает все вызовы в captured_list.

    captured_list — общий список, в который складываются condition_text'ы.
    Первый вызов ask_llm — промпт тем, второй — промпт ссылок.
    """
    async def fake_ask_llm(condition_text, channel_text_data):
        captured_list.append({"condition_text": condition_text})
        return '{"🔥 | Юмор": [1, "https://t.me/c/1/1"]}'
    return fake_ask_llm


def test_topic_prompt_does_not_contain_kazhduyu():
    """condition_text для тем НЕ содержит подстроку 'КАЖДУЮ' (case-insensitive)."""
    captured = []

    date = "2023-05-18"
    messages = [
        {"user_id": "1", "link_to_message": "https://t.me/c/1/1",
         "timestamp": "2023-05-18 10:00:00", "text_in_msg": "тест"}
    ]
    db = _make_db_with_chat("-100123", date, messages)

    with patch("modules.summary.ask_llm", new=AsyncMock(side_effect=_make_fake_ask_llm(captured))):
        _run_async(get_summary_data("-100123", date, db))

    assert len(captured) >= 1, "ask_llm не был вызван"
    cond = captured[0]["condition_text"]  # первый вызов — промпт тем
    assert "КАЖДУЮ" not in cond.upper(), f"Промпт содержит 'КАЖДУЮ': {cond!r}"


def test_topic_prompt_contains_clustering_instruction():
    """Новый промпт содержит инструкцию про кластеризацию/объединение тем."""
    captured = []

    date = "2023-05-18"
    messages = [
        {"user_id": "1", "link_to_message": "https://t.me/c/1/1",
         "timestamp": "2023-05-18 10:00:00", "text_in_msg": "тест"}
    ]
    db = _make_db_with_chat("-100123", date, messages)

    with patch("modules.summary.ask_llm", new=AsyncMock(side_effect=_make_fake_ask_llm(captured))):
        _run_async(get_summary_data("-100123", date, db))

    cond = captured[0]["condition_text"]
    # Инструкция про кластеризацию/объединение
    cond_lower = cond.lower()
    assert ("группируй" in cond_lower or "объединяй" in cond_lower), (
        f"Промпт не содержит инструкцию кластеризации/объединения: {cond!r}"
    )


def test_topic_prompt_respects_summary_topic_limit_setting():
    """Лимит тем берётся из settings.get('summary_topic_limit', 8)."""
    captured = []

    date = "2023-05-18"
    messages = [
        {"user_id": "1", "link_to_message": "https://t.me/c/1/1",
         "timestamp": "2023-05-18 10:00:00", "text_in_msg": "тест"}
    ]
    db = _make_db_with_chat("-100123", date, messages)
    db["chats"]["-100123"]["settings"]["summary_topic_limit"] = 5

    with patch("modules.summary.ask_llm", new=AsyncMock(side_effect=_make_fake_ask_llm(captured))):
        _run_async(get_summary_data("-100123", date, db))

    cond = captured[0]["condition_text"]
    assert "3 до 5" in cond, f"Лимит тем не подставился из settings: {cond!r}"


def test_topic_prompt_has_prochee_fallback_instruction():
    """Промпт содержит инструкцию отнести несовпадающие сообщения к теме 'Прочее'."""
    captured = []

    date = "2023-05-18"
    messages = [
        {"user_id": "1", "link_to_message": "https://t.me/c/1/1",
         "timestamp": "2023-05-18 10:00:00", "text_in_msg": "тест"}
    ]
    db = _make_db_with_chat("-100123", date, messages)

    with patch("modules.summary.ask_llm", new=AsyncMock(side_effect=_make_fake_ask_llm(captured))):
        _run_async(get_summary_data("-100123", date, db))

    cond = captured[0]["condition_text"]
    assert "Прочее" in cond, f"Промпт не содержит темы 'Прочее': {cond!r}"


def test_topic_prompt_per_chat_override():
    """settings.prompt_summary переопределяет пользовательскую часть промпта."""
    captured = []

    date = "2023-05-18"
    messages = [
        {"user_id": "1", "link_to_message": "https://t.me/c/1/1",
         "timestamp": "2023-05-18 10:00:00", "text_in_msg": "тест"}
    ]
    db = _make_db_with_chat("-100123", date, messages)
    db["chats"]["-100123"]["settings"]["prompt_summary"] = "МОЙ_КАСТОМНЫЙ_ПРОМПТ_123"

    with patch("modules.summary.ask_llm", new=AsyncMock(side_effect=_make_fake_ask_llm(captured))):
        _run_async(get_summary_data("-100123", date, db))

    cond = captured[0]["condition_text"]
    assert "МОЙ_КАСТОМНЫЙ_ПРОМПТ_123" in cond