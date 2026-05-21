import json
import asyncio
from datetime import datetime
from pathlib import Path
from pyrogram import Client, filters
from pyrogram.types import ChatMemberUpdated
from pyrogram.enums import ChatMemberStatus
import os
from dotenv import load_dotenv

# Подключаем работу с нашей общей БД
import sys
sys.path.append(str(Path(__file__).resolve().parent.parent))
from modules.db import load_database, save_database

load_dotenv()

API_ID = os.getenv("TELEGRAM_API_ID")
API_HASH = os.getenv("TELEGRAM_API_HASH")
SESSION_NAME = os.getenv("SESSION_NAME", "userbot_session")

app = Client(SESSION_NAME, api_id=API_ID, api_hash=API_HASH)

async def record_membership_event(chat_id: int, user_id: int, username: str, action: str, event_date: datetime):
    """Сохраняет событие подписки/отписки в общую БД бота."""
    db = load_database()
    chat_id_str = str(chat_id)
    
    if "chats" not in db:
        db["chats"] = {}
    if chat_id_str not in db["chats"]:
        db["chats"][chat_id_str] = {}
    if "membership_events" not in db["chats"][chat_id_str]:
        db["chats"][chat_id_str]["membership_events"] = []
    
    # Сохраняем информацию о пользователе
    if "users" not in db:
        db["users"] = {}
    uid_str = str(user_id)
    if uid_str not in db["users"] or not db["users"][uid_str].get("username"):
        db["users"][uid_str] = {"username": username if username else f"ID:{user_id}"}
        
    db["chats"][chat_id_str]["membership_events"].append({
        "user_id": user_id,
        "action": action,
        "date": event_date.isoformat()
    })
    
    await save_database(db)
    print(f"[{event_date.isoformat()}] Chat {chat_id}: User {user_id} ({username}) -> {action}")

@app.on_chat_member_updated()
async def member_update(client: Client, event: ChatMemberUpdated):
    old = event.old_chat_member
    new = event.new_chat_member
    if not old or not new:
        return
        
    user = new.user
    if not user:
        return
        
    # Определяем действие
    action = None
    was_member = old.status in [ChatMemberStatus.MEMBER, ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.OWNER, ChatMemberStatus.RESTRICTED]
    is_member = new.status in [ChatMemberStatus.MEMBER, ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.OWNER, ChatMemberStatus.RESTRICTED]
    
    if not was_member and is_member:
        action = "joined"
    elif was_member and not is_member:
        action = "left"
        
    if action:
        event_date = event.date or datetime.now()
        username = user.username or user.first_name or str(user.id)
        await record_membership_event(event.chat.id, user.id, username, action, event_date)

if __name__ == "__main__":
    if not API_ID or not API_HASH:
        print("Не заданы TELEGRAM_API_ID и TELEGRAM_API_HASH в .env")
    else:
        print("Запуск юзербота-слушателя подписок/отписок...")
        app.run()
