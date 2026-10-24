"""采购订单完成态查询辅助

从 purchase_order_query_helpers.py 按主题拆出,行为与原实现完全一致。
"""
import logging
from collections import defaultdict
from datetime import UTC, datetime, timedelta

from sqlalchemy import exists, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from fastapi_app.core.business_time import business_day_bounds_utc_naive, fmt_business, fmt_business_naive_utc
from fastapi_app.core.sanitizer import escape_like
from fastapi_app.services.purchase._list import _serialize_po_item
from fastapi_app.services.purchase_utils import (
    magnified_purchase_qty,
    normalize_spare_rate,
    resolve_item_loss_rate,
)
from fastapi_app.shared_models import (
    MaterialRegistration,
    MaterialRegistrationItem,
    PurchaseOrder,
    PurchaseOrderItem,
)

logger = logging.getLogger(__name__)

_COMPLETED_SORT_MAP = {
    'completed_at': PurchaseOrder.completed_at,
    'order_no': PurchaseOrder.order_no,
    'total_amount': PurchaseOrder.total_amount,
}

_QUICK_FILTER_DAYS = {
    'today': 0,
    'week': 7,
    'month': 30,
}


def _apply_completed_filters(
    query, count_query, *,
    supplier_id, keyword, date_from, date_to,
    order_no, customer_name, product_name, supplier_name,
    barcode, material_name, start_date, end_date,
):
    if supplier_id:
        query = query.where(PurchaseOrder.supplier_id == supplier_id)
        count_query = count_query.where(PurchaseOrder.supplier_id == supplier_id)
    if keyword:
        like_pattern = f'%{escape_like(keyword)}%'
        kw_filter = or_(
            PurchaseOrder.order_no.ilike(like_pattern),
            PurchaseOrder.customer_name.ilike(like_pattern),
            PurchaseOrder.supplier_name.ilike(like_pattern),
        )
        query = query.where(kw_filter)
        count_query = count_query.where(kw_filter)
    if date_from:
        # AUD-02（2026-10-24 审计）：completed_at 是 naive-UTC 列，日期边界按
        # 业务时区（北京）日界换算成 UTC——原先直比 'YYYY-MM-DD'（UTC 日界），
        # 北京 00:00–07:59 完成的记录落到前一天。
        lower, _ = business_day_bounds_utc_naive(
            datetime.strptime(date_from, '%Y-%m-%d').date())
        query = query.where(PurchaseOrder.completed_at >= lower)
        count_query = count_query.where(PurchaseOrder.completed_at >= lower)
    if date_to:
        # 用独立变量：原先赋给 `end_date`（同名参数）→ 末尾 `f'{end_date} 23:59:59'`
        # 又拼一次得到 '... 23:59:59 23:59:59' 作为绑定参数与 timestamp 比较
        # → Postgres `invalid input syntax for type timestamp` → 整个列表 500。
        # 端点 order_routes 把 date_to 作为兼容字段对外暴露，老客户端/直连 API 即命中。
        # AUD-02：闭区间 '23:59:59' 带 1 秒微秒洞且时区语义错位，改 < 次日 00:00（UTC）。
        _, upper = business_day_bounds_utc_naive(
            datetime.strptime(date_to, '%Y-%m-%d').date())
        query = query.where(PurchaseOrder.completed_at < upper)
        count_query = count_query.where(PurchaseOrder.completed_at < upper)
    # 分字段过滤（与前端 useCompletedOrders filters 一一对应）
    for col, val in (
        (PurchaseOrder.order_no, order_no),
        (PurchaseOrder.customer_name, customer_name),
        (PurchaseOrder.product_name, product_name),
        (PurchaseOrder.supplier_name, supplier_name),
    ):
        if val:
            pattern = f'%{escape_like(val)}%'
            query = query.where(col.ilike(pattern))
            count_query = count_query.where(col.ilike(pattern))
    if start_date:
        lower, _ = business_day_bounds_utc_naive(
            datetime.strptime(start_date, '%Y-%m-%d').date())  # AUD-02：北京日界
        query = query.where(PurchaseOrder.completed_at >= lower)
        count_query = count_query.where(PurchaseOrder.completed_at >= lower)
    if end_date:
        _, upper = business_day_bounds_utc_naive(
            datetime.strptime(end_date, '%Y-%m-%d').date())  # AUD-02：北京日界
        query = query.where(PurchaseOrder.completed_at < upper)
        count_query = count_query.where(PurchaseOrder.completed_at < upper)
    # barcode / material_name 需要 EXISTS 子查询 purchase_order_item
    if barcode:
        barcode_pattern = f'%{escape_like(barcode)}%'
        barcode_filter = exists().where(
            PurchaseOrderItem.order_id == PurchaseOrder.id,
            PurchaseOrderItem.barcode.ilike(barcode_pattern),
        )
        query = query.where(barcode_filter)
        count_query = count_query.where(barcode_filter)
    if material_name:
        material_pattern = f'%{escape_like(material_name)}%'
        material_filter = exists().where(
            PurchaseOrderItem.order_id == PurchaseOrder.id,
            PurchaseOrderItem.material_name.ilike(material_pattern),
        )
        query = query.where(material_filter)
        count_query = count_query.where(material_filter)
    return query, count_query

