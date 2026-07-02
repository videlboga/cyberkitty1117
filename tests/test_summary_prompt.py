"""Тест: новый промпт кластеризации в modules/summary.py.

Покрывает задачу eng-summary-prompt:
- Убрана инструкция 'Выдели КАЖДУЮ уникальную тему ... даже если она упоминалась мельком'.
- Лимит тем берётся из settings.get('summary_topic_limit', 8) и подставляется в condition_main.
- Есть инструкция про 'Прочее'.
- Сохранён per-chat override через settings.prompt_summary.
- Есть явный пример ожидаемого вывода (dict тем).
"""
import asyncio
import os
import sys
from unittest.mock import AsyncMock, patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


def _make_db(settings=None):
    """Минимальная база с одной датой и одним сообщением."""
    return {
        'users': {'1': {'username': 'Tester', 'first_seen': '2026-01-01'}},
        'chats': {
            '-100123': {
                'admins': [],
                'settings': settings or {},
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


def _capture_condition(monkeypatch):
    """Возвращает condition, переданный в ask_llm при вызове тем."""
    import modules.summary as s

    captured = {}

    async def _ask(condition, data):
        # Первый вызов — темы, второй — ссылки. Сохраняем оба.
        if 'topics' not in captured:
            captured['topics'] = condition
        else:
            captured['links'] = condition
        # Темы — валидный dict, чтобы функция завершилась без повторов.
        return '{"🔥 | Юмор": [1, "https://t.me/c/123/1"]}'

    monkeypatch.setattr(s, 'ask_llm', _ask)
    return captured


def test_default_prompt_has_no_old_instruction(monkeypatch):
    """Дефолтный промпт не содержит старую инструкцию про 'КАЖДУЮ'."""
    captured = _capture_condition(monkeypatch)
    import modules.summary as s
    _run(s.get_summary_data(-100123, '2026-01-01', _make_db()))

    cond = captured['topics']
    assert 'КАЖДУЮ уникальную тему' not in cond
    assert 'даже если она упоминалась мельком' not in cond


def test_default_prompt_has_new_instructions(monkeypatch):
    """Дефолтный промпт содержит новые инструкции: группировка, Прочее, лимит, пример."""
    captured = _capture_condition(monkeypatch)
    import modules.summary as s
    _run(s.get_summary_data(-100123, '2026-01-01', _make_db()))

    cond = captured['topics']
    # Группировка и объединение похожего
    assert 'Группируй сообщения по темам' in cond
    assert 'Объединяй похожие сообщения' in cond
    # Инструкция про Прочее
    assert 'Прочее' in cond
    # Лимит: все значимые темы, не больше 10
    assert 'не больше 10' in cond
    # Явный пример вывода (dict тем)
    assert 'Пример ожидаемого вывода' in cond
    assert '"🔥 | Юмор и мемы"' in cond


def test_topic_limit_override(monkeypatch):
    """settings.summary_topic_limit подставляется в лимит тем."""
    captured = _capture_condition(monkeypatch)
    import modules.summary as s
    db = _make_db(settings={'summary_topic_limit': 5})
    _run(s.get_summary_data(-100123, '2026-01-01', db))

    cond = captured['topics']
    # 1 сообщение, topic_limit=5 → "не больше 5"
    assert 'не больше 5' in cond


def test_prompt_summary_override_replaces_default(monkeypatch):
    """settings.prompt_summary полностью заменяет дефолтный condition_user."""
    captured = _capture_condition(monkeypatch)
    import modules.summary as s
    custom = 'МОЙ_КАСТОМНЫЙ_ПРОМПТ_ДЛЯ_ТЕМ'
    db = _make_db(settings={'prompt_summary': custom})
    _run(s.get_summary_data(-100123, '2026-01-01', db))

    cond = captured['topics']
    # Кастомный промпт присутствует
    assert custom in cond
    # Дефолтные инструкции отсутствуют (override заменяет целиком)
    assert 'Группируй сообщения по темам' not in cond
    assert 'Пример ожидаемого вывода' not in cond
    # Но лимит из condition_main всё равно применяется (по умолчанию 10)
    assert 'не больше 10' in cond