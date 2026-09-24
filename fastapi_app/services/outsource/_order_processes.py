"""外发订单工艺生成与操作(同步/自动生成/发货/收货)

从 outsource_service.py 按职责拆出,行为与原实现完全一致。
"""
import logging
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload, selectinload

from fastapi_app.services.outsource._common import (
    _derive_status,
    _is_fully_received,
    _serialize_order_process,
)
from fastapi_app.services.outsource._process_types import get_presets_for_products
from fastapi_app.services.outsource._queries import _process_target_quantity
from fastapi_app.shared_models import Order, OrderItem, OrderOutsourceProcess, OrderOutsourceProcessFlow

logger = logging.getLogger(__name__)


async def _load_order_with_skus(db: AsyncSession, order_id: int) -> Order | None:
    """加载订单并显式 eager-load items/product 关系。

    异步 SQLAlchemy 下关系默认 lazy：直接访问未加载的 order.items 会抛
    MissingGreenlet。订单创建路径中 items 是单独 flush 的，order 对象上的
    items 集合可能从未填充——必须通过查询重新加载才能拿到完整 SKU 明细。
    """
    result = await db.execute(
        select(Order)
        .options(
            joinedload(Order.product),
            selectinload(Order.items),
        )
        .where(Order.id == order_id)
    )
    return result.unique().scalar_one_or_none()

def _collect_order_skus(order: Order) -> list[tuple[int | None, int, str | None]]:
    """收集订单 SKU 维度列表 [(order_item_id, product_id, product_name)]。

    多 SKU 订单（有 OrderItem）按明细遍历；单 SKU 旧订单回退到 order.product_id。
    """
    items: list[OrderItem] = list(order.items or [])
    if items:
        return [(it.id, it.product_id, it.product_name) for it in items]
    return [(None, order.product_id, getattr(order.product, 'name', None) if order.product else None)]

async def sync_outsource_processes_for_order(
    db: AsyncSession, order: Order, username: str | None = None,
) -> tuple[int, int]:
    """根据 SKU 预设为订单自动生成外发工序（返单自动带出）。

    幂等：已存在 (order_id, order_item_id, product_id, process_type) 的跳过。
    未配置预设的产品不生成任何工序。返回 (created, skipped)。
    """
    # 重新查询并 eager-load items/product：
    # 1) 创建路径中 order.items 集合可能未填充（items 单独 flush），直接读取会漏 SKU
    # 2) 异步下 lazy 关系直接访问会抛 MissingGreenlet
    if getattr(order, 'id', None) is not None:
        loaded = await _load_order_with_skus(db, order.id)
        if loaded is not None:
            order = loaded

    skus = _collect_order_skus(order)
    if not skus:
        return 0, 0

    product_ids = list({pid for _item_id, pid, _name in skus})
    presets = await get_presets_for_products(db, product_ids)
    if not presets:
        return 0, 0

    # 已存在工序（幂等去重）
    existing_result = await db.execute(
        select(
            OrderOutsourceProcess.order_item_id,
            OrderOutsourceProcess.product_id,
            OrderOutsourceProcess.process_type,
        ).where(OrderOutsourceProcess.order_id == order.id)
    )
    existing = {
        (row[0], row[1], row[2])  # 兼容 SQLAlchemy Row（下标访问）与测试 mock 元组
        for row in existing_result.all()
    }

    created = 0
    skipped = 0
    for item_id, product_id, product_name in skus:
        for preset in presets.get(product_id, []):
            key = (item_id, product_id, preset.process_type)
            if key in existing:
                skipped += 1
                continue
            db.add(OrderOutsourceProcess(
                order_id=order.id,
                order_item_id=item_id,
                product_id=product_id,
                product_name=product_name,
                process_type=preset.process_type,
                sort_order=preset.sort_order or 0,
                status='pending',
                created_by=username,
            ))
            created += 1

    if created:
        await db.flush()
    return created, skipped

async def auto_generate_for_order(
    db: AsyncSession, order: Order, username: str | None = None,
) -> None:
    """防御性封装：订单创建时自动带出外发工序（返单自动带出）。

    供 order_crud.create_order / order_batch_create / staging_service 在事务内调用。
    失败仅记录日志，绝不影响订单创建主流程。
    """
    try:
        created, skipped = await sync_outsource_processes_for_order(db, order, username)
        if created:
            logger.info(
                "订单 %s 自动生成外发工序 %d 道（跳过 %d）",
                getattr(order, 'order_no', order.id), created, skipped,
            )
    except (SQLAlchemyError, OSError):  # defensive: 外发工序生成失败不影响订单创建
        # 仅捕获基础设施异常；编程错误（KeyError 等）自然抛出，避免被静默吞噬
        logger.exception(
            "订单 %s 自动生成外发工序失败", getattr(order, 'order_no', order.id),
        )

