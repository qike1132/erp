"""BOM 续提的真实 PostgreSQL 幂等与来源锁回归。"""
from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from fastapi_app.core.pg_locks import acquire_advisory_lock_async, number_lock_key
from fastapi_app.services import purchase_order_generate as generate_module
from fastapi_app.services.purchase_order_generate import (
    generate_purchase_orders_from_customer_orders,
)
from fastapi_app.shared_models import (
    Order,
    OrderItem,
    ProductMaterial,
    PurchaseOrder,
    PurchaseOrderSku,
    StockIn,
)

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture(autouse=True)
async def _numbering_engine_on_test_db():
    """单号分配走全局会话工厂；直调服务前把它指向测试库。"""
    from fastapi_app.core.database import ensure_engine_for_current_loop

    await ensure_engine_for_current_loop()


def _unique(prefix: str) -> str:
    return f"{prefix}-{uuid4().hex[:12]}"


async def _ensure_bom(db: AsyncSession, product_id: int) -> None:
    existing = await db.scalar(
        select(ProductMaterial.id).where(
            ProductMaterial.product_id == product_id,
            ProductMaterial.role_id.is_(None),
        )
    )
    if existing is None:
        db.add(ProductMaterial(
            product_id=product_id,
            cotton_usage=2,
            material_code=_unique("RESUME-MAT")[:50],
            supplier_name="续提测试供应商",
        ))
        await db.flush()


async def _new_order(db: AsyncSession, product_id: int, *, order_id: int | None = None) -> Order:
    order = Order(
        **({"id": order_id} if order_id is not None else {}),
        order_no=_unique("RESUME-ORDER")[:20],
        customer="续提测试客户",
        product_id=product_id,
        quantity=3,
        status="待备货",
        is_deleted=False,
        order_date=datetime.now(UTC),
    )
    db.add(order)
    await db.flush()
    return order


async def _new_stockin(db: AsyncSession, product_id: int, *, stockin_id: int) -> StockIn:
    stockin = StockIn(
        id=stockin_id,
        stockin_no=_unique("RESUME-SI")[:20],
        customer="续提测试客户",
        product_id=product_id,
        quantity=3,
        stockin_date=datetime.now(UTC),
    )
    db.add(stockin)
    await db.flush()
    return stockin


async def _new_product_without_bom(db: AsyncSession):
    from fastapi_app.shared_models import Product

    product = Product(
        name=_unique("RESUME-PRODUCT")[:100],
        barcode=_unique("RESUME-BAR")[:50],
        initial_stock=0,
        current_stock=0,
    )
    db.add(product)
    await db.flush()
    return product


async def _new_multi_sku_order(
    db: AsyncSession, products: list, *, quantities: list[int],
) -> Order:
    order = await _new_order(db, products[0].id)
    order.product_id = products[0].id
    order.quantity = sum(quantities)
    for product, quantity in zip(products, quantities, strict=True):
        db.add(OrderItem(
            order_id=order.id,
            product_id=product.id,
            product_name=product.name,
            quantity=quantity,
        ))
    await db.flush()
    return order


async def _linked_po(
    db: AsyncSession,
    *,
    record_type: str,
    source_id: int,
    status: str,
    product_name: str,
) -> PurchaseOrder:
    po = PurchaseOrder(
        order_no=_unique("RESUME-PO")[:30],
        customer_name="续提测试客户",
        supplier_name="续提测试供应商",
        status=status,
        remark="已补录内容不得删除",
        source_order_ids=json.dumps([source_id]),
        product_quantity=3,
    )
    db.add(po)
    await db.flush()
    db.add(PurchaseOrderSku(
        po_id=po.id,
        product_name=product_name,
        order_qty=3,
        source_record_type=record_type,
        source_order_id=source_id,
    ))
    await db.flush()
    return po


async def _legacy_po(db: AsyncSession, source_id: int) -> PurchaseOrder:
    """模拟无 typed SKU 快照、只有裸 JSON 的历史采购单。"""
    po = PurchaseOrder(
        order_no=_unique("RESUME-LEGACY")[:30],
        customer_name="续提测试客户",
        supplier_name="续提测试供应商",
        status="completed",
        source_order_ids=json.dumps([source_id]),
        product_quantity=3,
    )
    db.add(po)
    await db.flush()
    return po


async def _generate(
    db: AsyncSession,
    composite_ids: list[str],
    *,
    key: str = "",
    actor_id: int = 1,
) -> dict:
    kwargs = {"actor_id": actor_id} if key else {}
    return await generate_purchase_orders_from_customer_orders(
        db, composite_ids, idempotency_key=key, **kwargs
    )


