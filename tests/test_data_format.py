"""Тесты форматирования forming_data в читаемый текст вместо str(list[dict])."""
import asyncio
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from modules.summary import _format_messages_for_llm, _format_texts_for_links


def _make_msg(user_id, text, link):
    return {
        "user_id": user_id,
        "link_to_message": link,
        "text_in_msg": text,
        "timestamp": "2026-07-02T12:00:00",
    }


def test_format_messages_basic():
    """Формат '[1] username: text (link)\\n[2] ...'."""
    database = {
        "users": {
            "111": {"username": "alice"},
            "222": {"username": "bob"},
        }
    }
    forming_data = [
        _make_msg("111", "Привет всем", "https://t.me/c/1/10"),
        _make_msg("222", "Как дела?", "https://t.me/c/1/11"),
    ]
    result = _format_messages_for_llm(forming_data, database)
    assert "[1] alice: Привет всем (https://t.me/c/1/10)" in result
    assert "[2] bob: Как дела? (https://t.me/c/1/11)" in result
    assert result == "[1] alice: Привет всем (https://t.me/c/1/10)\n[2] bob: Как дела? (https://t.me/c/1/11)"
    print("test_format_messages_basic: PASS")


def test_format_messages_not_str_of_list_dict():
    """Вывод не должен быть str(list[dict]) — нет сырых dict-представлений."""
    database = {"users": {"111": {"username": "alice"}}}
    forming_data = [_make_msg("111", "Текст", "https://t.me/c/1/10")]
    result = _format_messages_for_llm(forming_data, database)
    # не должно быть сырых фигурных скобок от dict-представления
    assert "{'" not in result
    assert '"user_id"' not in result
    assert "user_id" not in result
    assert "timestamp" not in result
    print("test_format_messages_not_str_of_list_dict: PASS")


def test_format_messages_username_fallback():
    """Если user_id нет в database['users'] — fallback на 'Unknown'."""
    database = {"users": {}}
    forming_data = [_make_msg("999", "Одинокий текст", "https://t.me/c/1/1")]
    result = _format_messages_for_llm(forming_data, database)
    assert "[1] Unknown: Одинокий текст (https://t.me/c/1/1)" in result
    print("test_format_messages_username_fallback: PASS")


def test_format_messages_no_user_id_key():
    """Если в msg вообще нет user_id — не падает, fallback 'Unknown'."""
    database = {"users": {}}
    forming_data = [{"text_in_msg": "Без user", "link_to_message": "https://t.me/c/1/1"}]
    result = _format_messages_for_llm(forming_data, database)
    assert "[1] Unknown: Без user (https://t.me/c/1/1)" in result
    print("test_format_messages_no_user_id_key: PASS")


def test_format_messages_empty_text():
    """Пустой text_in_msg не ломает формат."""
    database = {"users": {"111": {"username": "alice"}}}
    forming_data = [{"user_id": "111", "link_to_message": "https://t.me/c/1/1", "text_in_msg": ""}]
    result = _format_messages_for_llm(forming_data, database)
    assert "[1] alice:  (https://t.me/c/1/1)" in result
    print("test_format_messages_empty_text: PASS")


def test_format_texts_for_links_basic():
    """only_text объединяется в строку, остаются только тексты."""
    only_text = ["Первый текст", "Второй текст", ""]
    result = _format_texts_for_links(only_text)
    assert "Первый текст" in result
    assert "Второй текст" in result
    assert "{" not in result
    assert "'" not in result
    print("test_format_texts_for_links_basic: PASS")


def test_format_texts_for_links_no_dict_repr():
    """Только тексты — никаких dict-представлений."""
    only_text = ["Текст", "Ещё текст"]
    result = _format_texts_for_links(only_text)
    assert result == "Текст\nЕщё текст"
    assert "text_in_msg" not in result
    print("test_format_texts_for_links_no_dict_repr: PASS")


def test_format_texts_for_links_empty():
    """Пустой список → пустая строка."""
    assert _format_texts_for_links([]) == ""
    assert _format_texts_for_links(["", ""]) == ""
    print("test_format_texts_for_links_empty: PASS")


if __name__ == "__main__":
    test_format_messages_basic()
    test_format_messages_not_str_of_list_dict()
    test_format_messages_username_fallback()
    test_format_messages_no_user_id_key()
    test_format_messages_empty_text()
    test_format_texts_for_links_basic()
    test_format_texts_for_links_no_dict_repr()
    test_format_texts_for_links_empty()
    print("\nAll data-format tests PASSED")