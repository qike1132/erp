"""外发发货单（一键发货工作流）服务

一键发货 → 生成发货单（贝乐用户端「待收货」订单）→ 贝乐确认收货 → 「已完成」闭环。
参照 beile-order 确认流程：幂等确认 + 通知派发。

- create_shipment: 一键发货，原子生成发货单 + 发货工序 + 通知贝乐
- list_shipments: 发货单列表（待收货/已完成筛选 + 计数横幅）
- get_shipment: 发货单明细（SKU + 工序 + 发货/收货数量）
- receive_shipment: 贝乐确认收货（幂等，shipped → received）
"""
import json
import logging
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from fastapi_app.services.numbering import generate_shipment_number
from fastapi_app.services.outsource._common import _fmt_dt
from fastapi_app.services.outsource._order_processes import (
    _load_order_with_skus,
    receive_order_process,
    ship_order_process,
)
from fastapi_app.shared_models import (
    SHIPMENT_STATUS_RECEIVED,
    SHIPMENT_STATUS_SHIPPED,
    Notification,
    Order,
    OrderItem,
    OrderOutsourceProcess,
    OutsourceShipment,
    OutsourceShipmentItem,
    Permission,
    User,
)

logger = logging.getLogger(__name__)

# 发货单「待收货」通知类型（贝乐用户端收货账号收到提醒）
SHIPMENT_SHIPPED_NOTIFY_TYPE = 'outsource_shipment_shipped'
SHIPMENT_SHIPPED_NOTIFY_TITLE = '新发货单待收货'


def _serialize_shipment_item(item: OutsourceShipmentItem, order_qty: int | None = None) -> dict:
    """明细行序列化。order_qty 为订单要求的该工序总数量（工序已删除时为空）。"""
    return {
        'id': item.id,
        'process_id': item.process_id,
        'product_id': item.product_id,
        'product_name': item.product_name,
        'process_type': item.process_type,
        'order_qty': order_qty,
        'shipped_quantity': item.shipped_quantity or 0,
        'received_quantity': item.received_quantity or 0,
    }


def _serialize_shipment(
    shipment: OutsourceShipment,
    include_items: bool = False,
    qty_map: dict[int, int] | None = None,
) -> dict:
    """qty_map：{工序ID: 订单数量}，仅在 include_items 时用于填充明细的 order_qty。"""
    items = shipment.items or []
    data = {
        'id': shipment.id,
        'shipment_no': shipment.shipment_no,
        'order_id': shipment.order_id,
        'customer': shipment.customer,
        'status': shipment.status,
        'shipped_at': _fmt_dt(shipment.shipped_at),
        'received_at': _fmt_dt(shipment.received_at),
        'shipped_by': shipment.shipped_by,
        'received_by': shipment.received_by,
        'remark': shipment.remark,
        'create_time': _fmt_dt(shipment.create_time),
        'item_count': len(items),
        'total_shipped': sum(it.shipped_quantity or 0 for it in items),
    }
    if include_items:
        lookup = qty_map or {}
        data['items'] = [
            _serialize_shipment_item(it, lookup.get(it.process_id) if it.process_id else None)
            for it in items
        ]
    return data


async def _load_order_qty_map(db: AsyncSession, items: list[OutsourceShipmentItem]) -> dict[int, int]:
    """批量查明细涉及工序的订单数量，避免逐行查询。

    订单数量口径与待发货面板一致（见 _queries.list_shippable_processes）：
    优先取 SKU 明细数量（order_item.quantity），单 SKU 旧订单回退订单数量（order.quantity）。

    工序被删除时 outsource_shipment_item.process_id 会置空（ON DELETE SET NULL），
    该行取不到订单数量，由调用方以 None 呈现。
    """
    ids = [it.process_id for it in items if it.process_id is not None]
    if not ids:
        return {}
    rows = (await db.execute(
        select(
            OrderOutsourceProcess.id,
            func.coalesce(OrderItem.quantity, Order.quantity).label('order_qty'),
        )
        .select_from(OrderOutsourceProcess)
        .join(Order, Order.id == OrderOutsourceProcess.order_id)
        .outerjoin(OrderItem, OrderItem.id == OrderOutsourceProcess.order_item_id)
        .where(OrderOutsourceProcess.id.in_(ids))
    )).all()
    return {r.id: int(r.order_qty or 0) for r in rows}


async def _load_order_or_raise(db: AsyncSession, order_id: int):
    """加载订单并校验（未删除、湖北工厂）；不存在或已删除抛 ValueError。"""
    order = await _load_order_with_skus(db, order_id)
    if not order or order.is_deleted:
        raise ValueError('订单不存在')
    return order


