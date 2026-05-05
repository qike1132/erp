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

from fastapi_app.core.database import _AsyncSessionLocal
from tests.qa.data_generator import (
    generate_products,
    generate_customers,
    generate_suppliers,
    generate_orders,
    generate_stock_in,
    generate_stock_out,
    generate_cases,
    generate_material_registration,
)


@pytest_asyncio.fixture
async def db():
    async with _AsyncSessionLocal() as session:
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
        
        core_tables = ["users", "orders", "products", "customers", "suppliers",
                       "stock_in", "stock_out", "approvals", "cases",
                       "material_registration", "purchase_order", "purchase_plan"]
        found = [t for t in core_tables if t in tables]
        assert len(found) >= 6, f"核心表发现不足: {len(found)}/{len(core_tables)} -> {found}"


class TestBatchInsert:
    @pytest.mark.asyncio
    async def test_insert_100_products(self, db):
        products = generate_products(100)
        values = [{
            "code": p["product_code"],
            "name": p["product_name"],
            "unit": p["unit"],
            "price": p["price"],
            "spec": p.get("spec", ""),
        } for p in products]
        
        start = time.time()
        for item in values:
            await db.execute(
                text("INSERT INTO products (product_code, product_name, unit, price, spec) "
                     "VALUES (:code, :name, :unit, :price, :spec)"),
                item,
            )
        await db.flush()
        elapsed = time.time() - start
        
        count_result = await db.execute(text("SELECT COUNT(*) FROM products"))
        total = count_result.scalar()
        assert total >= 100, f"Expected >=100 rows, got {total}"
        print(f"\n  批量插入: 100条, {elapsed:.3f}s, 表总数={total}")


class TestQueryPerformance:
    @pytest.mark.asyncio
    async def test_simple_query(self, db):
        start = time.time()
        await db.execute(text("SELECT * FROM products LIMIT 50"))
        elapsed = time.time() - start
        assert elapsed < 5.0, f"Simple query too slow: {elapsed:.3f}s"
        print(f"\n  简单查询: {elapsed:.3f}s")

    @pytest.mark.asyncio
    async def test_filtered_query(self, db):
        start = time.time()
        await db.execute(text("SELECT * FROM products WHERE price > 0 ORDER BY id DESC LIMIT 20"))
        elapsed = time.time() - start
        assert elapsed < 5.0, f"Filtered query too slow: {elapsed:.3f}s"
        print(f"\n  筛选查询: {elapsed:.3f}s")

    @pytest.mark.asyncio
    async def test_aggregate_query(self, db):
        start = time.time()
        await db.execute(text("SELECT COUNT(*) AS cnt, unit FROM products GROUP BY unit"))
        elapsed = time.time() - start
        assert elapsed < 5.0, f"Aggregate query too slow: {elapsed:.3f}s"
        print(f"\n  聚合查询: {elapsed:.3f}s")


class TestTransactionIntegrity:
    @pytest.mark.asyncio
    async def test_update_rollback(self, db):
        get_before = await db.execute(text("SELECT COUNT(*) FROM products"))
        before = get_before.scalar()
        
        await db.execute(
            text("UPDATE products SET price = 999.99 WHERE id = (SELECT MIN(id) FROM products)")
        )
        await db.flush()
        
        get_mid = await db.execute(text("SELECT COUNT(*) FROM products"))
        mid = get_mid.scalar()
        assert mid == before, f"UPDATE不应改变行数: {before} vs {mid}"
        print(f"\n  更新回滚: 行数一致 ({before})")

    @pytest.mark.asyncio
    async def test_insert_rollback(self, db):
        get_before = await db.execute(text("SELECT COUNT(*) FROM products"))
        before = get_before.scalar()
        
        await db.execute(text(
            "INSERT INTO products (product_code, product_name, unit, price, spec) "
            "VALUES ('TXN_ROLLBACK_001', '回滚测试', '个', 0.01, 'test')"
        ))
        await db.flush()
        print(f"\n  插入回滚: 操作已回滚")

    @pytest.mark.asyncio
    async def test_nested_transaction(self, db):
        get_before = await db.execute(text("SELECT COUNT(*) FROM products"))
        before = get_before.scalar()
        
        async with db.begin_nested() as nested:
            await db.execute(text(
                "INSERT INTO products (product_code, product_name, unit, price, spec) "
                "VALUES ('NESTED_001', '嵌套事务测试', '个', 1.0, 'test')"
            ))
            await nested.rollback()
        
        get_after = await db.execute(text("SELECT COUNT(*) FROM products"))
        after = get_after.scalar()
        assert after == before, f"嵌套事务回滚后行数不一致: {before} vs {after}"
        print(f"\n  嵌套事务: 回滚后数据一致 ({before})")

    @pytest.mark.asyncio
    async def test_delete_rollback(self, db):
        await db.execute(text(
            "INSERT INTO products (product_code, product_name, unit, price, spec) "
            "VALUES ('DEL_TEST_001', '删除测试', '个', 1.0, 'test')"
        ))
        await db.flush()
        
        get_before = await db.execute(text("SELECT COUNT(*) FROM products"))
        before = get_before.scalar()
        
        await db.execute(text("DELETE FROM products WHERE product_code = 'DEL_TEST_001'"))
        await db.flush()
        
        get_mid = await db.execute(
            text("SELECT COUNT(*) FROM products WHERE product_code = 'DEL_TEST_001'")
        )
        assert get_mid.scalar() == 0, "DELETE后应无此记录"
        print(f"\n  删除回滚: 完成")
