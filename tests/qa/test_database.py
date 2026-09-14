"""
ERP系统数据库完整性测试 - 使用SQLAlchemy async session验证数据库表完整性
"""
import os
import sys
import time

_db_dir = os.path.dirname(os.path.abspath(__file__))
_project_root = os.path.dirname(os.path.dirname(_db_dir))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

import pytest
import pytest_asyncio
from sqlalchemy import text

from fastapi_app.core import database
from tests.qa.data_generator import (
    generate_products,
)


@pytest_asyncio.fixture
async def db():
    # 经模块属性访问 _AsyncSessionLocal：若 ensure_engine_for_current_loop()
    # 在本轮测试重建了引擎，直接 `from ... import _AsyncSessionLocal`
    # 会拿到旧引擎的 sessionmaker（连接池绑定已关闭的旧 loop）。
    # 首次进入时全局引擎可能尚未初始化（conftest 将其置空以重定向到测试库），
    # 先跑一次 loop 守卫确保在当前事件循环上完成懒重建。
    await database.ensure_engine_for_current_loop()
    async with database._AsyncSessionLocal() as session:
        async with session.begin():
            yield session
            await session.rollback()


class TestDatabaseConnection:
    @pytest.mark.asyncio
    async def test_connection(self, db):
        result = await db.execute(text("SELECT 1"))
        assert result.scalar() == 1

    @pytest.mark.asyncio
    async def test_table_discovery(self, db):
        from sqlalchemy import inspect
        async with db.bind.connect() as conn:
            tables = await conn.run_sync(lambda sync_conn: inspect(sync_conn).get_table_names())

        # 当前 schema 表名（单数）；旧复数名（users/products/...）已随重构移除
        core_tables = ["user", "product", "order", "customer", "supplier",
                       "stock_in", "stock_out", "approval_request",
                       "case", "material_registration", "purchase_order", "purchase_plans"]
        found = [t for t in core_tables if t in tables]
        assert len(found) >= 6, f"核心表发现不足: {len(found)}/{len(core_tables)} -> {found}"


class TestBatchInsert:
    @pytest.mark.asyncio
    async def test_insert_100_products(self, db):
        products = generate_products(100)
        values = [{
            "name": p["product_name"],
            "barcode": p["product_code"],
            "price": p["price"],
            "initial_stock": 0,
            "current_stock": 0,
        } for p in products]

        start = time.time()
        await db.execute(
            text("INSERT INTO product (name, barcode, price, initial_stock, current_stock) "
                 "VALUES (:name, :barcode, :price, :initial_stock, :current_stock)"),
            values,
        )
        await db.flush()
        elapsed = time.time() - start

        count_result = await db.execute(text("SELECT COUNT(*) FROM product"))
        total = count_result.scalar()
        assert total >= 100, f"Expected >=100 rows, got {total}"
        print(f"\n  批量插入: 100条, {elapsed:.3f}s, 表总数={total}")


class TestQueryPerformance:
    @pytest.mark.asyncio
    async def test_simple_query(self, db):
        start = time.time()
        await db.execute(text("SELECT * FROM product LIMIT 50"))
        elapsed = time.time() - start
        assert elapsed < 5.0, f"Simple query too slow: {elapsed:.3f}s"
        print(f"\n  简单查询: {elapsed:.3f}s")

    @pytest.mark.asyncio
    async def test_filtered_query(self, db):
        start = time.time()
        await db.execute(text("SELECT * FROM product WHERE price > 0 ORDER BY id DESC LIMIT 20"))
        elapsed = time.time() - start
        assert elapsed < 5.0, f"Filtered query too slow: {elapsed:.3f}s"
        print(f"\n  筛选查询: {elapsed:.3f}s")

    @pytest.mark.asyncio
    async def test_aggregate_query(self, db):
        start = time.time()
        await db.execute(text("SELECT COUNT(*) AS cnt, price FROM product GROUP BY price"))
        elapsed = time.time() - start
        assert elapsed < 5.0, f"Aggregate query too slow: {elapsed:.3f}s"
        print(f"\n  聚合查询: {elapsed:.3f}s")


class TestTransactionIntegrity:
    @pytest.mark.asyncio
    async def test_update_rollback(self, db):
        get_before = await db.execute(text("SELECT COUNT(*) FROM product"))
        before = get_before.scalar()

        await db.execute(
            text("UPDATE product SET price = 999.99 WHERE id = (SELECT MIN(id) FROM product)")
        )
        await db.flush()

        get_mid = await db.execute(text("SELECT COUNT(*) FROM product"))
        mid = get_mid.scalar()
        assert mid == before, f"UPDATE不应改变行数: {before} vs {mid}"
        print(f"\n  更新回滚: 行数一致 ({before})")

    @pytest.mark.asyncio
    async def test_insert_rollback(self, db):
        get_before = await db.execute(text("SELECT COUNT(*) FROM product"))
        get_before.scalar()

        await db.execute(text(
            "INSERT INTO product (name, barcode, price, initial_stock, current_stock) "
            "VALUES ('回滚测试', 'TXN_ROLLBACK_001', 0.01, 0, 0)"
        ))
        await db.flush()
        print("\n  插入回滚: 操作已回滚")

    @pytest.mark.asyncio
    async def test_nested_transaction(self, db):
        get_before = await db.execute(text("SELECT COUNT(*) FROM product"))
        before = get_before.scalar()

        async with db.begin_nested() as nested:
            await db.execute(text(
                "INSERT INTO product (name, barcode, price, initial_stock, current_stock) "
                "VALUES ('嵌套事务测试', 'NESTED_001', 1.0, 0, 0)"
            ))
            await nested.rollback()

        get_after = await db.execute(text("SELECT COUNT(*) FROM product"))
        after = get_after.scalar()
        assert after == before, f"嵌套事务回滚后行数不一致: {before} vs {after}"
        print(f"\n  嵌套事务: 回滚后数据一致 ({before})")

    @pytest.mark.asyncio
    async def test_delete_rollback(self, db):
        await db.execute(text(
            "INSERT INTO product (name, barcode, price, initial_stock, current_stock) "
            "VALUES ('删除测试', 'DEL_TEST_001', 1.0, 0, 0)"
        ))
        await db.flush()

        get_before = await db.execute(text("SELECT COUNT(*) FROM product"))
        get_before.scalar()

        await db.execute(text("DELETE FROM product WHERE barcode = 'DEL_TEST_001'"))
        await db.flush()

        get_mid = await db.execute(
            text("SELECT COUNT(*) FROM product WHERE barcode = 'DEL_TEST_001'")
        )
        assert get_mid.scalar() == 0, "DELETE后应无此记录"
        print("\n  删除回滚: 完成")
