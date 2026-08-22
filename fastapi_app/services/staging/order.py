"""暂存订单实体业务

从 staging_service.py 按实体拆出,行为与原实现完全一致。
"""
import logging
from datetime import UTC, datetime

from sqlalchemy import delete, func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from fastapi_app.core.exceptions import NotFoundError
from fastapi_app.core.state_machine import StagingAction, StagingStatus, staging_machine
from fastapi_app.core.validators import validate_quantity_range
from fastapi_app.services.batch_service import process_order_deduction
from fastapi_app.services.numbering import generate_order_number
from fastapi_app.services.staging._generic import (
    _generic_import_staging_from_excel,
    _generic_update_staging_entity,
    _parse_deduct_flag,
)
from fastapi_app.shared_models import InventoryLog, Order, StagingOrder
from fastapi_app.shared_models.order import ORDER_STATUS_PENDING_STOCK

logger = logging.getLogger(__name__)


def _build_order_entity(
    fields: dict, session_id: str, product_id: int | None, qty: int,
    is_validated: bool, validation_error: str, product_name: str,
) -> StagingOrder:
    deduct_stock_flag, deduct_quantity = _parse_deduct_flag(
        fields.get('deduct_stock'), qty
    )
    return StagingOrder(
        session_id=session_id,
        customer=str(fields.get('customer', '')).strip(),
        product_name=product_name,
        product_barcode='',
        product_id=product_id,
        quantity=qty,
        deduct_stock=deduct_stock_flag,
        deduct_quantity=deduct_quantity,
        note=str(fields.get('note', '') or '').strip(),
        is_validated=is_validated,
        validation_error=validation_error,
        status=StagingStatus.PENDING,
    )

def _order_extra_updates(entity, data: dict, _db: AsyncSession) -> None:
    if 'quantity' in data:
        qty = int(data['quantity'])
        validate_quantity_range(qty)
    if 'deduct_stock' in data:
        entity.deduct_stock = bool(data['deduct_stock'])
    if 'deduct_quantity' in data:
        deduct_qty = int(data['deduct_quantity'])
        if deduct_qty < 0:
            raise ValueError('抵扣数量不能为负数')
        entity.deduct_quantity = deduct_qty
        entity.deduct_stock = deduct_qty > 0
    if 'note' in data:
        entity.note = data['note']


# ==================== 暂存订单服务 ====================

async def get_staging_orders(db: AsyncSession, session_id: str, page: int = 1, per_page: int = 100) -> dict:
    """获取暂存订单列表（支持分页）"""
    base_query = select(StagingOrder).where(
        StagingOrder.session_id == session_id, StagingOrder.status == StagingStatus.PENDING
    )
    # 总数
    count_result = await db.execute(
        select(func.count(StagingOrder.id)).where(
            StagingOrder.session_id == session_id, StagingOrder.status == StagingStatus.PENDING
        )
    )
    total = count_result.scalar() or 0
    # 分页查询
    result = await db.execute(
        base_query.order_by(StagingOrder.created_at.desc())
        .offset((page - 1) * per_page).limit(per_page)
    )
    orders = result.scalars().all()
    return {'items': [order.to_dict() for order in orders], 'total': total, 'page': page, 'per_page': per_page}

async def clear_staging_orders_by_session(db: AsyncSession, session_id: str) -> int:
    result = await db.execute(
        delete(StagingOrder).where(StagingOrder.session_id == session_id)
    )
    await db.flush()
    return result.rowcount

async def clear_staging_orders(db: AsyncSession, session_id: str):
    await clear_staging_orders_by_session(db, session_id)

async def delete_staging_order(db: AsyncSession, order_id: int):
    result = await db.execute(select(StagingOrder).where(StagingOrder.id == order_id))
    order = result.scalar_one_or_none()
    if not order:
        raise NotFoundError(f"暂存订单 {order_id} 不存在")
    await db.delete(order)
    await db.flush()

