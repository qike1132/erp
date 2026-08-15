"""临时验证脚本：创建临时用户验证登录后 /outsource 跳转，用完即删"""
import asyncio

from fastapi_app.core.database import _init_async_engine, _AsyncSessionLocal
from fastapi_app.core.security import hash_password
from sqlalchemy import text


async def main():
    _init_async_engine()
    async with _AsyncSessionLocal() as s:
        await s.execute(text('DELETE FROM "user" WHERE username=:u'), {"u": "__verify_tmp"})
        await s.execute(
            text('INSERT INTO "user" (username, password, is_super, status) VALUES (:u,:p,true,true)'),
            {"u": "__verify_tmp", "p": hash_password("TmpPass_2026")},
        )
        await s.commit()
        print("temp user created")


asyncio.run(main())
