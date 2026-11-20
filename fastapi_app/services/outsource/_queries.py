"""外发加工订单/看板查询

从 outsource_service.py 按职责拆出,行为与原实现完全一致。
"""
import logging

from sqlalchemy import and_, case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from fastapi_app.services.outsource._common import (
    OutsourceOrderViewStatus,
    _attach_progress_to_orders,
    _fmt_dt,
    _serialize_order_process,
)
from fastapi_app.shared_models import (
    Order,
    OrderItem,
    OrderOutsourceProcess,
    OrderOutsourceProcessFlow,
    OutsourceProcessType,
    Product,
)

logger = logging.getLogger(__name__)


async def _process_target_quantity(db: AsyncSession, p: OrderOutsourceProcess) -> int:
    """工序目标数量：优先取 SKU(order_item) 数量；旧订单回退整单数量。

    P1-6：旧订单（无 OrderItem）的工序 order_item_id 为空，旧实现直接
    fail-closed 抛错——但待发货面板 `list_shippable_processes` 用
    ``coalesce(OrderItem.quantity, Order.quantity)`` 展示目标量并计入剩余，
    于是旧订单工序「面板可见、发货必拒」。此处按同一口径回退 order.quantity。

    仍保留 fail-closed 边界（防超发）：
    - 工序挂了 order_item_id 但明细缺失/数量非法 → 抛错；
    - order_item_id 为空、而订单其实已有 SKU 明细（脏数据）→ 抛错，不能按整单量放行。
    """
    try:
        if p.order_item_id is not None:
            item = await db.get(OrderItem, p.order_item_id)
            if item is not None:
                qty = getattr(item, 'quantity', None)
                if isinstance(qty, int) and qty > 0:
                    return int(qty)
        else:
            has_sku = (await db.execute(
                select(OrderItem.id).where(OrderItem.order_id == p.order_id).limit(1)
            )).first()
            if has_sku is None:
                order_qty = (await db.execute(
                    select(Order.quantity).where(Order.id == p.order_id)
                )).scalar_one_or_none()
                if isinstance(order_qty, int) and order_qty > 0:
                    return int(order_qty)
    except Exception:  # defensive: DB 查询异常不阻断，由下面的统一 fail-closed 处理
        logger.warning('解析外发工序目标数量失败: process_id=%s', getattr(p, 'id', None), exc_info=True)
    raise ValueError(
        f'外发工序 {getattr(p, "id", "?")} 无法解析目标数量（SKU 明细缺失或异常），拒绝发货以防超发'
    )


# ==================== 湖北外发订单列表 ====================


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


def _process_status_order_filter(status: str):
    """把外发整体状态下推为 Order 分支的 IN 子查询（审计 M-05）。

    口径与 `_common._matches_process_status` 一致：
    - pending：有工序且全部未发货（started=0）
    - in_progress：有工序已发货且未全部收齐（started>0 且 completed<total）
    - completed：全部工序已收齐（completed=total）
    未配置工序的订单（total=0）与备货行不属于任何状态；未知状态保留「有工序」的订单
    （对应 Python 实现的 total==0 → False）。
    """
    shipped = func.coalesce(OrderOutsourceProcess.shipped_quantity, 0)
    received = func.coalesce(OrderOutsourceProcess.received_quantity, 0)
    fully_received = and_(received > 0, received >= shipped)
    total = func.count()
    completed = func.sum(case((fully_received, 1), else_=0))
    started = func.sum(case((shipped > 0, 1), else_=0))

    subquery = select(OrderOutsourceProcess.order_id).group_by(
        OrderOutsourceProcess.order_id,
    )
    if status == OutsourceOrderViewStatus.PENDING:
        subquery = subquery.having(started == 0)
    elif status == OutsourceOrderViewStatus.IN_PROGRESS:
        subquery = subquery.having(and_(started > 0, completed < total))
    elif status == OutsourceOrderViewStatus.COMPLETED:
        subquery = subquery.having(completed == total)
    return Order.id.in_(subquery)


