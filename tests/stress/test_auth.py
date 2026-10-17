"""登录压测探针（**不是** pytest 用例）。

⚠️ 2026-10-03 第五轮审计：本文件此前把 `asyncio.run(test())` 写在**模块级**，
而 `testpaths = tests` 会 import 它 → **每次跑 pytest 都在向 `http://127.0.0.1:5002`
发 10 次 admin 登录**（打真实后端、写登录限流计数），且不产生任何用例（假绿）。
现加 `__main__` 守卫：只有显式 `python tests/stress/test_auth.py` 才执行。
"""
import sys as _sys, os as _os
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
from _prod_guard import require_non_production
import asyncio

import aiohttp


async def _probe():
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


if __name__ == '__main__':
    require_non_production(BASE_URL)  # fail-closed 守卫（F-TEST-BE-TOP-02）
    asyncio.run(_probe())