def _apply_completed_quick_filter(query, count_query, quick_filter):
    days = _QUICK_FILTER_DAYS.get(quick_filter)
    if days is None:
        return query, count_query
    threshold = datetime.now(UTC).replace(tzinfo=None).date() - timedelta(days=days)
    query = query.where(PurchaseOrder.completed_at >= threshold)
    count_query = count_query.where(PurchaseOrder.completed_at >= threshold)
    return query, count_query

async def _fetch_completed_items_and_arrived(db: AsyncSession, order_ids: list[int]):
    if not order_ids:
        return {}, {}
    items_result = await db.execute(
        select(PurchaseOrderItem).where(PurchaseOrderItem.order_id.in_(order_ids))
    )
    all_items = items_result.scalars().all()
    items_by_order: dict[int, list] = defaultdict(list)
    for item in all_items:
        items_by_order[item.order_id].append(item)

    regs_result = await db.execute(
        select(
            MaterialRegistrationItem.material_name,
            MaterialRegistrationItem.material_code,
            func.sum(MaterialRegistrationItem.received_quantity).label('total'),
        ).join(
            MaterialRegistration, MaterialRegistrationItem.registration_id == MaterialRegistration.id
        ).where(
            MaterialRegistration.purchase_order_id.in_(order_ids),
            MaterialRegistration.status.in_(('pending', 'partial', 'completed')),
        ).group_by(
            MaterialRegistrationItem.material_name,
            MaterialRegistrationItem.material_code,
        )
    )
    arrived_map = {
        (r.material_name, r.material_code or ''): int(r.total or 0)
        for r in regs_result
    }
    return items_by_order, arrived_map

def _serialize_completed_item(item, arrived_map: dict, order=None) -> dict:
    required = int(item.quantity or 0)
    # 与 arrived_map 构建侧同构归一（material_code 可空 → ''），否则 NULL 明细永远查不中
    key = (item.material_name, item.material_code or '')
    arrived = arrived_map.get(key, 0)
    data = _serialize_po_item(item)
    # P1（2026-10-24）：数量与金额必须同源。金额（item.total_price）按「加放损耗后的
    # 计价数量」计算，而列表原先下发落库原值 → spare_rate>0 时页面必现
    # 「数量 × 单价 ≠ 金额」，同一行导出却是相等的（导出侧已改用 magnified_purchase_qty）。
    # 这里改用同一函数，并下发 loss_rate/spare_rate 供前端自行核对。
    if order is not None:
        loss_rate = resolve_item_loss_rate(item.loss_rate, order.spare_rate)
        data['quantity'] = float(magnified_purchase_qty(item.quantity or 0, loss_rate))
        data['loss_rate'] = float(loss_rate or 0)
        data['spare_rate'] = float(normalize_spare_rate(order.spare_rate) or 0)
    return {
        **data,
        # 到货判定仍用落库原值：material_registration.ordered_quantity 也是原值口径
        'is_arrived': required > 0 and arrived >= required,
        'deficit': max(0, required - arrived) if required > 0 else 0,
    }

def _serialize_completed_order(order, items, arrived_map: dict, source_order_no: str, sku_items: list[dict] | None = None) -> dict:
    return {
        'id': order.id,
        'order_no': order.order_no,
        'source_order_no': source_order_no,
        'supplier_name': order.supplier_name,
        'supplier_id': order.supplier_id,
        'customer_name': order.customer_name,
        'customer': order.customer_name,
        'status': order.status,
        'total_amount': float(order.total_amount or 0),
        'product_name': order.product_name or '',
        'quantity': float(order.product_quantity or 0) if order.product_quantity else 0,
        'order_date': order.order_date.strftime('%Y-%m-%d') if order.order_date else '',
        'note': order.remark or '',
        # AUD-02：create_time 是 timestamptz（aware）、completed_at 是 naive-UTC
        # 列——两者都按北京时间渲染（原先 UTC 墙钟直出恒慢 8 小时）。
        'create_time': fmt_business(order.create_time),
        'completed_at': fmt_business_naive_utc(order.completed_at),
        'items': [_serialize_completed_item(item, arrived_map, order) for item in items],
        'sku_items': sku_items or [],
    }
