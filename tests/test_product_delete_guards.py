"""删除产品的阻塞路径回归测试（2026-09-28）

背景：``product_service.delete_product`` 的前置关联计数只覆盖
order / stock_in / stock_out 三张表，而 schema 中还有多张表的 product_id
外键会阻塞删除（order_item、purchase_plan_details、outsource_process_type、
order_outsource_process 等）。未被计数的表会在 ``db.flush()`` 处抛
IntegrityError —— 此前未被捕获，端点把它变成 500，用户只看到"删除失败"。

本文件锁定修复后的口径：
- 被历史单据引用的产品，删除必须抛 ProductDeleteError（端点映射为 400）
- 仍持有 order_item 的软删除订单同样算"被引用"，且给出具体的订单数文案
- 明细已随订单清理的软删订单不阻塞删除（订单全删的产品可正常删除）
- 仅持有 BOM 物料行的产品仍应能正常删除（ORM 级联）
"""
from datetime import UTC, datetime

import pytest
import pytest_asyncio
from sqlalchemy import delete as sa_delete
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from fastapi_app.services import product_service
from fastapi_app.services.product_service import (
    ProductDeleteError,
    ProductHasRelatedOrdersError,
)
from fastapi_app.shared_models import (
    Order,
    OrderItem,
    OutsourceProcessType,
    Product,
    ProductMaterial,
)

pytestmark = pytest.mark.integration


@pytest_asyncio.fixture
async def db(test_engine):
    """函数级会话 + 事务回滚隔离（复用会话级 test_engine）。"""
    factory = async_sessionmaker(
        test_engine, class_=AsyncSession, expire_on_commit=False, autoflush=False,
    )
    async with factory() as session:
        async with session.begin() as transaction:
            yield session
            await transaction.rollback()


def _make_product(name: str) -> Product:
    return Product(name=name, barcode=name, current_stock=0, initial_stock=0)


async def test_soft_deleted_order_blocks_product_delete(db):
    """软删订单**仍持有 order_item** 时，删除必须被业务拒绝（而非泛化的外键错误）。

    阻塞源是 order_item 对 product 的 FK NO ACTION（不是订单的软删状态本身）。
    计数以 order_item 为准，故仍给出"已关联 N 个订单"的具体文案，
    而不是走到 db.delete(product) 才被 IntegrityError 兜成泛化错误。
    """
    product = _make_product('PDEL-软删订单')
    db.add(product)
    await db.flush()

    order = Order(
        order_no='PDEL-O-001', customer='PDEL客户', order_date=datetime.now(UTC),
        product_id=product.id, quantity=1, status='待备货',
    )
    db.add(order)
    await db.flush()
    db.add(OrderItem(order_id=order.id, product_id=product.id, quantity=1))
    await db.flush()

    order.is_deleted = True
    await db.flush()

    with pytest.raises(ProductHasRelatedOrdersError):
        await product_service.delete_product(db, product.id)


async def test_product_with_only_soft_deleted_orders_can_be_deleted(db):
    """订单已软删除且明细已随订单清理的产品，应能正常删除。

    背景（2026-10-08）：关联计数曾无条件计入软删订单，导致「订单已全部删除」
    的产品仍报"已关联 N 个订单"。真实删除路径（order/commands.py）会清掉
    order_item，故软删订单不再构成外键阻塞 —— 计数应只拦活订单，
    外加仍持有 order_item 的订单（后者是真正的 FK NO ACTION 阻塞源）。
    """
    product = _make_product('PDEL-仅软删订单')
    db.add(product)
    await db.flush()

    order = Order(
        order_no='PDEL-O-002', customer='PDEL客户', order_date=datetime.now(UTC),
        product_id=product.id, quantity=1, status='待备货',
    )
    db.add(order)
    await db.flush()
    db.add(OrderItem(order_id=order.id, product_id=product.id, quantity=1))
    await db.flush()

    # 复刻真实删除路径：软删订单 + 清掉明细
    await db.execute(sa_delete(OrderItem).where(OrderItem.order_id == order.id))
    order.is_deleted = True
    await db.flush()

    await product_service.delete_product(db, product.id)
    await db.flush()

    assert await db.get(Product, product.id) is None


async def test_uncounted_fk_blocks_product_delete(db):
    """未被计数表（外发工序预设）引用时，删除也须抛业务错误而非 500。

    ``outsource_process_type.product_id`` 是 NOT NULL + NO ACTION，且不在
    delete_product 的计数里 —— 它只能靠 flush 时的 IntegrityError 暴露。
    """
    product = _make_product('PDEL-外发工序')
    db.add(product)
    await db.flush()
    db.add(OutsourceProcessType(product_id=product.id, process_type='电绣'))
    await db.flush()

    with pytest.raises(ProductDeleteError):
        await product_service.delete_product(db, product.id)


async def test_product_with_bom_rows_can_still_be_deleted(db):
    """仅持有 BOM 物料行的产品应能删除：ORM 级联负责清掉子行。"""
    product = _make_product('PDEL-有BOM')
    db.add(product)
    await db.flush()
    db.add(ProductMaterial(product_id=product.id, material_code='MAT-1'))
    await db.flush()

    await product_service.delete_product(db, product.id)
    await db.flush()

    assert await db.get(Product, product.id) is None
