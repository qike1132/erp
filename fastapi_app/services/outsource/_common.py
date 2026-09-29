"""外发加工序列化与状态派生辅助

从 outsource_service.py 按职责拆出,行为与原实现完全一致。
"""
from datetime import UTC, datetime, timedelta, timezone

from sqlalchemy import and_, case, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from fastapi_app.shared_models import OrderOutsourceProcess, OutsourceProcessType, Product

# 展示时区：用户全部在国内（工厂内网，固定 UTC+8），与 beile._fmt_beile_time 同口径。
_BEILE_TZ = timezone(timedelta(hours=8))


def _fmt_dt(dt: datetime | None) -> str | None:
    """timestamptz 列（asyncpg 返回 aware UTC）或 naive UTC → 北京时间 'YYYY-MM-DD HH:MM'。

    外发序列化共用该输出（页面行 / 详情 / 台账），前端不做二次时区换算。
    """
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(_BEILE_TZ).strftime('%Y-%m-%d %H:%M')

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

def _fully_received_condition(proc):
    """SQL 端「已收齐」条件：有收货且收货累计 >= 发货累计（与 _is_fully_received 一致）。"""
    shipped = func.coalesce(proc.shipped_quantity, 0)
    received = func.coalesce(proc.received_quantity, 0)
    return and_(received > 0, received >= shipped)


def _format_process_progress(*, total: int, completed: int, started: int,
                            current_process: str | None) -> dict:
    """把工序统计数值格式化为列表所需的进度字段（口径与改造前的 Python 实现一致）。

    统计本身由数据库聚合得到（见 _load_process_stats），此处只做展示字段拼装，
    保证 total=0 时为「未配置工序」、全部收齐为「外发完成」等既有语义不变。
    """
    progress = round(completed * 100 / total) if total else 0
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


async def _load_process_stats(db: AsyncSession, order_ids: list[int]) -> dict[int, dict]:
    """单条聚合 SQL 取回每个订单的工序进度（一个订单一行）。

    改造前是把这些订单的全部工序行拉回应用层再逐条判断；现在由数据库完成
    GROUP BY 聚合与「当前工序」取值（关联子查询按 SKU/工序顺序取第一道未收齐），
    传输与遍历的数据量从「工序行数」降到「订单数」。
    """
    if not order_ids:
        return {}
    cur = aliased(OrderOutsourceProcess, name='cur_proc')
    # 当前工序：与 Python 版一致，取排序最靠前的未收齐工序
    current_process_sq = (
        select(cur.process_type)
        .where(
            cur.order_id == OrderOutsourceProcess.order_id,
            ~_fully_received_condition(cur),
        )
        .order_by(cur.order_item_id, cur.sort_order, cur.id)
        .limit(1)
        .correlate(OrderOutsourceProcess)
        .scalar_subquery()
    )
    stmt = (
        select(
            OrderOutsourceProcess.order_id,
            func.count().label('total_processes'),
            func.sum(case((_fully_received_condition(OrderOutsourceProcess), 1), else_=0))
            .label('completed_processes'),
            func.sum(case((func.coalesce(OrderOutsourceProcess.shipped_quantity, 0) > 0, 1), else_=0))
            .label('started_processes'),
            current_process_sq.label('current_process'),
        )
        .where(OrderOutsourceProcess.order_id.in_(order_ids))
        .group_by(OrderOutsourceProcess.order_id)
    )
    rows = (await db.execute(stmt)).all()
    return {
        row.order_id: _format_process_progress(
            total=row.total_processes or 0,
            completed=int(row.completed_processes or 0),
            started=int(row.started_processes or 0),
            current_process=row.current_process,
        )
        for row in rows
    }


async def _load_process_item_ids(db: AsyncSession, order_ids: list[int]) -> dict[int, set[int]]:
    """取回各订单下「存在外发工序」的 SKU 明细 ID（用于列表标记 SKU 是否有工序）。"""
    if not order_ids:
        return {}
    stmt = (
        select(OrderOutsourceProcess.order_id, OrderOutsourceProcess.order_item_id)
        .where(
            OrderOutsourceProcess.order_id.in_(order_ids),
            OrderOutsourceProcess.order_item_id.isnot(None),
        )
        .distinct()
    )
    result: dict[int, set[int]] = {}
    for order_id, item_id in (await db.execute(stmt)).all():
        result.setdefault(order_id, set()).add(item_id)
    return result

# 订单外发工序整体状态（由工序进度派生的视图状态，区别于单工序的
# pending/shipped/received）：业务代码引用常量，禁止新增字面量。
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
    """为订单列表条目附加外发工序进度统计（就地修改，仅订单记录；备货记录无工序）。

    进度由数据库聚合（两次窄查询：进度统计 + 有工序的 SKU 集合），
    应用层只做字段拼装，不再逐条遍历全部工序行。
    """
    order_ids = [row['id'] for row in items if row.get('record_type') == 'order']
    if not order_ids:
        return

    stats_by_order = await _load_process_stats(db, order_ids)
    process_item_ids_by_order = await _load_process_item_ids(db, order_ids)

    for row in items:
        # 为每个 SKU 标记是否有外发工序
        if row.get('items'):
            item_ids_with_processes = process_item_ids_by_order.get(row['id'], set())
            for sku in row['items']:
                sku['has_processes'] = sku['id'] in item_ids_with_processes

        if row.get('record_type') != 'order':
            row.update(_format_process_progress(total=0, completed=0, started=0, current_process=None))
            continue
        row.update(
            stats_by_order.get(row['id'])
            or _format_process_progress(total=0, completed=0, started=0, current_process=None)
        )
