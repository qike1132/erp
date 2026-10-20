"""审计 Z09-R6：test_product 夹具的用例级库存恢复。

夹具按 barcode 幂等查回**同一行**，而 ``async_db_session`` 在用例结束时会把挂起
变更提交进共享测试库——于是用例之间通过 DB 隐式传递库存状态：同一条依赖库存
数值的断言，在聚焦跑（``pytest -k``）与全量跑下可能因为初值不同而结论不同
（聚焦绿 ≠ 全量绿）。

本文件锁住修复后的两条契约：

1. **进入用例时**库存归位到基准值，不继承上一个用例留下的漂移；
2. **退出用例时**库存写回基准值，不把漂移留给下一个用例。

夹具声明顺序即 pytest 的搭建/拆除顺序（搭建按签名序，拆除按后进先出）：
``stock_drift`` → ``probe_stock_after_teardown`` → ``test_product``。
于是漂移在 ``test_product`` 搭建**之前**写入（验证「进入用例归位」），
而探针夹具在 ``test_product`` 拆除**之后**才跑（验证「退出用例写回」）。
"""
import pytest_asyncio
from sqlalchemy import select

from fastapi_app.shared_models.product import Product

# 夹具创建的测试产品（barcode）与基准库存，必须与 tests/conftest.py 保持一致
BARCODE = "TEST001"
BASELINE = 100


@pytest_asyncio.fixture
async def stock_drift(async_db_session):
    """把测试产品的库存改成漂移值——模拟上一个用例留在库里的状态。"""
    row = (
        await async_db_session.execute(
            select(Product).where(Product.barcode == BARCODE)
        )
    ).scalar_one_or_none()
    if row is None:
        async_db_session.add(
            Product(
                name="测试产品",
                barcode=BARCODE,
                current_stock=777,
                initial_stock=BASELINE,
            )
        )
    else:
        row.current_stock = 777
    await async_db_session.commit()


@pytest_asyncio.fixture
async def probe_stock_after_teardown(async_db_session):
    """在 test_product 夹具 teardown 之后读取库里的库存值。"""
    yield
    row = (
        await async_db_session.execute(
            select(Product.current_stock).where(Product.barcode == BARCODE)
        )
    ).scalar_one()
    assert row == BASELINE, (
        f"用例结束后库存应写回 {BASELINE}，实际 {row}——用例之间的隐式状态传递未被阻断"
    )


async def test_fixture_resets_stock_on_entry_and_restores_on_exit(
    async_db_session, stock_drift, probe_stock_after_teardown, test_product
):
    """进入用例归位、退出用例写回，两端都不让库存漂移跨用例传递。"""
    # 夹具搭建时读到的应是漂移值 777，搭建过程必须把它归位到基准值
    assert test_product.current_stock == BASELINE, (
        f"用例开始时库存应归位到 {BASELINE}，实际 {test_product.current_stock}——继承了上一个用例的漂移"
    )

    # 用例内再制造一次漂移：teardown 应写回基准值（由探针夹具在 teardown 之后断言）
    test_product.current_stock = 555
    await async_db_session.commit()
