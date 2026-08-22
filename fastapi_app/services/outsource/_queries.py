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
    _summarize_process_progress,
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
    """
    from fastapi_app.services.order_crud import get_beile_orders_with_stockins
    if process_status:
        all_data = await get_beile_orders_with_stockins(
            db, page=1, per_page=500, customer=customer, factory='湖北',
        )
        await _attach_progress_to_orders(db, all_data['items'])
        filtered = [
            row for row in all_data['items']
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
    await _attach_progress_to_orders(db, data['items'])
    return data

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

async def get_kanban(
    db: AsyncSession, *, page: int = 1, per_page: int = 20,
    customer: str | None = None,
) -> dict:
    """订单进度看板：湖北工厂订单 + 各 SKU 外发工序状态。

    每个订单条目包含：
    - 下单时间/客户/产品
    - processes: 按 SKU 排序的工序（计划/实际完成时间、状态）
    - progress: 完成工序占比（0-100）
    - current_process: 当前进行中（或下一个待开始）的工序
    """
    orders_data = await list_outsource_orders(
        db, page=page, per_page=per_page, customer=customer,
    )
    items: list[dict] = []
    order_ids = [row['id'] for row in orders_data['items']]

    processes_by_order: dict[int, list[OrderOutsourceProcess]] = {}
    if order_ids:
        proc_result = await db.execute(
            select(OrderOutsourceProcess)
            .where(OrderOutsourceProcess.order_id.in_(order_ids))
            .order_by(
                OrderOutsourceProcess.order_id,
                OrderOutsourceProcess.order_item_id,
                OrderOutsourceProcess.sort_order,
                OrderOutsourceProcess.id,
            )
        )
        for p in proc_result.scalars().all():
            processes_by_order.setdefault(p.order_id, []).append(p)

    for row in orders_data['items']:
        processes = processes_by_order.get(row['id'], [])
        summary = _summarize_process_progress(processes)
        total = summary['total_processes']
        completed = summary['completed_processes']
        current_process = summary['current_process']
        status_label = summary['status_label']

        items.append({
            'id': row['id'],
            'order_no': row['order_no'],
            'customer': row['customer'],
            'order_date': row.get('order_date', ''),
            'record_type': row.get('record_type', 'order'),
            'products': [
                {'product_id': sku['product_id'], 'product_name': sku['product_name'],
                 'quantity': sku['quantity']}
                for sku in (row.get('items') or [])
            ],
            'processes': [_serialize_order_process(p) for p in processes],
            'total_processes': total,
            'completed_processes': completed,
            'progress': summary['progress'],
            'current_process': current_process,
            'status_label': status_label,
        })

    return {
        'items': items,
        'total': orders_data['total'],
        'page': page,
        'per_page': per_page,
    }