async def _dispatch_shipment_shipped_notification(
    db: AsyncSession, shipment_no: str, customer: str | None, order_id: int | None,
    items: list[dict],
) -> int:
    """向拥有 outsource_receive 权限的启用用户派发「新发货单待收货」提醒。

    参照 dispatch_beile_unconfirmed_notifications 的派发模式；无收货账号时静默返回 0。
    ``items`` 为已构造的明细摘要（product_name/process_type/quantity），
    避免在异步会话内访问 shipment.items 触发懒加载。
    """
    result = await db.execute(
        select(User.id)
        .join(User.permissions)
        .where(Permission.code == 'outsource_receive', User.status.is_(True))
        .distinct()
    )
    user_ids = [row[0] for row in result.all()]
    if not user_ids:
        return 0

    payload = {
        'format_version': 2,
        'order_type': '发货单',
        'shipment_no': shipment_no,
        'items': items,
    }
    # 合并发货单 customer 为空，通知 content 省略 customer 键，避免贝乐端展示空客户名
    if customer:
        payload['customer'] = customer
    content = json.dumps(payload, ensure_ascii=False)

    db.add_all([
        Notification(
            user_id=uid,
            type=SHIPMENT_SHIPPED_NOTIFY_TYPE,
            title=SHIPMENT_SHIPPED_NOTIFY_TITLE,
            content=content,
            related_order_id=order_id,
            is_read=False,
        )
        for uid in user_ids
    ])
    await db.flush()
    return len(user_ids)


async def create_shipment(
    db: AsyncSession, order_id: int, items: list[tuple[int, int]], username: str | None = None,
) -> dict:
    """一键发货：原子生成发货单 + 逐工序发货 + 通知贝乐收货账号。

    items: [(process_id, quantity), ...]；任一工序发货失败即抛错，由外层
    db_transaction 回滚整批（与 ship_order_processes_batch 的原子语义一致）。
    发货完成后发货单状态为 shipped（贝乐用户端「待收货」）。
    """
    if not items:
        raise ValueError('发货明细不能为空')

    order = await _load_order_or_raise(db, order_id)
    shipment_no = await generate_shipment_number(db)
    now = datetime.now(UTC)  # aware UTC：shipped_at 等列为 timestamptz，naive 值会被按本地时区解释致早 8h

    shipment = OutsourceShipment(
        shipment_no=shipment_no,
        order_id=order.id,
        customer=order.customer,
        status=SHIPMENT_STATUS_SHIPPED,
        shipped_at=now,
        shipped_by=username,
    )
    db.add(shipment)
    await db.flush()  # 取 shipment.id

    notify_items: list[dict] = []
    for process_id, quantity in items:
        p = await db.get(OrderOutsourceProcess, process_id)
        if not p:
            raise ValueError(f'外发工序 {process_id} 不存在')
        if p.order_id != order_id:
            raise ValueError(f'外发工序 {process_id} 不属于订单 {order_id}')
        # 复用既有发货逻辑（行锁 + 数量校验 + 流水）
        await ship_order_process(db, process_id, quantity, username)
        db.add(OutsourceShipmentItem(
            shipment_id=shipment.id,
            process_id=p.id,
            product_id=p.product_id,
            product_name=p.product_name,
            process_type=p.process_type,
            shipped_quantity=quantity,
            received_quantity=0,
        ))
        notify_items.append({
            'product_name': p.product_name,
            'process_type': p.process_type,
            'quantity': quantity,
        })

    await db.flush()

    # 通知贝乐收货账号（失败仅记录日志，不影响发货单创建）
    try:
        await _dispatch_shipment_shipped_notification(
            db, shipment_no, order.customer, order.id, notify_items,
        )
    except Exception:  # defensive: 服务层容错，通知失败不阻断发货
        logger.warning('发货单待收货通知派发失败：shipment_no=%s', shipment_no, exc_info=True)

    # 重新 selectinload 明细后再序列化，避免异步会话内访问 shipment.items 触发懒加载
    loaded = (await db.execute(
        select(OutsourceShipment)
        .options(selectinload(OutsourceShipment.items))
        .where(OutsourceShipment.id == shipment.id)
    )).scalars().unique().one()
    return _serialize_shipment(loaded, include_items=True)


