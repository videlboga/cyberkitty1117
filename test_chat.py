import asyncio
from aiogram import Bot
from modules.config import API_TOKEN

async def main():
    bot = Bot(token=API_TOKEN)
    try:
        chat = await bot.get_chat('-1002498790496')
        print("TITLE:", chat.title)
    except Exception as e:
        print("ERROR:", e)
    finally:
        session = await bot.session
        if session:
            await session.close()
        await bot.close()

if __name__ == '__main__':
    loop = asyncio.new_event_loop()
    loop.run_until_complete(main())
