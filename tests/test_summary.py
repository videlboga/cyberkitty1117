"""Тесты парсинга ответа LLM (_parse_llm_response)."""
import os
import sys

# Делаем корень проекта импортируемым
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from modules.summary import _parse_llm_response


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