async def list_shipments(
    db: AsyncSession, *, status: str | None = None, page: int = 1, per_page: int = 50,
) -> dict:
    """发货单列表：status=shipped(待收货)/received(已完成)/None(全部)。

    返回 items / total / page / per_page，并附 shipped_count / received_count
    供前端「待收货/已完成」计数横幅使用（参照 beile-order unconfirmed_count）。
    """
    stmt = select(OutsourceShipment).order_by(OutsourceShipment.create_time.desc(), OutsourceShipment.id.desc())
    if status in (SHIPMENT_STATUS_SHIPPED, SHIPMENT_STATUS_RECEIVED):
        stmt = stmt.where(OutsourceShipment.status == status)

    total_stmt = select(func.count()).select_from(stmt.subquery())
    total = (await db.execute(total_stmt)).scalar() or 0

    offset = (page - 1) * per_page
    rows = (await db.execute(
        stmt.options(selectinload(OutsourceShipment.items)).offset(offset).limit(per_page)
    )).scalars().unique().all()

    shipped_count = (await db.execute(
        select(func.count()).select_from(OutsourceShipment).where(OutsourceShipment.status == SHIPMENT_STATUS_SHIPPED)
    )).scalar() or 0
    received_count = (await db.execute(
        select(func.count()).select_from(OutsourceShipment).where(OutsourceShipment.status == SHIPMENT_STATUS_RECEIVED)
    )).scalar() or 0

    return {
        'items': [_serialize_shipment(s) for s in rows],
        'total': total,
        'page': page,
        'per_page': per_page,
        'shipped_count': shipped_count,
        'received_count': received_count,
    }


async def get_shipment(db: AsyncSession, shipment_id: int) -> dict | None:
    """发货单明细（含 items：SKU + 工序 + 订单数量 + 发货/收货数量）。"""
    shipment = (await db.execute(
        select(OutsourceShipment)
        .options(selectinload(OutsourceShipment.items))
        .where(OutsourceShipment.id == shipment_id)
    )).scalars().unique().one_or_none()
    if not shipment:
        return None
    qty_map = await _load_order_qty_map(db, shipment.items or [])
    return _serialize_shipment(shipment, include_items=True, qty_map=qty_map)


async def receive_shipment(db: AsyncSession, shipment_id: int, username: str | None = None) -> dict:
    """贝乐确认收货（幂等）：发货单状态 shipped → received，逐明细回写收货数量。

    幂等早退在门控之前（参照 confirm_beile_order）：已收货的历史发货单直接返回
    成功（already_received=True），不重复回写工序收货数量。
    """
    # 行锁（with_for_update，与 confirm_beile_order 同款；审计 hubei-M-2）：
    # 状态检查与写回是 check-then-act，shipment 读取必须持行锁。并发双收场景
    # （双标签页/双人同时点确认、或超时重试撞上人工点击）：无锁的 T2 会在 T1
    # 未提交前读到 status=shipped 并通过状态检查；等 T2 的 receive_order_process
    # 在工序行锁上拿到 T1 提交后的最新值时，工序剩余已是 0 → clamp_to_remaining
    # 分支返回 None → T2 把每条明细 received_quantity 覆盖为 0 并再次置
    # status=received，发货单「已完成」但明细收货数量全 0，与工序台账对不上。
    # 加行锁后 T2 在本行上等待，T1 提交后重读 status=received → 幂等早退
    # （下方 already_received 分支），明细保持 T1 写入的值。
    # selectinload 是独立的第二条查询，不影响主查询的 FOR UPDATE。
    shipment = (await db.execute(
        select(OutsourceShipment)
        .options(selectinload(OutsourceShipment.items))
        .where(OutsourceShipment.id == shipment_id)
        .with_for_update()
    )).scalars().unique().one_or_none()
    if not shipment:
        raise ValueError('发货单不存在')

    if shipment.status == SHIPMENT_STATUS_RECEIVED:
        logger.info('发货单重复确认收货（幂等）：shipment_no=%s，操作人：%s', shipment.shipment_no, username)
        return {'success': True, 'message': '发货单已收货', 'already_received': True}

    if shipment.status != SHIPMENT_STATUS_SHIPPED:
        raise ValueError(f'发货单状态异常（{shipment.status}），无法确认收货')

    # L-6（2026-11-21 审计）：receive_order_process 对工序行加 FOR UPDATE，
    # 按明细顺序逐行加锁时两张发货单明细顺序相反会形成 AB-BA 死锁；
    # 统一按 process_id 升序取锁（None=工序已删、不加锁，排最后）
    for item in sorted(shipment.items or [], key=lambda it: (it.process_id is None, it.process_id or 0)):
        # 复用既有收货逻辑（行锁 + 数量校验 + 流水）；按**本发货单明细**的发货数量收货。
        # 第八轮审计：原传 received_quantity=None → receive_order_process 取「整道工序剩余量」
        # → 分批发货时收发货单 A 会把整道工序一次收满，随后收 B 命中 _is_fully_received 报"已收货"。
        # 2026-11-16 上线前审计 H-1：另一条反向路径同样会卡死——工序面板「一键收货」（数量缺省
        # =整道剩余）先把工序收满，再来确认发货单，receive_order_process 会因「已收货」抛错，
        # 整事务回滚 ⇒ 发货单永久停在 shipped、无任何闭环出口。故本入口传 clamp_to_remaining：
        # 按「本单发货量」与「工序剩余量」取小，剩余为 0 时跳过该明细（发货单仍照常转 received）。
        #
        # 明细列语义 = **本单实际回写量**，不是发货量（推送前 OCR 复审发现项）：人工入口
        # 先在工序面板收过一部分时，clamp 后的回写量小于 shipped_quantity；剩余为 0 时
        # receive_order_process 直接返回 None（未回写工序），实际回写量为 0。
        # 旧实现一律写 shipped_quantity ⇒ 明细「收货数量」系统性虚高，与工序台账对不上。
        if item.process_id is not None:
            res = await receive_order_process(
                db, item.process_id, username,
                received_quantity=item.shipped_quantity,
                clamp_to_remaining=True,
            )
            item.received_quantity = 0 if res is None else int(res.get('applied_quantity') or 0)
        else:
            # 无工序可回写（工序已被删除，process_id 置空）：没有可对账的工序台账，
            # 保持原语义——明细按本单发货量记账，即「本单已全额确认」。
            item.received_quantity = item.shipped_quantity

    shipment.status = SHIPMENT_STATUS_RECEIVED
    shipment.received_at = datetime.now(UTC)  # aware UTC：received_at 列为 timestamptz
    shipment.received_by = username
    await db.flush()

    logger.info('发货单确认收货成功：shipment_no=%s，操作人：%s', shipment.shipment_no, username)
    return {'success': True, 'message': '确认收货成功', 'already_received': False}


