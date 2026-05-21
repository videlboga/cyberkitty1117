import asyncio, json
from aiogram import Bot
from modules.config import API_TOKEN
from modules.db import load_database, save_database

async def main():
    bot = Bot(token=API_TOKEN)
    try:
        db = load_database()
        changed = False
        for cid, cdata in db.get('chats', {}).items():
            if cdata.get('title') == cid or not cdata.get('title') or cdata.get('title').startswith('Группа'):
                try:
                    chat = await bot.get_chat(cid)
                    if chat.title:
                        cdata['title'] = chat.title
                        changed = True
                        print(f"Updated title for {cid} -> {chat.title}")
                except Exception as e:
                    print(f"Error fetching {cid}: {e}")
        if changed:
            await save_database(db)
            print("DB saved.")
    finally:
        session = await bot.get_session()
        if session:
            await session.close()

if __name__ == '__main__':
    loop = asyncio.new_event_loop()
    loop.run_until_complete(main())
