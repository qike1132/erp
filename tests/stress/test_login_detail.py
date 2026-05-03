import asyncio

import aiohttp

BASE_URL = "http://127.0.0.1:5002"

async def test_login():
    async with aiohttp.ClientSession() as session:
        for i in range(5):
            try:
                async with session.post(
                    f"{BASE_URL}/api/v1/auth/login",
                    json={"username": "admin", "password": "admin123"},
                    timeout=aiohttp.ClientTimeout(total=5)
                ) as resp:
                    text = await resp.text()
                    print(f"尝试 {i+1}: 状态={resp.status}, 响应={text[:100]}")
            except Exception as e:
                print(f"尝试 {i+1}: 异常={e}")
            await asyncio.sleep(0.5)

if __name__ == "__main__":
    asyncio.run(test_login())