async def list_outsource_orders(
    db: AsyncSession, *, page: int = 1, per_page: int = 50,
    customer: str | None = None, process_status: str | None = None,
    product: str | None = None,
) -> dict:
    """湖北工厂订单+备货合并列表（强制 factory=湖北）。

    复用 order_crud.get_beile_orders_with_stockins，与 beile-order 页面
    保持完全一致的筛选逻辑与返回结构；并为每个订单附加外发工序进度统计
    （total/completed/progress/current_process/status_label），供订单列表
    直接展示进度条，无需再单独打开看板。

    process_status：按订单外发工序整体状态过滤（pending/in_progress/completed），
    条件已下推到 Order 分支 SQL（HAVING），不再跨页拉全量后内存过滤；
    备货行不属于任何工序状态，状态筛选时一并排除（与 _matches_process_status 一致）。
    进度统计由数据库聚合完成（见 _common）。
    """
    from fastapi_app.services.order_crud import get_beile_orders_with_stockins
    if process_status:
        data = await get_beile_orders_with_stockins(
            db, page=page, per_page=per_page, customer=customer, factory='湖北',
            product_kw=product, skip_po_maps=True,
            order_filter=_process_status_order_filter(process_status),
            include_stockins=False,
            cache_variant=f'process_status:{process_status}',
        )
        items = _detach_page_items(data['items'])
        await _attach_progress_to_orders(db, items)
        return {**data, 'items': items}

    data = await get_beile_orders_with_stockins(
        db, page=page, per_page=per_page, customer=customer, factory='湖北',
        product_kw=product, skip_po_maps=True,
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


async def list_unshipped_processes(db: AsyncSession) -> list[dict]:
    """跨全部湖北订单聚合「未发完」工序明细（导出/打印未到货清单）。

    口径（用户裁决）：未到数量 = 订单数量 - 已发数量，仅保留 > 0 的工序。

    **工序来源为 SKU 预设**（outsource_process_type，is_active）——即用户为每个 SKU
    配置的应做工序，而非下单时生成、之后不再随预设更新的订单工序实例快照。这样
    预设变更（增删工序）后导出/打印即时生效，与每个 SKU 的预设完全一致。

    已发数量左连接订单工序实例（按 order_id + order_item_id + process_type 精确匹配）；
    无对应实例的预设工序视为未发（已发数量 0）。
    排除软删除订单（与 beile-list 一致）；下单时间按北京时间展示（与列表同口径）。
    """
    from fastapi_app.services.order.beile import _fmt_beile_time

    shipped_qty = func.coalesce(OrderOutsourceProcess.shipped_quantity, 0)
    stmt = (
        select(
            Order.id.label('order_id'),
            Order.order_no,
            Order.customer,
            Order.order_date,
            Product.name.label('product_name'),
            Product.barcode.label('product_barcode'),
            OutsourceProcessType.process_type,
            OrderItem.quantity.label('target_qty'),
            shipped_qty.label('shipped_qty'),
        )
        .select_from(OrderItem)
        .join(Order, Order.id == OrderItem.order_id)
        .join(Product, Product.id == OrderItem.product_id)
        .join(
            OutsourceProcessType,
            and_(
                OutsourceProcessType.product_id == OrderItem.product_id,
                OutsourceProcessType.is_active.is_(True),
            ),
        )
        .outerjoin(
            OrderOutsourceProcess,
            and_(
                OrderOutsourceProcess.order_id == OrderItem.order_id,
                OrderOutsourceProcess.order_item_id == OrderItem.id,
                OrderOutsourceProcess.process_type == OutsourceProcessType.process_type,
            ),
        )
        .where(
            Order.is_deleted.isnot(True),
            Product.factory == '湖北',
            OrderItem.quantity > shipped_qty,
        )
        .order_by(
            Order.order_date,
            Order.id,
            OrderItem.id,
            OutsourceProcessType.sort_order,
            OutsourceProcessType.id,
        )
    )
    rows = (await db.execute(stmt)).all()
    return [
        {
            'order_id': row.order_id,
            'order_no': row.order_no,
            'customer': row.customer,
            'order_date': _fmt_beile_time(row.order_date),
            'product_name': row.product_name,
            'product_barcode': row.product_barcode,
            'process_type': row.process_type,
            'target_qty': int(row.target_qty or 0),
            'shipped_qty': int(row.shipped_qty or 0),
            'remaining': int((row.target_qty or 0) - (row.shipped_qty or 0)),
        }
        for row in rows
    ]


async def list_shippable_processes(db: AsyncSession) -> list[dict]:
    """跨全部湖北订单聚合「待发货」工序实例（批量发货面板数据源）。

    待发货 = 已发 < 目标。返回 process_id 供批量发货定位实例。

    收货是「分批闭环」而非「整单关闭」：部分发货并收货后剩余数量仍可继续发下一批，
    故不得以 received_quantity > 0 排除（否则未发满的工序会从面板消失，无法再发货）。
    目标数量优先 SKU 明细（order_item.quantity），单 SKU 旧订单回退订单数量。
    """
    target_qty = func.coalesce(OrderItem.quantity, Order.quantity)
    shipped_qty = func.coalesce(OrderOutsourceProcess.shipped_quantity, 0)
    stmt = (
        select(
            OrderOutsourceProcess.id.label('process_id'),
            Order.id.label('order_id'),
            Order.order_no,
            Order.customer,
            OrderOutsourceProcess.product_name,
            OrderOutsourceProcess.process_type,
            target_qty.label('target_qty'),
            shipped_qty.label('shipped_qty'),
        )
        .join(Order, Order.id == OrderOutsourceProcess.order_id)
        .join(Product, Product.id == OrderOutsourceProcess.product_id)
        .outerjoin(OrderItem, OrderItem.id == OrderOutsourceProcess.order_item_id)
        .where(
            Order.is_deleted.isnot(True),
            # Z03-R7：与 docstring / list_unshipped_processes 对齐，只聚合湖北 SKU
            Product.factory == '湖北',
            shipped_qty < target_qty,
        )
        .order_by(
            Order.order_date,
            Order.id,
            OrderOutsourceProcess.order_item_id,
            OrderOutsourceProcess.sort_order,
        )
    )
    rows = (await db.execute(stmt)).all()
    return [
        {
            'process_id': row.process_id,
            'order_id': row.order_id,
            'order_no': row.order_no,
            'customer': row.customer,
            'product_name': row.product_name,
            'process_type': row.process_type,
            'target_qty': int(row.target_qty or 0),
            'shipped_qty': int(row.shipped_qty or 0),
            'remaining': int((row.target_qty or 0) - (row.shipped_qty or 0)),
        }
        for row in rows
    ]
