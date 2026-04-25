import asyncio
import aiohttp

async def test():
    async with aiohttp.ClientSession() as session:
        for i in range(10):
            try:
                async with session.post(
                    'http://127.0.0.1:5002/api/v1/auth/login',
                    json={'username': 'admin', 'password': 'admin123'},
                    timeout=aiohttp.ClientTimeout(total=5)
                ) as resp:
                    print(f'{i}: status={resp.status}')
                    if resp.status == 200:
                        data = await resp.json()
                        token = data.get("access_token", "")
                        print(f'   token: {token[:50]}...')
            except Exception as e:
                print(f'{i}: error - {e}')
            await asyncio.sleep(0.1)

asyncio.run(test())
