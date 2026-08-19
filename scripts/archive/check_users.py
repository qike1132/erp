import asyncio

from sqlalchemy import text

from fastapi_app.core.database import _AsyncSessionLocal, _init_async_engine


async def main():
    _init_async_engine()
    async with _AsyncSessionLocal() as s:
        r = await s.execute(text('SELECT id, username, is_super, status FROM "user" LIMIT 10'))
        for row in r.fetchall():
            print(row)

asyncio.run(main())
