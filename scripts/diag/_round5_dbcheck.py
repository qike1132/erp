"""Round-5 只读核验：alembic_version + stock_return 关键列可空性。结果打印到 stdout。"""
import asyncio
import re

import asyncpg

env = {}
with open(r'D:\erp_system\.env', encoding='utf-8') as f:
    for line in f:
        m = re.match(r'\s*([A-Z_]+)\s*=\s*(.*)', line)
        if m:
            env[m.group(1)] = m.group(2).strip().strip('"').strip("'")


async def main():
    conn = await asyncpg.connect(
        user=env['DB_USER'], password=env['DB_PASSWORD'],
        host=env.get('DB_HOST', '127.0.0.1'),
        port=int(env.get('DB_PORT', '5432')),
        database=env['DB_NAME'],
    )
    v = await conn.fetchval('SELECT version_num FROM alembic_version')
    n = await conn.fetchval(
        "SELECT is_nullable FROM information_schema.columns "
        "WHERE table_name='stock_return' AND column_name='stockout_id'"
    )
    s = await conn.fetchval(
        "SELECT is_nullable FROM information_schema.columns "
        "WHERE table_name='stock_return' AND column_name='status'"
    )
    print('ALEMBIC_VERSION =', v)
    print('STOCKOUT_ID_NULLABLE =', n)
    print('STATUS_NULLABLE =', s)
    await conn.close()


asyncio.run(main())