async def generate_order_processes(
    db: AsyncSession, order_id: int, username: str | None = None,
) -> dict:
    """为已有订单按 SKU 预设生成外发工序（返回 created/skipped 统计）。

    注意：订单列表（beile-list）的 items 可能含备货记录，其 id 是 StockIn.id
    而非 Order.id——此处用 Order 主键查询，备货记录将返回「订单不存在」。
    """
    order = await _load_order_with_skus(db, order_id)
    if not order or order.is_deleted:
        raise ValueError('订单不存在')

    created, skipped = await sync_outsource_processes_for_order(db, order, username)
    return {'created': created, 'skipped': skipped}


async def sync_orders_for_product(
    db: AsyncSession, product_id: int, username: str | None = None,
) -> dict:
    """预设变更后，把该 SKU 的所有订单实例对齐到当前启用预设（新增/移除/顺序）。

    - 新增：预设已启用、实例缺失的工序 → 补一条 pending 实例；
    - 移除：实例存在但不在启用预设中，且**未发货且无收货** → 删除；
      已发货/已收货的实例一律保留（保护发货/收货流水，不随预设删除而丢失）；
    - 顺序：仍存在的实例 sort_order 对齐到预设（其余字段不动）。

    范围：全部未删除订单（含历史）中该 SKU 的明细。返回 {'created','removed','kept'}。
    """
    presets = await get_presets_for_products(db, [product_id])
    preset_map = {p.process_type: (p.sort_order or 0) for p in presets.get(product_id, [])}

    item_rows = (await db.execute(
        select(
            OrderItem.id.label('item_id'),
            OrderItem.order_id.label('order_id'),
            OrderItem.product_name.label('product_name'),
        )
        .join(Order, Order.id == OrderItem.order_id)
        .where(OrderItem.product_id == product_id, Order.is_deleted.isnot(True))
    )).all()
    if not item_rows:
        return {'created': 0, 'removed': 0, 'kept': 0}

    item_by_id = {r.item_id: (r.order_id, r.product_name) for r in item_rows}
    instances = (await db.execute(
        select(OrderOutsourceProcess).where(
            OrderOutsourceProcess.order_item_id.in_(list(item_by_id))
        )
    )).scalars().all()

    existing_by_item: dict[int, dict[str, OrderOutsourceProcess]] = {}
    for inst in instances:
        # order_item_id 在库中非空（上面的 in_() 也永不匹配 NULL）；此判空只是让类型收窄显式化。
        if inst.order_item_id is None:
            continue
        existing_by_item.setdefault(inst.order_item_id, {})[inst.process_type] = inst

    created = removed = kept = 0
    for item_id, (order_id, product_name) in item_by_id.items():
        existing = existing_by_item.get(item_id, {})
        # 新增 / 顺序对齐
        for ptype, sort_order in preset_map.items():
            cur = existing.get(ptype)
            if cur is None:
                db.add(OrderOutsourceProcess(
                    order_id=order_id, order_item_id=item_id, product_id=product_id,
                    product_name=product_name, process_type=ptype,
                    sort_order=sort_order, status='pending', created_by=username,
                ))
                created += 1
            elif (cur.sort_order or 0) != sort_order:
                cur.sort_order = sort_order
        # 移除：仅未发货且无收货的；已发货/已收货的保留
        for ptype, inst in existing.items():
            if ptype in preset_map:
                continue
            if (inst.shipped_quantity or 0) == 0 and (inst.received_quantity or 0) == 0:
                await db.delete(inst)
                removed += 1
            else:
                kept += 1

    if created or removed:
        await db.flush()
    return {'created': created, 'removed': removed, 'kept': kept}


async def update_order_process(db: AsyncSession, process_id: int, data: dict) -> dict:
    """更新订单外发工序（计划时间/工序类型/备注，部分更新）。"""
    p = await db.get(OrderOutsourceProcess, process_id)
    if not p:
        raise ValueError('外发工序不存在')

    if data.get('process_type') is not None:
        new_type = data['process_type'].strip()
        if not new_type:
            raise ValueError('工序类型不能为空')
        p.process_type = new_type
    if data.get('sort_order') is not None:
        p.sort_order = data['sort_order']
    if 'planned_start_time' in data:
        p.planned_start_time = data['planned_start_time']
    if 'planned_end_time' in data:
        p.planned_end_time = data['planned_end_time']
    if 'remark' in data:
        p.remark = (data['remark'] or '').strip() or None

    await db.flush()
    await db.refresh(p)
    return _serialize_order_process(p)

