"""外发加工序列化与状态派生辅助

从 outsource_service.py 按职责拆出,行为与原实现完全一致。
"""
import logging
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from fastapi_app.shared_models import OrderOutsourceProcess, OutsourceProcessType, Product

logger = logging.getLogger(__name__)


def _fmt_dt(dt: datetime | None) -> str | None:
    """格式化 datetime 为 'YYYY-MM-DD HH:MM'；naive UTC 按 UTC 直接格式化。"""
    if dt is None:
        return None
    return dt.strftime('%Y-%m-%d %H:%M')

def _serialize_process_type(pt: OutsourceProcessType, product: Product | None = None) -> dict:
    product = product or pt.product
    return {
        'id': pt.id,
        'product_id': pt.product_id,
        'product_name': product.name if product else None,
        'product_barcode': product.barcode if product else None,
        'factory': product.factory if product else None,
        'process_type': pt.process_type,
        'sort_order': pt.sort_order or 0,
        'is_active': bool(pt.is_active),
        'remark': pt.remark,
        'created_by': pt.created_by,
        'create_time': _fmt_dt(pt.create_time),
        'update_time': _fmt_dt(pt.update_time),
    }

def _serialize_order_process(p: OrderOutsourceProcess) -> dict:
    return {
        'id': p.id,
        'order_id': p.order_id,
        'order_item_id': p.order_item_id,
        'product_id': p.product_id,
        'product_name': p.product_name,
        'process_type': p.process_type,
        'sort_order': p.sort_order or 0,
        'status': p.status,
        'shipped_quantity': p.shipped_quantity,
        'received_quantity': p.received_quantity,
        'planned_start_time': _fmt_dt(p.planned_start_time),
        'planned_end_time': _fmt_dt(p.planned_end_time),
        'actual_start_time': _fmt_dt(p.actual_start_time),
        'actual_end_time': _fmt_dt(p.actual_end_time),
        'remark': p.remark,
        'created_by': p.created_by,
        'create_time': _fmt_dt(p.create_time),
        'update_time': _fmt_dt(p.update_time),
    }

def _is_fully_received(p: OrderOutsourceProcess) -> bool:
    """是否已收齐：有收货记录且收货累计 >= 发货累计。"""
    return (p.received_quantity or 0) > 0 and (p.received_quantity or 0) >= (p.shipped_quantity or 0)

def _derive_status(p: OrderOutsourceProcess) -> str:
    """按累计数量派生状态：pending=未发；shipped=已发未收齐；received=已收齐。"""
    if (p.shipped_quantity or 0) == 0:
        return 'pending'
    if _is_fully_received(p):
        return 'received'
    return 'shipped'

def _summarize_process_progress(processes: list[OrderOutsourceProcess]) -> dict:
    """计算工序进度统计（总数/已收齐数/已开始数/进度/当前工序/状态标签）。"""
    total = len(processes)
    completed = sum(1 for p in processes if _is_fully_received(p))
    started = sum(1 for p in processes if (p.shipped_quantity or 0) > 0)
    progress = round(completed * 100 / total) if total else 0

    current_process = None
    for p in processes:
        if not _is_fully_received(p):
            current_process = p.process_type
            break

    if total == 0:
        status_label = '未配置工序'
    elif completed == total:
        status_label = '外发完成'
    elif started > 0:
        status_label = f'进行中（{current_process}）'
    else:
        status_label = '待发货'

    return {
        'total_processes': total,
        'completed_processes': completed,
        'started_processes': started,
        'progress': progress,
        'current_process': current_process,
        'status_label': status_label,
    }

# 订单外发工序整体状态（由工序进度派生的视图状态，区别于单工序的
# OUTSOURCE_PROCESS_STATUSES）：业务代码引用常量，禁止新增字面量。
class OutsourceOrderViewStatus:
    PENDING = 'pending'
    IN_PROGRESS = 'in_progress'
    COMPLETED = 'completed'


def _matches_process_status(row: dict, status: str) -> bool:
    """按订单外发工序整体状态过滤。

    - pending 待发货：已配置工序且全部未发货
    - in_progress 进行中：有工序已发货但未全部收货
    - completed 已完成：全部工序已收货
    未配置工序（total=0）不属于任何状态。
    """
    total = row.get('total_processes', 0)
    if total == 0:
        return False
    completed = row.get('completed_processes', 0)
    started = row.get('started_processes', 0)
    if status == OutsourceOrderViewStatus.COMPLETED:
        return completed == total
    if status == OutsourceOrderViewStatus.IN_PROGRESS:
        return started > 0 and completed < total
    if status == OutsourceOrderViewStatus.PENDING:
        return started == 0
    return True

async def _attach_progress_to_orders(db: AsyncSession, items: list[dict]) -> None:
    """为订单列表条目附加外发工序进度统计（就地修改，仅订单记录；备货记录无工序）。"""
    order_ids = [row['id'] for row in items if row.get('record_type') == 'order']
    if not order_ids:
        return

    result = await db.execute(
        select(OrderOutsourceProcess)
        .where(OrderOutsourceProcess.order_id.in_(order_ids))
        .order_by(
            OrderOutsourceProcess.order_id,
            OrderOutsourceProcess.order_item_id,
            OrderOutsourceProcess.sort_order,
            OrderOutsourceProcess.id,
        )
    )
    processes_by_order: dict[int, list[OrderOutsourceProcess]] = {}
    # 记录每个订单中有工序的 SKU (order_item_id 集合)
    process_item_ids_by_order: dict[int, set[int]] = {}
    for p in result.scalars().all():
        processes_by_order.setdefault(p.order_id, []).append(p)
        if p.order_item_id is not None:
            process_item_ids_by_order.setdefault(p.order_id, set()).add(p.order_item_id)

    for row in items:
        # 为每个 SKU 标记是否有外发工序
        if row.get('items'):
            item_ids_with_processes = process_item_ids_by_order.get(row['id'], set())
            for sku in row['items']:
                sku['has_processes'] = sku['id'] in item_ids_with_processes

        if row.get('record_type') != 'order':
            row['total_processes'] = 0
            row['completed_processes'] = 0
            row['started_processes'] = 0
            row['progress'] = 0
            row['current_process'] = None
            row['status_label'] = '未配置工序'
            continue
        row.update(_summarize_process_progress(processes_by_order.get(row['id'], [])))


# ==================== SKU 工序预设 ====================