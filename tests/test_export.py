import asyncio
import io
import csv

def test_global_export():
    # Mock data
    import sys
    import os
    sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
    
    chats = [
        ("chat_1", "Test Chat", {
            "history": {
                "2023-05-18": [
                    {"user_id": 1, "link_to_message": "https://t.me/c/123/1", "timestamp": "2023-05-18 10:00:00", "text_in_msg": "Hello"}
                ]
            },
            "reactions": {
                "2023-05-18": [
                    {"reactor_user_id": 2, "delta": 1, "message_id": 1}
                ]
            },
            "membership_events": [
                {"user_id": 1, "action": "joined", "date": "2023-05-18 09:00:00"}
            ]
        })
    ]
    db = {"users": {"1": {"username": "user1"}, "2": {"username": "user2"}}}
    
    # We load export
    try:
        from modules.export import build_global_export_csv_bytes
    except ImportError:
        # Mock aiogram if it's imported at the top of export.py
        import sys
        from unittest.mock import MagicMock
        sys.modules['aiogram'] = MagicMock()
        sys.modules['aiogram.types'] = MagicMock()
        from modules.export import build_global_export_csv_bytes
        
    csv_bytes, caption, filename = build_global_export_csv_bytes(chats, args=[], db=db)
    
    # Assertions for pytest
    result_text = csv_bytes.decode('utf-8')
    assert "СТАТИСТИКА ПОЛЬЗОВАТЕЛЕЙ ПО ЧАТАМ" in result_text
    assert "user1" in result_text
    assert "Test Chat" in result_text
    
if __name__ == "__main__":
    test()
