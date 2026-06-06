import asyncio
from sqlalchemy import text
from fastapi_app.core.database import async_engine

async def check():
    async with async_engine.connect() as conn:
        # What does the server think today is?
        r = await conn.execute(text("SELECT CURRENT_DATE, CURRENT_TIMESTAMP, now()"))
        row = r.fetchone()
        print(f"CURRENT_DATE: {row[0]}")
        print(f"CURRENT_TIMESTAMP: {row[1]}")
        print(f"now(): {row[2]}")

        # Count records for each table using CURRENT_DATE
        for table, col in [("order", "order_date"), ("stock_in", "stockin_date"), ("stock_out", "stockout_date")]:
            r = await conn.execute(text(f"SELECT count(*) FROM {table} WHERE {col} >= CURRENT_DATE"))
            print(f"{table} >= CURRENT_DATE: {r.scalar()}")

        # Count records using CST midnight explicit
        r = await conn.execute(text("SELECT count(*) FROM \"order\" WHERE order_date >= '2026-06-04 16:00:00+00'"))
        print(f"order >= June5 CST midnight (UTC 16:00): {r.scalar()}")

        # Recent records
        r = await conn.execute(text("SELECT id, order_date FROM \"order\" ORDER BY order_date DESC LIMIT 3"))
        for row in r.fetchall():
            print(f"  Order id={row[0]}, order_date={row[1]}")

asyncio.run(check())
