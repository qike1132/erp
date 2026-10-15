"""登录压测探针（**不是** pytest 用例）。

⚠️ 2026-10-15 修复：本文件原名 `test_login_detail.py`，`python_files = test_*.py` +
`asyncio_mode = auto`（pytest.ini:4/9）会把 `test_login` 当用例收集执行——它向
`http://127.0.0.1:5002`（生产 API）真实 POST 5 次 admin 登录（写生产 Redis 限流计数），
且**零断言**，返回什么都"通过"（假绿）。与 2026-10-03 `test_auth.py` 同类前科。

修复口径与 `test_auth.py` 一致：改名为 `login_probe.py` 脱离 pytest 收集模式，
只有显式 `python tests/stress/login_probe.py` 才执行。
"""
import asyncio

import aiohttp

BASE_URL = "http://127.0.0.1:5002"


async def _probe():
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
    asyncio.run(_probe())
