import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))


def test_compute_user_stats_basic():
    from modules.gsheets import compute_user_stats

    chat_data = {
        "history": {
            "2023-05-18": [
                {
                    "user_id": 1,
                    "link_to_message": "https://t.me/c/123/1",
                    "timestamp": "2023-05-18 10:00:00",
                    "text_in_msg": "Hello",
                },
                {
                    "user_id": 1,
                    "link_to_message": "https://t.me/c/123/3",
                    "timestamp": "2023-05-18 12:00:00",
                    "text_in_msg": "Later message",
                },
                {
                    "user_id": 3,
                    "link_to_message": "https://t.me/c/123/5",
                    "timestamp": "2023-05-18 11:00:00",
                    "text_in_msg": "",
                    "text": "",
                },
            ],
        },
        "reactions": {
            "2023-05-18": [
                {"reactor_user_id": 2, "delta": 1, "message_id": 1},
                {"reactor_user_id": 2, "delta": 2, "message_id": 3},
            ],
        },
    }

    stats = compute_user_stats(chat_data, args=[], db={})

    # user 1: 2 messages, last_text from the later message, 3 reactions received
    assert stats["1"]["messages"] == 2
    assert stats["1"]["reactions_received"] == 3
    assert stats["1"]["reactions_given"] == 0
    assert stats["1"]["last_text"] == "Later message"

    # user 2: no messages, 3 reactions given, last_text empty
    assert stats["2"]["messages"] == 0
    assert stats["2"]["reactions_given"] == 3
    assert stats["2"]["reactions_received"] == 0
    assert stats["2"]["last_text"] == ""

    # user 3: 1 message, no reactions, last_text placeholder
    assert stats["3"]["messages"] == 1
    assert stats["3"]["last_text"] == "[Медиа/Без текста]"


def test_compute_user_stats_empty():
    from modules.gsheets import compute_user_stats

    stats = compute_user_stats({}, args=[], db={})
    assert stats == {}


def test_compute_user_stats_matches_export_aggregation():
    """Cross-check messages/reactions counts against process_export's branch."""
    from modules.gsheets import compute_user_stats

    chat_data = {
        "history": {
            "2024-01-01": [
                {"user_id": 10, "link_to_message": "https://t.me/c/1/100",
                 "timestamp": "2024-01-01 08:00:00", "text_in_msg": "first"},
                {"user_id": 20, "link_to_message": "https://t.me/c/1/101",
                 "timestamp": "2024-01-01 09:00:00", "text_in_msg": "second"},
            ],
        },
        "reactions": {
            "2024-01-01": [
                {"reactor_user_id": 20, "delta": 1, "message_id": 100},
            ],
        },
    }

    stats = compute_user_stats(chat_data, args=[], db={"users": {}})

    assert stats["10"]["messages"] == 1
    assert stats["10"]["reactions_received"] == 1
    assert stats["10"]["last_text"] == "first"
    assert stats["20"]["messages"] == 1
    assert stats["20"]["reactions_given"] == 1
    assert stats["20"]["last_text"] == "second"


if __name__ == "__main__":
    test_compute_user_stats_basic()
    test_compute_user_stats_empty()
    test_compute_user_stats_matches_export_aggregation()
    print("ok")