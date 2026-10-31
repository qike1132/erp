"""
采购中心 - BOM 复制服务

从 purchase_center_service.py 拆分，包含 BOM 复制搜索、预览和执行功能。
"""
import logging
from decimal import Decimal
from typing import Any, TypedDict

from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from fastapi_app.core.business_time import fmt_business
from fastapi_app.core.exceptions import ConflictError
from fastapi_app.core.sanitizer import escape_like
from fastapi_app.services.bom_service import (  # noqa: F401
    copy_bom as copy_bom_to_product,
)
from fastapi_app.services.bom_service import (
    has_bom,
)
from fastapi_app.services.purchase_order_purge import purge_purchase_order_children
from fastapi_app.shared_models import (
    MaterialRegistration,
    Product,
    PurchaseOrder,
    PurchaseOrderItem,
)

logger = logging.getLogger(__name__)

class _BomData(TypedDict):
    """BOM 复制时的中间结构：填充/面料/辅料三类明细。"""

    filling: dict[str, Any] | None
    fabric: list[dict[str, Any]]
    accessory: list[dict[str, Any]]



async def batch_delete_purchase_orders(db: AsyncSession, order_ids: list, username: str = 'unknown') -> dict:
    if not order_ids:
        raise ValueError('请选择要删除的订单')

    result = await db.execute(select(PurchaseOrder).where(PurchaseOrder.id.in_(order_ids)))
    orders_to_delete = result.scalars().all()
    if not orders_to_delete:
        raise ValueError('未找到要删除的订单')

    # 来料登记 FK 为 NO ACTION：有登记的单会让整批 flush 抛 IntegrityError（500）。
    # 批删语义取「整批拒绝 + 列出具体单号」，避免用户以为部分成功。
    blocked_rows = (await db.execute(
        select(MaterialRegistration.purchase_order_id, MaterialRegistration.purchase_order_no)
        .where(MaterialRegistration.purchase_order_id.in_([o.id for o in orders_to_delete]))
    )).all()
    if blocked_rows:
        blocked = sorted({str(row.purchase_order_no or row.purchase_order_id) for row in blocked_rows})
        raise ConflictError(f'以下采购单存在来料登记，无法删除: {", ".join(blocked)}')

    deleted_info = []
    deleted_order_nos: list[str] = []
    try:
        count_rows = (await db.execute(
            select(PurchaseOrderItem.order_id, func.count(PurchaseOrderItem.id))
            .where(PurchaseOrderItem.order_id.in_([o.id for o in orders_to_delete]))
            .group_by(PurchaseOrderItem.order_id)
        )).all()
        item_counts: dict[int, int] = {
            int(order_id): int(count) for order_id, count in count_rows
        }
        # 子表必须先显式清理：items 的 FK 是 NO ACTION，skus 虽是 CASCADE 但
        # 关系为 lazy='raise'，靠 ORM 级联会在 flush 抛 InvalidRequestError（A-M19）。
        await purge_purchase_order_children(db, [o.id for o in orders_to_delete])
        for order in orders_to_delete:
            item_count = item_counts.get(order.id, 0)
            deleted_info.append({
                'order_no': order.order_no,
                'supplier_name': order.supplier_name or '',
                'customer_name': order.customer_name or '',
                'item_count': item_count,
            })
            deleted_order_nos.append(order.order_no)
            await db.delete(order)

        await db.flush()
    except IntegrityError as e:
        raise ConflictError('部分采购单被来料登记等记录引用，无法删除，请刷新后重试') from e

    logger.warning(
        f'批量删除采购订单 | 操作人: {username} | '
        f'删除数量: {len(deleted_info)} | '
        f"订单编号: {', '.join(deleted_order_nos)}"
    )

    return {
        'message': f'成功删除 {len(deleted_info)} 个订单',
        'deleted_count': len(deleted_info),
    }


async def search_products_for_bom_copy(db: AsyncSession, keyword: str) -> list:
    """搜索产品用于复制BOM

    根据关键词搜索产品名称或条码，返回产品基本信息和BOM状态。
    """
    if not keyword:
        return []

    result = await db.execute(
        select(Product)
        .options(
            selectinload(Product.material),
            selectinload(Product.material_rows),
            selectinload(Product.fabrics),
            selectinload(Product.accessories),
        )
        .where(
            or_(
                # 第八轮审计：补 escape_like —— 此前 keyword 中的 % / _ 会被当通配符
                # （`%` 命中全表）。同仓 _list.py / purchase_customer_service.py 均已转义。
                Product.name.ilike(f'%{escape_like(keyword)}%'),
                Product.barcode.ilike(f'%{escape_like(keyword)}%'),
            )
        )
        .limit(20)
    )
    products = result.scalars().all()

    output = []
    for p in products:
        has_bom_result = has_bom(p)
        material_count = (
            len(p.fabrics) + len(p.accessories)
            + (1 if p.material and getattr(p.material, 'cotton_usage', Decimal('0')) > 0 else 0)
        )
        output.append({
            'id': p.id,
            'name': p.name,
            'barcode': p.barcode,
            'price': float(p.price) if p.price else 0,
            'has_bom': has_bom_result,
            'material_count': material_count,
        })

    return output


async def get_bom_preview(db: AsyncSession, source_product_id: int) -> dict:
    """获取源产品BOM预览用于复制确认

    返回源产品的基本信息和完整BOM数据（filling/fabric/accessory/packaging）。
    """
    result = await db.execute(
        select(Product)
        .options(
            selectinload(Product.material),
            selectinload(Product.material_rows),
            selectinload(Product.fabrics),
            selectinload(Product.accessories),
        )
        .where(Product.id == source_product_id)
    )
    source_product = result.scalar_one_or_none()

    if not source_product:
        raise ValueError(f'产品ID {source_product_id} 不存在')

    if not has_bom(source_product):
        raise ValueError('该产品没有配置BOM表，无法复制')

    bom_data: _BomData = {
        'filling': None,
        'fabric': [],
        'accessory': [],
    }

    if source_product.material and getattr(source_product.material, 'cotton_usage', Decimal('0')) > 0:
        bom_data['filling'] = source_product.material.to_dict()

    for fabric in source_product.fabrics:
        bom_data['fabric'].append(fabric.to_dict())

    for accessory in source_product.accessories:
        bom_data['accessory'].append(accessory.to_dict())

    material_count = (
        (1 if bom_data['filling'] else 0)
        + len(bom_data['fabric'])
        + len(bom_data['accessory'])
    )

    create_time_str = fmt_business(
        source_product.create_time, '%Y-%m-%d %H:%M:%S') or None

    return {
        'product': {
            'id': source_product.id,
            'name': source_product.name,
            'barcode': source_product.barcode,
            'create_time': create_time_str,
        },
        'bom': bom_data,
        'material_count': material_count,
    }