async def create_merged_shipment(
    db: AsyncSession, items: list[tuple[int, int]], username: str | None = None,
) -> dict:
    """合并发货：把跨订单、跨客户的多个 SKU 合并生成一张发货单。

    items: [(process_id, quantity), ...]，不限定订单归属；发货单 order_id 与
    customer 均置空（作为独立单据，明细行仍记录各工序）。任一道工序发货失败
    即抛错，由外层 db_transaction 回滚整批。
    """
    if not items:
        raise ValueError('发货明细不能为空')

    shipment_no = await generate_shipment_number(db)
    now = datetime.now(UTC)  # aware UTC：shipped_at 列为 timestamptz

    shipment = OutsourceShipment(
        shipment_no=shipment_no,
        order_id=None,
        customer=None,
        status=SHIPMENT_STATUS_SHIPPED,
        shipped_at=now,
        shipped_by=username,
    )
    db.add(shipment)
    await db.flush()  # 取 shipment.id

    notify_items: list[dict] = []
    for process_id, quantity in items:
        p = await db.get(OrderOutsourceProcess, process_id)
        if not p:
            raise ValueError(f'外发工序 {process_id} 不存在')
        # 复用既有发货逻辑（行锁 + 数量校验 + 流水）
        await ship_order_process(db, process_id, quantity, username)
        db.add(OutsourceShipmentItem(
            shipment_id=shipment.id,
            process_id=p.id,
            product_id=p.product_id,
            product_name=p.product_name,
            process_type=p.process_type,
            shipped_quantity=quantity,
            received_quantity=0,
        ))
        notify_items.append({
            'product_name': p.product_name,
            'process_type': p.process_type,
            'quantity': quantity,
        })

    await db.flush()

    # 通知贝乐收货账号（失败仅记录日志，不影响发货单创建；合并单无客户名）
    try:
        await _dispatch_shipment_shipped_notification(
            db, shipment_no, None, None, notify_items,
        )
    except Exception:  # defensive: 服务层容错，通知失败不阻断发货
        logger.warning('合并发货单待收货通知派发失败：shipment_no=%s', shipment_no, exc_info=True)

    # 重新 selectinload 明细后再序列化，避免异步会话内访问 shipment.items 触发懒加载
    loaded = (await db.execute(
        select(OutsourceShipment)
        .options(selectinload(OutsourceShipment.items))
        .where(OutsourceShipment.id == shipment.id)
    )).scalars().unique().one()
    return _serialize_shipment(loaded, include_items=True)