async def update_staging_order(db: AsyncSession, order_id: int, data: dict) -> dict:
    return await _generic_update_staging_entity(
        db, order_id, data, StagingOrder, '暂存订单',
        extra_updates=_order_extra_updates,
    )

async def confirm_staging_orders(
    db: AsyncSession, session_id: str
) -> tuple[int, list[str]]:
    from fastapi_app.shared.stock_concurrency import get_product_for_update

    result = await db.execute(
        select(StagingOrder).where(
            StagingOrder.session_id == session_id,
            StagingOrder.status == StagingStatus.PENDING,
            StagingOrder.is_validated,
        )
    )
    staging_orders = result.scalars().all()

    if not staging_orders:
        return 0, ["没有可确认的订单"]

    confirmed = 0
    errors: list[str] = []

    try:
        for staging in staging_orders:
            try:
                async with db.begin_nested():
                    validate_quantity_range(staging.quantity)

                    order_no = await generate_order_number(db)

                    order = Order(
                        order_no=order_no,
                        customer=staging.customer,
                        order_date=staging.order_date or datetime.now(UTC).replace(tzinfo=None),
                        product_id=staging.product_id,
                        quantity=staging.quantity,
                        note=staging.note,
                        status=ORDER_STATUS_PENDING_STOCK,
                        order_type=staging.order_type or 'regular',
                        country=staging.country if staging.order_type == 'custom' else None,
                    )
                    db.add(order)
                    await db.flush()

                    product = await get_product_for_update(db, staging.product_id)
                    if not product:
                        raise ValueError(f'订单{staging.customer}-{staging.product_name}产品不存在(ID:{staging.product_id})')
                    product.current_stock += staging.quantity

                    log = InventoryLog(
                        product_id=staging.product_id,
                        change_type='订单',
                        change_quantity=staging.quantity,
                        related_id=order_no,
                        note=f'批量导入订单：{order_no}',
                    )
                    db.add(log)

                    if staging.deduct_stock and staging.deduct_quantity and staging.deduct_quantity > 0:
                        await process_order_deduction(
                            db, order,
                            staging.product_id,
                            staging.quantity,
                            deduct_stock=True,
                            custom_deduct_quantity=staging.deduct_quantity,
                            product=product,
                        )

                    # 返单自动带出外发工序：按 SKU 预设生成湖北外发工序（失败不影响订单创建）
                    from fastapi_app.services.outsource_service import auto_generate_for_order
                    await auto_generate_for_order(db, order)

                    staging.status = staging_machine.transition(staging.status, StagingAction.APPROVE)
                    confirmed += 1

            except (ValueError, TypeError, OSError) as e:
                errors.append(f'订单{staging.customer}-{staging.product_name}确认失败: {e!s}')
                staging.status = staging_machine.transition(staging.status, StagingAction.REJECT)

        await db.execute(
            delete(StagingOrder).where(
                StagingOrder.session_id == session_id,
                StagingOrder.status == StagingStatus.REJECTED,
            )
        )
        await db.flush()

    except (SQLAlchemyError, RuntimeError, OSError, ValueError) as e:
        logger.error(f'确认暂存订单时发生错误: {e!s}', exc_info=True)
        raise

    return confirmed, errors

async def import_staging_orders_from_excel(
    db: AsyncSession, file_content: bytes, session_id: str
) -> tuple[int, str, list[str]]:
    return await _generic_import_staging_from_excel(
        db, file_content, session_id,
        staging_model=StagingOrder,
        clear_func=clear_staging_orders_by_session,
        sheet_keyword='订单管理',
        entity_label='订单',
        build_entity=_build_order_entity,
        column_names={
            'customer': '客户名称',
            'product_name': '产品名称',
            'quantity': '订单数量',
            'deduct_stock': '抵扣备货',
            'note': '备注',
        },
        required_fields=['customer', 'product_name', 'quantity'],
    )


# ==================== 暂存备货服务 ====================