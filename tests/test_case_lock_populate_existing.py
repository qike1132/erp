"""皮套行锁必须刷新身份映射（2026-10-17 审计 AUD-02）

缺陷：find_case_locked 先无锁 SELECT 把 Case 载入 session 身份映射，再
with_for_update 锁定查询。SQLAlchemy 默认不会用锁定读结果刷新已有对象——
锁拿到了、字段仍是锁前旧值，后续负库存校验与 current_stock 直写基于旧值，
并发扣减可丢失（与已修复的 F-BE-SVC-STOCK-02 同款）。

本测试用两个独立会话构造「A 先读、B 改并提交、A 再锁定读」的真实序列。
"""
import pytest
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from fastapi_app.services.batch_service import find_case_locked
from fastapi_app.shared_models import Case, Product


@pytest.mark.asyncio
async def test_locked_case_refreshes_stale_identity_map(test_engine, async_db_session):
    product = Product(
        name='锁测试产品', barcode='LOCKTEST001', current_stock=100, initial_stock=100,
    )
    async_db_session.add(product)
    await async_db_session.flush()
    case = Case(product_id=product.id, name='锁测试皮套', current_stock=100)
    async_db_session.add(case)
    await async_db_session.commit()

    case_id = case.id
    product_name = product.name

    factory = async_sessionmaker(
        test_engine, class_=AsyncSession, expire_on_commit=False, autoflush=False,
    )
    async with factory() as session_a, factory() as session_b:
        # A：无锁读，把 Case 放进身份映射（模拟 find_case_locked 的前置 SELECT）
        loaded = (await session_a.execute(select(Case).where(Case.id == case_id))).scalar_one()
        assert loaded.current_stock == 100

        # B：另一事务扣减并提交
        await session_b.execute(
            update(Case).where(Case.id == case_id).values(current_stock=40)
        )
        await session_b.commit()

        # A：走锁定读——必须看到 B 已提交的 40，而不是身份映射里的旧值 100
        found, err = await find_case_locked(session_a, product_name)
        assert err is None
        assert found is not None
        assert found.current_stock == 40, (
            '锁定读返回了身份映射中的旧值：populate_existing 缺失，并发扣减会丢失'
        )
