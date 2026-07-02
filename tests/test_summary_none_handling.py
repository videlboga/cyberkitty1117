"""Тест: None от ask_llm не роняет get_summary_data.

Покрывает задачу eng-summary-none-handling: если ask_llm возвращает None
на обеих попытках — dict_info/links_data остаются None, функция возвращает
None, рендер HTML не падает.
"""
import asyncio
import os
import sys
from unittest.mock import AsyncMock, patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


def _make_db():
    """Минимальная база с одной датой и одним сообщением."""
    return {
        'users': {'1': {'username': 'Tester', 'first_seen': '2026-01-01'}},
        'chats': {
            '-100123': {
                'admins': [],
                'settings': {},
                'history': {
                    '2026-01-01': [
                        {
                            'user_id': '1',
                            'link_to_message': 'https://t.me/c/123/1',
                            'text_in_msg': 'привет',
                            'timestamp': '2026-01-01T10:00:00',
                        }
                    ]
                },
                'last_summary_date': '',
            }
        },
    }


def test_both_llm_none_returns_none(monkeypatch):
    """ask_llm всегда None → get_summary_data возвращает None, не падает."""
    import modules.summary as s

    async def _none(*a, **kw):
        return None

    monkeypatch.setattr(s, 'ask_llm', _none)

    result = _run(s.get_summary_data(-100123, '2026-01-01', _make_db()))

    assert result is None


def test_topics_none_links_none_returns_none(monkeypatch):
    """Отдельно: темы None, ссылки None → None."""
    import modules.summary as s

    async def _none(*a, **kw):
        return None

    monkeypatch.setattr(s, 'ask_llm', _none)
    result = _run(s.get_summary_data(-100123, '2026-01-01', _make_db()))
    assert result is None


def test_topics_ok_links_none_returns_msg(monkeypatch):
    """Темы получены, ссылки None → рендер тем, без блока ссылок, возврат строки."""
    import modules.summary as s

    topics = '{"🔥 | Юмор": [3, "https://t.me/c/123/1"]}'

    calls = {'n': 0}

    async def _ask(condition, data):
        # Первый вызов (темы) — валидный dict, второй (ссылки) — None
        calls['n'] += 1
        return topics if calls['n'] == 1 else None

    monkeypatch.setattr(s, 'ask_llm', _ask)
    result = _run(s.get_summary_data(-100123, '2026-01-01', _make_db()))

    assert result is not None
    assert '🔥 | Юмор' in result
    # Блока ссылок быть не должно, т.к. links_data is None
    assert 'Ссылки по темам' not in result


def test_retries_on_none_then_succeeds(monkeypatch):
    """Первая попытка тем — None, вторая — валидный dict: retry срабатывает."""
    import modules.summary as s

    topics = '{"📚 | Учёба": [2, "https://t.me/c/123/1"]}'

    state = {'topics_attempts': 0, 'links_attempts': 0}

    async def _ask(condition, data):
        # Отличаем темы от ссылок по содержимому condition
        if 'тему' in condition or 'СОВПАДЕНИЙ' in condition:
            state['topics_attempts'] += 1
            return None if state['topics_attempts'] == 1 else topics
        state['links_attempts'] += 1
        return None

    monkeypatch.setattr(s, 'ask_llm', _ask)
    result = _run(s.get_summary_data(-100123, '2026-01-01', _make_db()))

    assert result is not None
    assert '📚 | Учёба' in result
    # Должно быть ровно 2 попытки тем (первая None, вторая успех)
    assert state['topics_attempts'] == 2


def test_missing_chat_returns_none(monkeypatch):
    """Нет чата в базе → None сразу, без вызова LLM."""
    import modules.summary as s

    called = {'n': 0}

    async def _ask(*a, **kw):
        called['n'] += 1
        return None

    monkeypatch.setattr(s, 'ask_llm', _ask)
    result = _run(s.get_summary_data(-999999, '2026-01-01', _make_db()))

    assert result is None
    assert called['n'] == 0


def test_no_messages_returns_none(monkeypatch):
    """Дата есть, но сообщений нет (пустой список) → None без вызова LLM."""
    import modules.summary as s

    db = _make_db()
    db['chats']['-100123']['history']['2026-01-02'] = []

    called = {'n': 0}

    async def _ask(*a, **kw):
        called['n'] += 1
        return None

    monkeypatch.setattr(s, 'ask_llm', _ask)
    result = _run(s.get_summary_data(-100123, '2026-01-02', db))

    assert result is None
    assert called['n'] == 0