async def test_same_key_replays_first_success_without_new_po(
    async_db_session, test_product, admin_user
):
    db = async_db_session
    await _ensure_bom(db, test_product.id)
    order = await _new_order(db, test_product.id)
    key = _unique("resume-key")

    first = await _generate(db, [f"order:{order.id}"], key=key, actor_id=admin_user.id)
    second = await _generate(db, [f"order:{order.id}"], key=key, actor_id=admin_user.id)

    assert first["success"] is True and first["created_count"] == 1
    assert second["success"] is True and second["idempotent"] is True
    assert second["created_count"] == 0
    assert "复用首次生成结果" in second["message"]
    assert [o["id"] for o in second["orders"]] == [o["id"] for o in first["orders"]]


async def test_cross_transaction_same_key_replays_after_commit(
    async_db_session, test_product, test_engine, admin_user
):
    """模拟首次已提交但响应丢失：新事务同键只能重放，不得重新生成。"""
    db = async_db_session
    await _ensure_bom(db, test_product.id)
    order = await _new_order(db, test_product.id)
    composite_id = f"order:{order.id}"
    key = _unique("resume-cross-tx")
    await db.commit()
    factory = async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)

    async with factory() as first_session:
        async with first_session.begin():
            first = await _generate(
                first_session, [composite_id], key=key, actor_id=admin_user.id,
            )
    async with factory() as retry_session:
        async with retry_session.begin():
            second = await _generate(
                retry_session, [composite_id], key=key, actor_id=admin_user.id,
            )

    assert first["created_count"] == 1
    assert second["idempotent"] is True and second["created_count"] == 0
    assert "复用首次生成结果" in second["message"]
    assert [o["id"] for o in second["orders"]] == [o["id"] for o in first["orders"]]


async def test_legacy_ambiguous_source_fails_closed(
    async_db_session, test_product,
):
    """同号 Order/StockIn 且历史单无 typed SKU 时不得猜测来源。"""
    db = async_db_session
    await _ensure_bom(db, test_product.id)
    source_id = 800_000 + (uuid4().int % 10_000)
    order = await _new_order(db, test_product.id, order_id=source_id)
    await _new_stockin(db, test_product.id, stockin_id=source_id)
    await _legacy_po(db, source_id)

    result = await _generate(db, [f"order:{source_id}"])

    assert result["success"] is False
    assert result["code"] == "SOURCE_INVALID"
    assert result["created_count"] == 0
    assert order.status == "待备货"


async def test_zero_generated_orders_roll_back(
    async_db_session, test_product, monkeypatch,
):
    """算法未产出订单时必须抛错回滚，不得返回成功 0 单。"""
    db = async_db_session
    await _ensure_bom(db, test_product.id)
    order = await _new_order(db, test_product.id)

    async def _empty(*args, **kwargs):
        return []

    monkeypatch.setattr(generate_module, "_generate_per_customer", _empty)

    with pytest.raises(RuntimeError, match="0 单"):
        await _generate(db, [f"order:{order.id}"])
    assert order.status == "待备货"
    count = await db.scalar(
        select(func.count()).select_from(PurchaseOrderSku).where(
            PurchaseOrderSku.source_record_type == "order",
            PurchaseOrderSku.source_order_id == order.id,
        )
    )
    assert count == 0


async def test_non_pending_source_is_invalid_without_writes(
    async_db_session, test_product,
):
    db = async_db_session
    await _ensure_bom(db, test_product.id)
    order = await _new_order(db, test_product.id)
    order.status = "已备货"
    await db.flush()

    result = await _generate(db, [f"order:{order.id}"])

    assert result["success"] is False and result["code"] == "SOURCE_INVALID"
    count = await db.scalar(
        select(func.count()).select_from(PurchaseOrderSku).where(
            PurchaseOrderSku.source_record_type == "order",
            PurchaseOrderSku.source_order_id == order.id,
        )
    )
    assert count == 0


async def test_same_key_different_payload_conflicts_before_writing(
    async_db_session, test_product, admin_user
):
    db = async_db_session
    await _ensure_bom(db, test_product.id)
    first_order = await _new_order(db, test_product.id)
    second_order = await _new_order(db, test_product.id)
    key = _unique("resume-conflict")
    await _generate(db, [f"order:{first_order.id}"], key=key, actor_id=admin_user.id)

    with pytest.raises(ValueError, match="IDEMPOTENCY_CONFLICT"):
        await _generate(db, [f"order:{second_order.id}"], key=key, actor_id=admin_user.id)
    assert second_order.status == "待备货"


