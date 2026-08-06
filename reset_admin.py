import asyncio
from fastapi_app.core.database import _init_async_engine, _AsyncSessionLocal
from fastapi_app.core.security import hash_password
from sqlalchemy import text

async def main():
    _init_async_engine()
    new_hash = hash_password("admin123")
    async with _AsyncSessionLocal() as s:
        await s.execute(text('UPDATE "user" SET password = :pw WHERE username = :u'), {"pw": new_hash, "u": "admin"})
        await s.commit()
        print("admin password reset to admin123")

asyncio.run(main())
