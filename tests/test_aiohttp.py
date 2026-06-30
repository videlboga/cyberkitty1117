import asyncio
import aiohttp

async def main():
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get('https://api.telegram.org') as response:
                print(response.status)
    except Exception as e:
        print(f"Error: {e}")

asyncio.run(main())