async def test_completed_po_is_returned_and_never_rebuilt(
    async_db_session, test_product
):
    db = async_db_session
    await _ensure_bom(db, test_product.id)
    order = await _new_order(db, test_product.id)
    existing = await _linked_po(
        db, record_type="order", source_id=order.id,
        status="completed", product_name=test_product.name,
    )

    result = await _generate(db, [f"order:{order.id}"])

    assert result["success"] is True and result["idempotent"] is True
    assert result["created_count"] == 0
    assert [o["id"] for o in result["orders"]] == [existing.id]
    assert existing.status == "completed"
    assert existing.remark == "已补录内容不得删除"
    assert order.status == "待备货"


async def test_pending_po_is_returned_and_not_deleted_rebuilt(
    async_db_session, test_product
):
    db = async_db_session
    await _ensure_bom(db, test_product.id)
    order = await _new_order(db, test_product.id)
    existing = await _linked_po(
        db, record_type="order", source_id=order.id,
        status="pending", product_name=test_product.name,
    )

    result = await _generate(db, [f"order:{order.id}"])

    assert result["success"] is True and result["idempotent"] is True
    assert result["created_count"] == 0
    assert [o["id"] for o in result["orders"]] == [existing.id]
    assert existing.remark == "已补录内容不得删除"
    assert order.status == "待备货"


async def test_deleted_source_without_po_is_invalid_and_writes_nothing(
    async_db_session, test_product
):
    db = async_db_session
    await _ensure_bom(db, test_product.id)
    order = await _new_order(db, test_product.id)
    order_id = order.id
    await db.delete(order)
    await db.flush()

    result = await _generate(db, [f"order:{order_id}"])

    assert result["success"] is False
    assert result["code"] == "SOURCE_INVALID"
    assert result["created_count"] == 0 and result["orders"] == []
    count = await db.scalar(
        select(func.count()).select_from(PurchaseOrderSku).where(
            PurchaseOrderSku.source_record_type == "order",
            PurchaseOrderSku.source_order_id == order_id,
        )
    )
    assert count == 0


async def test_soft_deleted_source_without_po_is_invalid(
    async_db_session, test_product,
):
    """生产删除订单走 is_deleted 软删，不能只测试物理删除。"""
    db = async_db_session
    await _ensure_bom(db, test_product.id)
    order = await _new_order(db, test_product.id)
    order.is_deleted = True
    await db.flush()

    result = await _generate(db, [f"order:{order.id}"])

    assert result["success"] is False and result["code"] == "SOURCE_INVALID"
    count = await db.scalar(
        select(func.count()).select_from(PurchaseOrderSku).where(
            PurchaseOrderSku.source_record_type == "order",
            PurchaseOrderSku.source_order_id == order.id,
        )
    )
    assert count == 0


async def test_deleted_source_with_existing_po_is_still_idempotent(
    async_db_session, test_product
):
    db = async_db_session
    await _ensure_bom(db, test_product.id)
    order = await _new_order(db, test_product.id)
    order_id = order.id
    existing = await _linked_po(
        db, record_type="order", source_id=order_id,
        status="completed", product_name=test_product.name,
    )
    await db.delete(order)
    await db.flush()

    result = await _generate(db, [f"order:{order_id}"])

    assert result["success"] is True and result["idempotent"] is True
    assert result["created_count"] == 0
    assert [o["id"] for o in result["orders"]] == [existing.id]


async def test_order_and_stockin_with_same_numeric_id_never_cross_match(
    async_db_session, test_product
):
    db = async_db_session
    await _ensure_bom(db, test_product.id)
    source_id = 900_000 + (uuid4().int % 10_000)
    order = await _new_order(db, test_product.id, order_id=source_id)
    stockin = await _new_stockin(db, test_product.id, stockin_id=source_id)
    order_po = await _linked_po(
        db, record_type="order", source_id=source_id,
        status="completed", product_name=test_product.name,
    )

    stockin_result = await _generate(db, [f"stockin:{stockin.id}"])
    order_result = await _generate(db, [f"order:{order.id}"])

    assert stockin_result["created_count"] == 1, stockin_result
    assert stockin_result["orders"][0]["id"] != order_po.id
    stockin_po = await db.get(PurchaseOrder, stockin_result["orders"][0]["id"])
    assert stockin_po is not None and stockin_po.source_order_ids is None
    assert order_result["idempotent"] is True
    assert [o["id"] for o in order_result["orders"]] == [order_po.id]


