import sqlite3
import json
from datetime import datetime as dt

db_path = '/home/cyberkitty/Projects/bot-ne-molchi/storage/activity.sqlite3'
json_path = '/home/cyberkitty/Projects/servertans/summary_bot/users_database.json'

with open(json_path, 'r', encoding='utf-8') as f:
    target_db = json.load(f)

if 'chats' not in target_db: target_db['chats'] = {}
if 'users' not in target_db: target_db['users'] = {}

conn = sqlite3.connect(db_path)
cursor = conn.cursor()

# Migrate Users
cursor.execute("SELECT user_id, full_name, username FROM members")
for row in cursor.fetchall():
    uid = str(row[0])
    target_db['users'][uid] = target_db['users'].get(uid, {})
    target_db['users'][uid]['username'] = row[2] or row[1] or "Unknown"

# Migrate Messages
cursor.execute("SELECT chat_id, message_id, user_id, posted_at FROM messages")
for row in cursor.fetchall():
    chat_id = str(row[0])
    msg_id = row[1]
    uid = str(row[2])
    posted_at = row[3] # Usually ISO format like 2026-04-22 10:20:30 or similar
    
    if chat_id not in target_db['chats']:
        target_db['chats'][chat_id] = {'admins': [], 'settings': {}, 'history': {}, 'reactions': {}}
    
    if 'history' not in target_db['chats'][chat_id]:
        target_db['chats'][chat_id]['history'] = {}
        
    try:
        date_str = posted_at.split('T')[0] if 'T' in posted_at else posted_at.split(' ')[0]
    except Exception:
        date_str = str(dt.now().date())
        
    if date_str not in target_db['chats'][chat_id]['history']:
        target_db['chats'][chat_id]['history'][date_str] = []
        
    link_base = f"https://t.me/c/{chat_id[4:] if chat_id.startswith('-100') else chat_id}/{msg_id}"
    
    # avoid duplicates
    exists = any(m.get('link_to_message') == link_base for m in target_db['chats'][chat_id]['history'][date_str])
    if not exists:
        target_db['chats'][chat_id]['history'][date_str].append({
            "user_id": uid,
            "link_to_message": link_base,
            "text_in_msg": "", # no text in bot-ne-molchi
            "timestamp": posted_at
        })

# Migrate Reactions
cursor.execute("SELECT chat_id, message_id, reactor_user_id, delta, at FROM message_reaction_events")
for row in cursor.fetchall():
    chat_id = str(row[0])
    msg_id = row[1]
    reactor_uid = str(row[2])
    delta = row[3]
    at = row[4]
    
    if chat_id not in target_db['chats']:
        target_db['chats'][chat_id] = {'admins': [], 'settings': {}, 'history': {}, 'reactions': {}}
        
    if 'reactions' not in target_db['chats'][chat_id]:
        target_db['chats'][chat_id]['reactions'] = {}
        
    try:
        date_str = at.split('T')[0] if 'T' in at else at.split(' ')[0]
    except Exception:
        date_str = str(dt.now().date())
        
    if date_str not in target_db['chats'][chat_id]['reactions']:
        target_db['chats'][chat_id]['reactions'][date_str] = []
        
    target_db['chats'][chat_id]['reactions'][date_str].append({
        "reactor_user_id": reactor_uid,
        "message_id": msg_id,
        "delta": delta,
        "timestamp": at
    })

with open(json_path, 'w', encoding='utf-8') as f:
    json.dump(target_db, f, ensure_ascii=False, indent=4)

print("Migration completed.")
# rsync back to proxy
