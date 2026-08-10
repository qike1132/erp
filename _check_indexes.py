"""检查 customer_sampling_part 表的索引和约束状态"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from sqlalchemy import text
from fastapi_app.core.database import async_engine


async def check_indexes():
    """查看 customer_sampling_part 表的所有索引"""
    async with async_engine.connect() as conn:
        # 查看所有索引
        result = await conn.execute(text(
            "SELECT indexname, indexdef FROM pg_indexes "
            "WHERE tablename = 'customer_sampling_part' ORDER BY indexname"
        ))
        rows = result.fetchall()
        print("=" * 80)
        print("customer_sampling_part 表的索引:")
        print("=" * 80)
        for row in rows:
            print(f"  索引名: {row[0]}")
            print(f"  定义:   {row[1]}")
            print()

        # 查看所有约束
        result = await conn.execute(text(
            "SELECT conname, contype, pg_get_constraintdef(oid) as def "
            "FROM pg_constraint WHERE conrelid = 'customer_sampling_part'::regclass "
            "ORDER BY conname"
        ))
        rows = result.fetchall()
        print("=" * 80)
        print("customer_sampling_part 表的约束:")
        print("=" * 80)
        for row in rows:
            contype_map = {'u': 'UNIQUE', 'c': 'CHECK', 'p': 'PRIMARY KEY', 'f': 'FOREIGN KEY'}
            print(f"  约束名: {row[0]}")
            print(f"  类型:   {contype_map.get(row[1], row[1])}")
            print(f"  定义:   {row[2]}")
            print()

        # 检查 fabric_color_no 字段是否存在
        result = await conn.execute(text(
            "SELECT column_name, data_type FROM information_schema.columns "
            "WHERE table_name = 'customer_sampling_part' AND column_name = 'fabric_color_no'"
        ))
        row = result.fetchone()
        print("=" * 80)
        print("fabric_color_no 字段:")
        print("=" * 80)
        if row:
            print(f"  存在, 类型: {row[1]}")
        else:
            print("  不存在!")

        # 检查 alembic 版本
        result = await conn.execute(text(
            "SELECT version_num FROM alembic_version"
        ))
        row = result.fetchone()
        print()
        print("=" * 80)
        print("当前 Alembic 版本:")
        print("=" * 80)
        print(f"  {row[0] if row else '未知'}")


if __name__ == '__main__':
    asyncio.run(check_indexes())