async def test_missing_bom_is_explicit_and_writes_nothing(
    async_db_session,
):
    db = async_db_session
    product = await _new_product_without_bom(db)
    order = await _new_order(db, product.id)

    result = await _generate(db, [f"order:{order.id}"])

    assert result == {
        "success": False,
        "code": "MISSING_BOM",
        "message": f"产品 {product.name} 未配置 BOM",
        "created_count": 0,
        "idempotent": False,
        "orders": [],
        "missing_bom": [{"product_id": product.id, "product_name": product.name}],
    }
    assert order.status == "待备货"


async def test_multi_sku_missing_list_then_success_after_all_bom_ready(
    async_db_session, test_product,
):
    db = async_db_session
    await _ensure_bom(db, test_product.id)
    missing_product = await _new_product_without_bom(db)
    order = await _new_multi_sku_order(
        db, [test_product, missing_product], quantities=[2, 3],
    )

    missing = await _generate(db, [f"order:{order.id}"])

    assert missing["success"] is False and missing["code"] == "MISSING_BOM"
    assert missing["missing_bom"] == [{
        "product_id": missing_product.id,
        "product_name": missing_product.name,
    }]
    assert order.status == "待备货"

    await _ensure_bom(db, missing_product.id)
    result = await _generate(db, [f"order:{order.id}"])

    assert result["success"] is True and result["created_count"] == 1
    sku_rows = list((await db.execute(
        select(PurchaseOrderSku).where(
            PurchaseOrderSku.po_id == result["orders"][0]["id"],
            PurchaseOrderSku.source_record_type == "order",
            PurchaseOrderSku.source_order_id == order.id,
        )
    )).scalars().all())
    assert {row.product_name for row in sku_rows} == {
        test_product.name, missing_product.name,
    }
    assert {row.product_name: float(row.order_qty) for row in sku_rows} == {
        test_product.name: 2.0, missing_product.name: 3.0,
    }


async def test_generation_waits_for_source_advisory_lock(
    async_db_session, test_product, test_engine
):
    db = async_db_session
    await _ensure_bom(db, test_product.id)
    order = await _new_order(db, test_product.id)
    composite_id = f"order:{order.id}"
    await db.commit()
    factory = async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)
    lock_key = number_lock_key("PURCHASE_GENERATE_SOURCE", composite_id)

    async with factory() as holder, factory() as worker:
        await acquire_advisory_lock_async(holder, lock_key)
        task = asyncio.create_task(_generate(worker, [composite_id]))
        await asyncio.sleep(0.25)
        try:
            assert not task.done(), "未持有来源锁就完成生成，自动/人工可并发写同一来源"
        finally:
            await holder.commit()
        result = await asyncio.wait_for(task, timeout=10)
        await worker.rollback()

    assert result["created_count"] == 1


async def test_concurrent_generators_create_only_one_po(
    async_db_session, test_product, test_engine
):
    db = async_db_session
    await _ensure_bom(db, test_product.id)
    order = await _new_order(db, test_product.id)
    composite_id = f"order:{order.id}"
    await db.commit()
    factory = async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)

    async def run_one() -> dict:
        async with factory() as session:
            async with session.begin():
                return await _generate(session, [composite_id])

    first, second = await asyncio.gather(run_one(), run_one())

    assert first["orders"][0]["id"] == second["orders"][0]["id"]
    assert first["created_count"] + second["created_count"] == 1
    async with factory() as check:
        count = await check.scalar(
            select(func.count(func.distinct(PurchaseOrderSku.po_id))).where(
                PurchaseOrderSku.source_record_type == "order",
                PurchaseOrderSku.source_order_id == order.id,
            )
        )
    assert count == 1


async def test_concurrent_stockin_generators_use_source_lock_not_unique_index(
    async_db_session, test_product, test_engine
):
    """备货来源的 source_order_ids 为 NULL，去重只能依赖 typed 预查 + 来源锁。"""
    db = async_db_session
    await _ensure_bom(db, test_product.id)
    stockin_id = 700_000 + (uuid4().int % 10_000)
    stockin = await _new_stockin(db, test_product.id, stockin_id=stockin_id)
    composite_id = f"stockin:{stockin.id}"
    await db.commit()
    factory = async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)

    async def run_one() -> dict:
        async with factory() as session:
            async with session.begin():
                return await _generate(session, [composite_id])

    first, second = await asyncio.gather(run_one(), run_one())

    assert first["orders"][0]["id"] == second["orders"][0]["id"]
    assert first["created_count"] + second["created_count"] == 1
    async with factory() as check:
        count = await check.scalar(
            select(func.count(func.distinct(PurchaseOrderSku.po_id))).where(
                PurchaseOrderSku.source_record_type == "stockin",
                PurchaseOrderSku.source_order_id == stockin.id,
            )
        )
    assert count == 1