async def ship_order_process(db: AsyncSession, process_id: int, shipped_quantity: int, username: str | None = None) -> dict:
    """发货（分批）：每次发货追加流水并累加数量，校验不超过剩余目标数量。

    收货只闭环「本批」：部分发货并收货后，剩余目标数量仍可继续发下一批，
    故不以 received_quantity > 0 拒绝发货（否则未发满的工序收货后就再也发不出去）。
    """
    # with_for_update：数量是「读-改-写」，必须锁行，否则并发发货会相互覆盖（丢失更新）
    p = await db.get(OrderOutsourceProcess, process_id, with_for_update=True)
    if not p:
        raise ValueError('外发工序不存在')
    if shipped_quantity <= 0:
        raise ValueError('发货数量必须大于 0')

    shipped_now = p.shipped_quantity or 0
    target = await _process_target_quantity(db, p)
    if target > 0:
        remaining = target - shipped_now
        if remaining <= 0:
            raise ValueError('该工序已全部发货，无需重复操作')
        if shipped_quantity > remaining:
            raise ValueError(f'发货数量超过剩余数量（剩余 {remaining}）')

    p.shipped_quantity = shipped_now + shipped_quantity
    if p.actual_start_time is None:
        p.actual_start_time = datetime.now(UTC).replace(tzinfo=None)  # naive UTC
    p.status = _derive_status(p)
    db.add(OrderOutsourceProcessFlow(
        process_id=p.id, action='ship', quantity=shipped_quantity,
        operator=username or p.created_by,
    ))
    await db.flush()
    await db.refresh(p)
    return _serialize_order_process(p)

async def receive_order_process(db: AsyncSession, process_id: int, username: str | None = None, received_quantity: int | None = None) -> dict:
    """确认收货（分批）：每次收货追加流水并累加数量，缺省=剩余待收，不超过已发货数量。"""
    # with_for_update：同发货，收货数量同样是「读-改-写」，需锁行避免并发覆盖
    p = await db.get(OrderOutsourceProcess, process_id, with_for_update=True)
    if not p:
        raise ValueError('外发工序不存在')
    if _is_fully_received(p):
        raise ValueError('该工序已收货，无需重复操作')
    shipped = p.shipped_quantity or 0
    if shipped <= 0:
        raise ValueError('该工序尚未发货，请先发货')

    received_now = p.received_quantity or 0
    remaining = shipped - received_now
    qty = received_quantity if received_quantity is not None else remaining
    if qty <= 0 or qty > remaining:
        raise ValueError(f'收货数量需在 1-{remaining} 之间')

    p.received_quantity = received_now + qty
    if p.actual_end_time is None:
        p.actual_end_time = datetime.now(UTC).replace(tzinfo=None)  # naive UTC
    p.status = _derive_status(p)
    db.add(OrderOutsourceProcessFlow(
        process_id=p.id, action='receive', quantity=qty,
        operator=username or p.created_by,
    ))
    await db.flush()
    await db.refresh(p)
    return _serialize_order_process(p)

async def ship_order_processes_batch(
    db: AsyncSession, order_id: int, items: list[tuple[int, int]], username: str | None = None,
) -> list[dict]:
    """按订单批量发货（单事务、原子）。

    逐条复用 ship_order_process（含行锁、数量校验、流水），任一条失败即抛错，
    由外层 db_transaction 回滚整批——单事务避免前端逐条请求产生的
    「部分成功」半完成状态。
    """
    results: list[dict] = []
    for process_id, quantity in items:
        try:
            item = await ship_order_process(db, process_id, quantity, username)
        except ValueError as e:
            raise ValueError(f'外发工序 {process_id}：{e}') from e
        if item['order_id'] != order_id:
            raise ValueError(f'外发工序 {process_id} 不属于订单 {order_id}')
        results.append(item)
    return results


async def ship_processes_multi(
    db: AsyncSession, items: list[tuple[int, int]], username: str | None = None,
) -> list[dict]:
    """跨订单批量发货（单事务、原子）。

    与 ship_order_processes_batch 的区别：不限定同一订单（批量发货面板跨订单/SKU）。
    逐条复用 ship_order_process（含行锁、数量校验、流水），任一条失败即抛错，
    由外层 db_transaction 回滚整批。
    """
    results: list[dict] = []
    for process_id, quantity in items:
        try:
            item = await ship_order_process(db, process_id, quantity, username)
        except ValueError as e:
            raise ValueError(f'外发工序 {process_id}：{e}') from e
        results.append(item)
    return results


async def receive_order_processes_batch(
    db: AsyncSession, order_id: int, items: list[tuple[int, int | None]], username: str | None = None,
) -> list[dict]:
    """按订单批量确认收货（单事务、原子）；quantity 为 None 时按剩余待收数量收货。"""
    results: list[dict] = []
    for process_id, quantity in items:
        try:
            item = await receive_order_process(db, process_id, username, received_quantity=quantity)
        except ValueError as e:
            raise ValueError(f'外发工序 {process_id}：{e}') from e
        if item['order_id'] != order_id:
            raise ValueError(f'外发工序 {process_id} 不属于订单 {order_id}')
        results.append(item)
    return results


async def delete_order_process(db: AsyncSession, process_id: int) -> None:
    """删除订单外发工序。"""
    p = await db.get(OrderOutsourceProcess, process_id)
    if not p:
        raise ValueError('外发工序不存在')
    await db.delete(p)
    await db.flush()
