"""根集成夹具隔离：业务行按用例唯一化，不读取或修复共享脏状态。"""
import pytest_asyncio

from fastapi_app.shared_models.product import Product


@pytest_asyncio.fixture
async def legacy_stock_drift(async_db_session):
    """放入旧固定条码的脏数据，证明新夹具不会复用它。"""
    from sqlalchemy import select

    row = (
        await async_db_session.execute(
            select(Product).where(Product.barcode == "TEST001")
        )
    ).scalar_one_or_none()
    if row is None:
        row = Product(
            name="旧共享测试产品",
            barcode="TEST001",
            current_stock=777,
            initial_stock=100,
        )
        async_db_session.add(row)
    else:
        row.current_stock = 777
    await async_db_session.flush()


async def test_product_does_not_reuse_legacy_drift_row(
    async_db_session, legacy_stock_drift, test_product
):
    """新产品的 barcode/库存不得继承旧固定行；用例内修改也不依赖 teardown 复原。"""
    assert test_product.barcode != "TEST001"
    assert test_product.current_stock == 100
    test_product.current_stock = 555
    await async_db_session.commit()


async def test_business_fixtures_start_with_clean_independent_rows(
    test_order, test_stockin, test_stockout, test_product
):
    """同一用例共享新产品，但订单/备货/出货各自为全新的独立业务行。"""
    assert {test_order.product_id, test_stockin.product_id, test_stockout.product_id} == {
        test_product.id
    }
    assert test_order.status == "待备货"
    assert test_order.quantity == 50
    assert test_order.is_deleted is False
    assert test_stockin.quantity == 50
    assert test_stockout.quantity == 20
    assert test_stockout.returned_quantity == 0
    numbers = {test_order.order_no, test_stockin.stockin_no, test_stockout.stockout_no}
    assert len(numbers) == 3
    assert not numbers & {"ORD-TEST-001", "SI-TEST-001", "SO-TEST-001"}
