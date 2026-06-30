import asyncio
from aiogram import Bot
from modules.config import API_TOKEN

async def main():
    bot = Bot(token=API_TOKEN)
    try:
        me = await bot.get_me()
        print('OK', me.username, me.id)
    except Exception as e:
        print('ERR', e)
    finally:
        await bot.session.close()
        await bot.close()

if __name__ == '__main__':
    loop = asyncio.new_event_loop()
    loop.run_until_complete(main())
