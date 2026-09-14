"""外发加工订单/看板查询

从 outsource_service.py 按职责拆出,行为与原实现完全一致。
"""
import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from fastapi_app.services.outsource._common import (
    _attach_progress_to_orders,
    _fmt_dt,
    _matches_process_status,
    _serialize_order_process,
)
from fastapi_app.shared_models import (
    Order,
    OrderItem,
    OrderOutsourceProcess,
    OrderOutsourceProcessFlow,
)

logger = logging.getLogger(__name__)


async def _process_target_quantity(db: AsyncSession, p: OrderOutsourceProcess) -> int:
    """工序目标数量：优先 SKU(order_item) 数量，无明细用订单数量；解析失败返回 0（不设上限）。"""
    try:
        if p.order_item_id is not None:
            item = await db.get(OrderItem, p.order_item_id)
            if item is not None:
                qty = getattr(item, 'quantity', None)
                if isinstance(qty, int) and qty > 0:
                    return int(qty)
        order = await db.get(Order, p.order_id)
        if order is not None:
            qty = getattr(order, 'quantity', None)
            if isinstance(qty, int) and qty > 0:
                return int(qty)
    except Exception:  # defensive: 目标解析失败不阻断发货（按无上限处理）
        logger.warning('解析外发工序目标数量失败: process_id=%s', getattr(p, 'id', None), exc_info=True)
    return 0


# ==================== 湖北外发订单列表 ====================

# 状态筛选需跨页统计，故按页遍历取回全量合并列表（单页上限 500 由 beile 查询约定）
_SCAN_PAGE_SIZE = 500


def _detach_page_items(items: list[dict]) -> list[dict]:
    """复制一页记录（含 SKU 明细），避免就地改写被缓存的数据。

    `get_beile_orders_with_stockins` 带 @cache_result，命中的是同一个 list 对象；
    直接就地附加进度会把 progress/status_label 等字段写回缓存，污染
    beile-order 页面的响应。此处先复制再改写，保证缓存内容不变。
    """
    detached: list[dict] = []
    for row in items:
        copied = dict(row)
        if copied.get('items'):
            copied['items'] = [dict(sku) for sku in copied['items']]
        detached.append(copied)
    return detached


async def _scan_beile_items_with_progress(db: AsyncSession, customer: str | None) -> list[dict]:
    """按页遍历取回全部订单+备货记录，并逐页附加外发工序进度。

    状态筛选是跨页统计，不能只取首页：此前固定 page=1&per_page=500，
    第 500 条之后的记录被静默丢弃，这些订单在任何状态筛选下都查不到。
    进度按页附加（每页 ≤500 个 id），避免把全量订单 id 堆进一条 IN 查询。

    已知局限：订单列表本身由 order_crud.get_beile_orders_with_stockins 提供，
    其 SQL 不接收「工序状态」条件，因此状态筛选仍需跨页扫描后再过滤；
    进度统计已下推到数据库聚合（见 _attach_progress_to_orders）。
    """
    from fastapi_app.services.order_crud import get_beile_orders_with_stockins
    items: list[dict] = []
    page = 1
    while True:
        page_data = await get_beile_orders_with_stockins(
            db, page=page, per_page=_SCAN_PAGE_SIZE, customer=customer, factory='湖北',
        )
        page_items = _detach_page_items(page_data['items'])
        await _attach_progress_to_orders(db, page_items)
        items.extend(page_items)
        # 短页说明已到末页；total 判定兜底防止短页提前终止
        if len(page_items) < _SCAN_PAGE_SIZE or page * _SCAN_PAGE_SIZE >= page_data['total']:
            return items
        page += 1


async def list_outsource_orders(
    db: AsyncSession, *, page: int = 1, per_page: int = 50,
    customer: str | None = None, process_status: str | None = None,
) -> dict:
    """湖北工厂订单+备货合并列表（强制 factory=湖北）。

    复用 order_crud.get_beile_orders_with_stockins，与 beile-order 页面
    保持完全一致的筛选逻辑与返回结构；并为每个订单附加外发工序进度统计
    （total/completed/progress/current_process/status_label），供订单列表
    直接展示进度条，无需再单独打开看板。

    process_status：按订单外发工序整体状态过滤（pending/in_progress/completed），
    需跨页统计，故先取全量合并列表附加进度后过滤再分页；未配置工序的订单
    不属于任何状态（未配置是独立状态，仅在无状态筛选时展示）。
    进度统计本身由数据库聚合完成（数据库聚合 JOIN + GROUP BY，见 _common）。
    """
    from fastapi_app.services.order_crud import get_beile_orders_with_stockins
    if process_status:
        all_items = await _scan_beile_items_with_progress(db, customer)
        filtered = [
            row for row in all_items
            if _matches_process_status(row, process_status)
        ]
        total = len(filtered)
        start = (page - 1) * per_page
        return {
            'items': filtered[start:start + per_page],
            'total': total,
            'page': page,
            'per_page': per_page,
        }

    data = await get_beile_orders_with_stockins(
        db, page=page, per_page=per_page, customer=customer, factory='湖北',
    )
    items = _detach_page_items(data['items'])
    await _attach_progress_to_orders(db, items)
    return {**data, 'items': items}

async def list_order_processes(db: AsyncSession, order_id: int) -> list[dict]:
    """查询订单外发工序（按 SKU + 工序顺序排序）。"""
    result = await db.execute(
        select(OrderOutsourceProcess)
        .where(OrderOutsourceProcess.order_id == order_id)
        .order_by(
            OrderOutsourceProcess.order_item_id,
            OrderOutsourceProcess.sort_order,
            OrderOutsourceProcess.id,
        )
    )
    processes = result.scalars().all()
    return [_serialize_order_process(p) for p in processes]

async def list_order_flows(db: AsyncSession, order_id: int) -> list[dict]:
    """查询订单全部外发工序流水（含工序名，按时间倒序），供台账展示。"""
    result = await db.execute(
        select(OrderOutsourceProcessFlow, OrderOutsourceProcess.process_type)
        .join(OrderOutsourceProcess, OrderOutsourceProcess.id == OrderOutsourceProcessFlow.process_id)
        .where(OrderOutsourceProcess.order_id == order_id)
        .order_by(OrderOutsourceProcessFlow.create_time.desc(), OrderOutsourceProcessFlow.id.desc())
    )
    return [
        {
            'id': flow.id,
            'process_id': flow.process_id,
            'process_type': process_type,
            'action': flow.action,
            'quantity': flow.quantity,
            'operator': flow.operator,
            'create_time': _fmt_dt(flow.create_time),
        }
        for flow, process_type in result.all()
    ]
