"""Тесты передачи max_tokens и temperature в openai.chat.completions.create."""
import asyncio
import configparser
from unittest.mock import MagicMock

import pytest


def _make_config(settings=None):
    cfg = configparser.ConfigParser()
    cfg['Settings'] = dict(settings or {})
    return cfg


class _Chunk:
    def __init__(self, content):
        choice = MagicMock()
        delta = MagicMock()
        delta.content = content
        choice.delta = delta
        choice.choices = None
        self.choices = [choice]


def _mock_openai(chunks):
    """openai-совместимый мок: openai.chat.completions.create -> list of chunks."""
    openai = MagicMock()
    openai.chat.completions.create.return_value = chunks
    return openai


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


def _patch_config(monkeypatch, cfg):
    import modules.llm_client as lc
    monkeypatch.setattr(lc, "config", cfg)


def test_no_params_when_not_set(monkeypatch):
    """Без max_tokens/temperature в конфиге — их нет в вызове create."""
    import modules.llm_client as lc

    cfg = _make_config({'text_model': 'm1'})
    monkeypatch.setattr(lc, "config", cfg)
    openai = _mock_openai([_Chunk("hello")])
    monkeypatch.setattr(lc, "openai", openai)

    result = _run(lc.ask_llm("cond", "data"))

    assert result == "hello"
    create_kwargs = openai.chat.completions.create.call_args.kwargs
    assert "max_tokens" not in create_kwargs
    assert "temperature" not in create_kwargs


def test_params_passed(monkeypatch):
    """Заданные max_tokens/temperature приводятся к int/float и передаются."""
    import modules.llm_client as lc

    cfg = _make_config({'text_model': 'm1', 'max_tokens': '2048', 'temperature': '0.5'})
    monkeypatch.setattr(lc, "config", cfg)
    openai = _mock_openai([_Chunk("hi")])
    monkeypatch.setattr(lc, "openai", openai)

    result = _run(lc.ask_llm("cond", "data"))

    assert result == "hi"
    create_kwargs = openai.chat.completions.create.call_args.kwargs
    assert create_kwargs["max_tokens"] == 2048
    assert isinstance(create_kwargs["max_tokens"], int)
    assert create_kwargs["temperature"] == 0.5
    assert isinstance(create_kwargs["temperature"], float)


def test_empty_params_skipped(monkeypatch):
    """Пустые строки значений не передаются."""
    import modules.llm_client as lc

    cfg = _make_config({'text_model': 'm1', 'max_tokens': '', 'temperature': '   '})
    monkeypatch.setattr(lc, "config", cfg)
    openai = _mock_openai([_Chunk("ok")])
    monkeypatch.setattr(lc, "openai", openai)

    _run(lc.ask_llm("cond", "data"))

    create_kwargs = openai.chat.completions.create.call_args.kwargs
    assert "max_tokens" not in create_kwargs
    assert "temperature" not in create_kwargs


def test_only_max_tokens(monkeypatch):
    """Только max_tokens, без temperature."""
    import modules.llm_client as lc

    cfg = _make_config({'text_model': 'm1', 'max_tokens': '1000'})
    monkeypatch.setattr(lc, "config", cfg)
    openai = _mock_openai([_Chunk("x")])
    monkeypatch.setattr(lc, "openai", openai)

    _run(lc.ask_llm("cond", "data"))

    create_kwargs = openai.chat.completions.create.call_args.kwargs
    assert create_kwargs["max_tokens"] == 1000
    assert "temperature" not in create_kwargs


def test_invalid_value_skipped(monkeypatch):
    """Некорректное значение не ломает вызов и не передаётся."""
    import modules.llm_client as lc

    cfg = _make_config({'text_model': 'm1', 'max_tokens': 'abc', 'temperature': 'not-a-number'})
    monkeypatch.setattr(lc, "config", cfg)
    openai = _mock_openai([_Chunk("y")])
    monkeypatch.setattr(lc, "openai", openai)

    _run(lc.ask_llm("cond", "data"))

    create_kwargs = openai.chat.completions.create.call_args.kwargs
    assert "max_tokens" not in create_kwargs
    assert "temperature" not in create_kwargs


def test_returns_none_on_all_failures(monkeypatch):
    """После 3 неудачных попыток ask_llm возвращает None (не пустую строку)."""
    import modules.llm_client as lc

    cfg = _make_config({'text_model': 'm1'})
    monkeypatch.setattr(lc, "config", cfg)
    openai = MagicMock()
    openai.chat.completions.create.side_effect = RuntimeError("boom")
    monkeypatch.setattr(lc, "openai", openai)

    result = _run(lc.ask_llm("cond", "data"))

    assert result is None
    assert openai.chat.completions.create.call_count == 3