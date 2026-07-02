"""Тесты modules/llm_client.ask_llm.

Покрывает три требования задачи eng-test-llm-client:
1. Дефолт модели deepseek/deepseek-v4-flash когда config не задаёт text_model.
2. max_tokens/temperature передаются в openai.chat.completions.create когда заданы в config.
3. После 3 исключений ask_llm возвращает None (не пустую строку).

Мок конфига по образцу test_export.py: sys.path.insert + MagicMock aiogram при
необходимости. Параметры config подменяются через monkeypatch, как в
test_llm_client_params.py.
"""
import asyncio
import configparser
import os
import sys
from unittest.mock import MagicMock

# Гарантируем, что корень проекта доступен в sys.path (как в test_export.py)
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# llm_client.py не импортирует aiogram напрямую, но на случай транзитивных
# импортов через modules.config подстрахуемся аналогично test_export.py.
try:
    import modules.llm_client  # noqa: F401
except ImportError:
    sys.modules['aiogram'] = MagicMock()
    sys.modules['aiogram.types'] = MagicMock()
    import modules.llm_client  # noqa: F401

import pytest


DEFAULT_MODEL = 'deepseek/deepseek-v4-flash'


def _make_config(settings=None):
    """Создаёт ConfigParser с секцией Settings из dict."""
    cfg = configparser.ConfigParser()
    cfg['Settings'] = dict(settings or {})
    return cfg


class _Chunk:
    """Один chunk stream-ответа openai: chunk.choices[0].delta.content."""

    def __init__(self, content):
        choice = MagicMock()
        delta = MagicMock()
        delta.content = content
        choice.delta = delta
        self.choices = [choice]


def _mock_openai(chunks=None, side_effect=None):
    """openai-совместимый мок: openai.chat.completions.create."""
    openai = MagicMock()
    if side_effect is not None:
        openai.chat.completions.create.side_effect = side_effect
    else:
        openai.chat.completions.create.return_value = chunks
    return openai


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


def _patch(monkeypatch, cfg, openai):
    import modules.llm_client as lc
    monkeypatch.setattr(lc, 'config', cfg)
    monkeypatch.setattr(lc, 'openai', openai)


def test_default_model_when_not_set(monkeypatch):
    """config без text_model → model=deepseek/deepseek-v4-flash в create."""
    import modules.llm_client as lc

    cfg = _make_config({})  # никаких настроек
    openai = _mock_openai([_Chunk('ok')])
    _patch(monkeypatch, cfg, openai)

    result = _run(lc.ask_llm('cond', 'data'))

    assert result == 'ok'
    create_kwargs = openai.chat.completions.create.call_args.kwargs
    assert create_kwargs['model'] == DEFAULT_MODEL
    # Убедимся, что именно дефолт, а не значение из конфига
    assert 'text_model' not in cfg['Settings']


def test_max_tokens_and_temperature_passed(monkeypatch):
    """max_tokens/temperature заданы в config → передаются в create."""
    import modules.llm_client as lc

    cfg = _make_config({'max_tokens': '2048', 'temperature': '0.7'})
    openai = _mock_openai([_Chunk('hi')])
    _patch(monkeypatch, cfg, openai)

    result = _run(lc.ask_llm('cond', 'data'))

    assert result == 'hi'
    create_kwargs = openai.chat.completions.create.call_args.kwargs
    assert create_kwargs['max_tokens'] == 2048
    assert isinstance(create_kwargs['max_tokens'], int)
    assert create_kwargs['temperature'] == 0.7
    assert isinstance(create_kwargs['temperature'], float)


def test_returns_none_after_three_exceptions(monkeypatch):
    """3 исключения подряд → ask_llm возвращает None, а не пустую строку."""
    import modules.llm_client as lc

    cfg = _make_config({})
    openai = _mock_openai(side_effect=RuntimeError('boom'))
    _patch(monkeypatch, cfg, openai)

    result = _run(lc.ask_llm('cond', 'data'))

    assert result is None
    assert result != ''
    assert openai.chat.completions.create.call_count == 3


if __name__ == '__main__':
    pytest.main([__file__, '-q'])