"""
出库（StockOut）业务逻辑

包含出库核心 CRUD（*_core）、对外编排函数（create/update/delete）以及
批量出库（batch_create_stockouts / _validate_stockout_batch /
_create_stockout_records / _process_single_stockout）。

说明：内部对 get_product_for_update / calculate_available_shipment_quantity /
generate_stockout_number / log_inventory_change / publish_stock_event /
同模块 *_core 的引用统一通过 `stock_service.<name>` 解析，
以便测试通过 `fastapi_app.services.stock_service.<name>` 打 patch 时能够拦截，
同时保持对外命名空间一致。底部 import 该模块以避免循环依赖。
库存写入（product.current_stock）统一走 fastapi_app.shared.stock_concurrency 的
写入口（update_stock_with_optimistic_lock / apply_stock_delta_locked），不再直写。
"""
import logging
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from fastapi_app.core.cache_invalidation import cache_mgr, schedule_post_commit_invalidation
from fastapi_app.core.domain_events import DomainEvent, DomainEventType, schedule_post_commit_domain_event
from fastapi_app.core.exception_handler import safe_publish_event
from fastapi_app.services.business_time import fmt_business
from fastapi_app.services.notification_service import StockEvent
from fastapi_app.services.stock_common import (
    _BUSINESS_TZ,
    _parse_date_preserve_time,
    guard_stockout_deletion,
)
from fastapi_app.services.stock_event_service import (
    _publish_shipment_completed_events,
    _recalc_shipment_order_statuses,
    recalc_order_status_after_return,
)
from fastapi_app.shared.stock_concurrency import (
    apply_stock_delta_locked,
    assert_stock_available,
    update_stock_with_optimistic_lock,
)
from fastapi_app.shared_models import Product, StockIn, StockOut
from fastapi_app.utils import inventory_balance_bounds

logger = logging.getLogger(__name__)


async def _assert_inventory_balance(
    db: AsyncSession, product_id: int, product_name: str, customer: str, quantity: int,
) -> None:
    """出货前「库存（结余）」闸门（产品级）：不足则拒绝。

    口径与 /stock 页「库存」列逐字同源（包装部入库 − 已出货），见
    stock_inventory_service.get_inventory_balance。作为主闸门置于订单余量校验
    之前；订单余量闸门保留（它同时是 FIFO 分配依据）。

    Raises:
        ValueError: 库存结余小于本次出货数量。
    """
    balance = await stock_service.get_inventory_balance(db, product_id)
    if quantity > balance:
        raise ValueError(
            f'客户「{customer}」产品「{product_name}」库存不足：可用 {balance}，本次 {quantity}'
        )


async def create_stockout_core(db: AsyncSession, product_id: int, quantity: int, customer: str, stockout_date: datetime, note: str, operator_id: int | None = None, batch_no: str | None = None) -> list[StockOut]:
    # 批次串归一化：与批量路径 _process_single_stockout 同口径（schema 未做 strip，
    # 直连 API 时可带前后空白；生产记录里的批次已被 strip 过，不归一化会匹配不到 → 误报不足）。
    batch_no = (batch_no or '').strip() or None
    product = await stock_service.get_product_for_update(db, product_id)
    # 闸门口径与批量路径（_process_single_stockout）统一：库存结余 + 订单余量。
    # 产品级 current_stock 前置断言已移除（2026-10-06 批量路径同款裁定，2026-10-07
    # 对齐单条路径）：它是备货口径，与客户级订单准入自相矛盾；负库存由写入口
    # update_stock_with_optimistic_lock 的原子守卫兜底拒绝。
    await _assert_inventory_balance(db, product_id, product.name, customer, quantity)
    # 批次级闸门（与批量路径同口径）：指定批次时按该批次可用量再拦一道。
    if batch_no:
        from fastapi_app.services.finished_stock_service import get_batch_available
        batch_available = await get_batch_available(db, product_id, batch_no)
        if quantity > batch_available:
            raise ValueError(f'批次「{batch_no}」可用库存不足：可用 {batch_available}，本次 {quantity}')
    shipment_info = await stock_service.calculate_available_shipment_quantity(db, product_id, customer)
    if shipment_info['available_quantity'] <= 0:
        raise ValueError('该客户没有可用的订单支持出货！请先创建订单。')
    if quantity > shipment_info['available_quantity']:
        raise ValueError(f"出货数量超过可出货量！订单总量：{shipment_info['order_quantity']}，已出货：{shipment_info['shipped_quantity']}，可出货：{shipment_info['available_quantity']}")
    remaining_qty = quantity
    created_stockouts: list[StockOut] = []
    async with db.begin_nested():
        for order_detail in shipment_info['orders']:
            if remaining_qty <= 0:
                break
            if order_detail['available'] <= 0:
                continue
            ship_qty = min(remaining_qty, order_detail['available'])
            stockout = StockOut(stockout_no=await stock_service.generate_stockout_number(db), product_id=product_id, quantity=ship_qty, stockout_date=stockout_date, customer=customer, order_id=order_detail['order_id'], note=note, batch_no=batch_no or None)
            db.add(stockout)
            created_stockouts.append(stockout)
            remaining_qty -= ship_qty
        # 库存扣减统一走乐观锁入口（WHERE version=旧值），不再直写 current_stock
        updated = await update_stock_with_optimistic_lock(db, product_id, -quantity)
        # 第一次 flush：批量写入所有 StockOut INSERT 并填充 stockout.id（库存在上一行已 UPDATE）
        # 原 N 次 flush（N=FIFO订单数）合并为 1 次，减少数据库往返
        await db.flush()
        before, after = inventory_balance_bounds(updated.current_stock, -quantity)
        stock_service.log_inventory_change(db, product_id=product_id, change_type='出库', change_quantity=-quantity, related_id=','.join(str(stock_out.id) for stock_out in created_stockouts) if created_stockouts else '', note=f'出库数量：{quantity}', quantity_before=before, quantity_after=after, product_name=updated.name, operator_id=operator_id)
        # 第二次 flush：提前暴露 InventoryLog 写入错误（约束违反等），而非依赖 SAVEPOINT 退出时自动 flush
        # 保留原因：错误早暴露便于定位；移除则错误会延迟到 begin_nested 退出时才触发
        await db.flush()
    return created_stockouts


async def _assert_deduction_within_stockin(db: AsyncSession, stockout: StockOut, new_quantity: int) -> None:
    """抵扣行改数量后，该备货被占用的净量不得超过备货总量（不含本行自身）。"""
    stockin = await db.get(StockIn, stockout.stockin_id)
    if stockin is None:
        raise ValueError('关联的备货记录不存在')
    others = (await db.execute(
        select(func.coalesce(func.sum(StockOut.quantity - StockOut.returned_quantity), 0)).where(
            StockOut.stockin_id == stockout.stockin_id, StockOut.id != stockout.id
        )
    )).scalar() or 0
    if new_quantity - stockout.returned_quantity > stockin.quantity - int(others):
        raise ValueError('抵扣数量超过该备货可用量！')


async def update_stockout_core(db: AsyncSession, stockout: StockOut, new_quantity: int, customer: str, stockout_date: datetime, note: str, operator_id: int | None = None) -> StockOut:
    # 独立出货（stockin_id IS NULL）与备货抵扣（stockin_id 非空）都走这里：
    # 抵扣行的客户/产品由订单与备货带出（客户不可改），数量变更需保证不超过所属备货可用量。
    is_deduction = stockout.stockin_id is not None
    if new_quantity < stockout.returned_quantity:
        raise ValueError(f'出货数量不能小于已退货数量({stockout.returned_quantity})')
    old_quantity = stockout.quantity
    old_net = old_quantity - stockout.returned_quantity
    product = await stock_service.get_product_for_update(db, stockout.product_id)
    # 本次库存变化量：净出货量减少=回补库存（delta 为正），净出货量增加=扣减（delta 为负）。
    # 必须与下方写入口 `-(new_quantity - old_quantity)` 同号，也与被本入口替换掉的旧判断
    # `current_stock + old_net < new_quantity - returned` 等价（P1-2b 统一入口）。
    assert_stock_available(
        product.current_stock,
        old_net - (new_quantity - stockout.returned_quantity),
        message='库存不足！',
    )
    # 结余闸门（口径与例外全写在 stock_inventory_service.get_inventory_balance 的
    # docstring 里，含业务举例，改动前先读那段）：
    #   可出库存 = 包装部入库 − 已出货；备货 / 填充 / 手工 / 抵扣都不计入。
    # 为什么需要它：上面的 current_stock 含备货与半成品，恒 ≥ 结余，只判它会让
    # 「编辑出货把数量调大」绕过「备货不得直接出货」，把结余扣成负数。
    # 只判**净增部分**：把出货改小是释放库存，即便结余已为负也必须放行。
    # 抵扣行不走此闸门 —— 抵扣不动结余，其上限由 _assert_deduction_within_stockin 约束。
    if not is_deduction:
        _net_increase = (new_quantity - stockout.returned_quantity) - old_net
        if _net_increase > 0:
            await _assert_inventory_balance(
                db, stockout.product_id, product.name, customer, _net_increase,
            )
    if is_deduction:
        # 抵扣行：客户不可改（改客户会与订单/备货脱钩），并校验不超过所属备货可用量
        customer = stockout.customer or ''
        await _assert_deduction_within_stockin(db, stockout, new_quantity)
    elif customer and customer.strip():
        shipment_info = await stock_service.calculate_available_shipment_quantity(db, stockout.product_id, customer)
        available_with_current = shipment_info['available_quantity'] + old_net
        if new_quantity - stockout.returned_quantity > available_with_current:
            raise ValueError(f"出货数量超过可出货量！订单总量：{shipment_info['order_quantity']}，可出货（含当前记录）：{available_with_current}")
        # P1-5：改客户必须同步迁移 order_id——已出货量按 order_id 聚合，只换 customer
        # 会让新客户额度不扣本行净额（可超订单总量出货）、旧订单余量仍被占用。
        # 单行不能跨订单拆分：新客户需有单个订单能容纳本行净额，否则明确拒绝。
        if customer.strip() != (stockout.customer or '').strip():
            new_net = new_quantity - stockout.returned_quantity
            candidates = [o for o in shipment_info['orders'] if o['available'] >= new_net]
            if not candidates:
                raise ValueError('新客户没有单个订单可容纳本次净出货量，请删除该出货后按新客户重新出货')
            stockout.order_id = candidates[0]['order_id']
    # 批次级闸门：该行带批次时，数量净增不得超过该批次可用（可用量已扣掉本行自身净额，
    # 故用「本次净增」比：new_net − old_net ≤ 当前批次可用）。删除路径不需校验（会释放批次量）。
    # 仅对真实非空批次串生效（batch_no 为 None/空 时不查，保持既有行为）。
    batch_no_val = stockout.batch_no
    if isinstance(batch_no_val, str) and batch_no_val.strip() and not is_deduction:
        from fastapi_app.services.finished_stock_service import get_batch_available
        batch_available = await get_batch_available(db, stockout.product_id, batch_no_val)
        net_delta = (new_quantity - stockout.returned_quantity) - old_net
        # 只在净增时拦：净减/不变是释放批次量，即便该批次已被透支（可用为负）也必须放行，
        # 否则「把出货改小」这种修复动作反而被拒。
        if net_delta > 0 and net_delta > batch_available:
            raise ValueError(f'批次「{batch_no_val}」可用库存不足：可用 {batch_available}，本次净增 {net_delta}')
    stockout.quantity = new_quantity
    stockout.stockout_date = stockout_date
    stockout.customer = customer
    stockout.note = note
    if new_quantity != old_quantity:
        delta = -(new_quantity - old_quantity)
        updated = await update_stock_with_optimistic_lock(db, stockout.product_id, delta)
        before, after = inventory_balance_bounds(updated.current_stock, delta)
        # 流水类型必须与「建立抵扣」一侧对称（P0-1）：订单抵扣建立时写 '订单抵扣'，
        # 而结余公式只统计 ('出库','出库修改','出库删除','退货','退货取消')。
        # 抵扣行若也写 '出库修改'，则建立时不进结余、修改/删除时进结余 → 结余凭空虚增。
        # 故抵扣行改用 '抵扣修改'，与 '订单抵扣/取消抵扣/抵扣回滚' 同属不进结余的抵扣三型。
        _change_type = '抵扣修改' if is_deduction else '出库修改'
        stock_service.log_inventory_change(db, product_id=stockout.product_id, change_type=_change_type, change_quantity=delta, related_id=str(stockout.id), note=f'{_change_type}ID：{stockout.id}', quantity_before=before, quantity_after=after, product_name=updated.name, operator_id=operator_id)
    await db.flush()
    return stockout


async def delete_stockout_core(db: AsyncSession, stockout: StockOut, operator_id: int | None = None) -> None:
    # 独立出货与备货抵扣均可删除：抵扣行删除后所属备货可用量随之释放（派生），
    # 关联订单状态由调用方重算（见 delete_stockout）。
    if stockout.returned_quantity > 0:
        raise ValueError('该出货记录已有退货关联，无法删除！请先取消退货记录。')
    # 072 RESTRICT 的应用层前置：守卫与「订单抵扣减少」路径共用同一实现
    # （stock_common.guard_stockout_deletion），避免逐点各写一份而漂移。
    await guard_stockout_deletion(db, stockout)
    # 先取行锁（产品不存在时由 get_product_for_update 抛错），库存写入走统一乐观锁入口
    await stock_service.get_product_for_update(db, stockout.product_id)
    updated = await update_stock_with_optimistic_lock(db, stockout.product_id, stockout.quantity)
    before, after = inventory_balance_bounds(updated.current_stock, stockout.quantity)
    # 同 update_stockout_core：抵扣行删除写 '抵扣删除'，与建立时的 '订单抵扣' 同属不进结余的
    # 抵扣类型；若写 '出库删除'，结余会凭空虚增该抵扣量（P0-1）。
    _is_deduction = stockout.stockin_id is not None
    _change_type = '抵扣删除' if _is_deduction else '出库删除'
    stock_service.log_inventory_change(db, product_id=stockout.product_id, change_type=_change_type, change_quantity=stockout.quantity, related_id=str(stockout.id), note=f'{_change_type}ID：{stockout.id}', quantity_before=before, quantity_after=after, product_name=updated.name, operator_id=operator_id)
    await db.delete(stockout)
    await db.flush()


async def create_stockout(db: AsyncSession, product_id: int, quantity: int, customer: str, stockout_date_str: str, note: str, operator_id: int | None = None, batch_no: str | None = None) -> dict:
    """创建出库记录"""
    stockout_date = _parse_date_preserve_time(stockout_date_str)
    created_stockouts = await stock_service.create_stockout_core(db, product_id, quantity, customer, stockout_date, note, operator_id=operator_id, batch_no=batch_no)
    shipment_completed_orders = await _recalc_shipment_order_statuses(db, created_stockouts)

    await db.flush()
    await cache_mgr.invalidate_stock_and_order()
    schedule_post_commit_invalidation(db, cache_mgr.invalidate_stock_and_order)
    product = await db.get(Product, product_id)
    if product is not None:
        await safe_publish_event(stock_service.publish_stock_event, StockEvent.STOCK_CHANGED, {'product_id': product_id, 'product_name': product.name, 'change_type': '出库', 'quantity': quantity, 'current_stock': product.current_stock}, context="出库事件发布")

    await _publish_shipment_completed_events(shipment_completed_orders)

    # 领域事件总线：出库单创建 → 发布 STOCK_OUT_CREATED 事件，供跨域订阅者消费
    # 采购计划重算与缓存失效由 purchase_plan_service 的事件处理器异步执行，解耦循环依赖
    # 提交后发布：订阅者（采购计划 FIFO 重算）用独立 session 读库，
    # 提交前发布会读不到本次出货行，按旧数据算错并落库
    plan_month = fmt_business(stockout_date, '%Y-%m') if stockout_date else ''
    product_name = product.name if product is not None else ''
    schedule_post_commit_domain_event(db, DomainEvent(
        event_type=DomainEventType.STOCK_OUT_CREATED,
        domain='stock',
        payload={
            'product_id': product_id,
            'quantity': quantity,
            'customer': customer,
            'product_name': product_name,
            'plan_month': plan_month,
        },
    ))

    logger.info(f'出库添加成功：产品ID：{product_id}，数量：{quantity}，客户：{customer}')
    return {'quantity': quantity}


async def update_stockout(db: AsyncSession, stockout_id: int, new_quantity: int, customer: str, stockout_date_str: str, note: str, operator_id: int | None = None) -> None:
    """更新出库记录"""
    pid_result = await db.execute(select(StockOut.product_id).where(StockOut.id == stockout_id))
    pid_row = pid_result.one_or_none()
    if not pid_row:
        raise ValueError('出库记录不存在')
    await stock_service.get_product_for_update(db, pid_row[0])
    result = await db.execute(select(StockOut).where(StockOut.id == stockout_id).with_for_update())
    stockout_obj = result.scalar_one_or_none()
    if not stockout_obj:
        raise ValueError('出库记录不存在')
    stockout_date = _parse_date_preserve_time(stockout_date_str)
    old_quantity = stockout_obj.quantity
    old_stockout_no = stockout_obj.stockout_no
    old_order_id = stockout_obj.order_id  # P1-5：改客户会迁移 order_id，旧订单也要重算状态
    await update_stockout_core(db, stockout_obj, new_quantity, customer, stockout_date, note, operator_id=operator_id)
    await db.flush()
    # 订单状态派生重算：出货量（含抵扣行的抵扣量）变化会影响订单状态；函数名虽为
    # return，逻辑是通用的「按出入库派生重算」（锁序 Product→StockOut→Order，与退货路径一致）
    completed_shipments = []
    for order_id in dict.fromkeys([old_order_id, stockout_obj.order_id]):
        if not order_id:
            continue
        shipment_completed = await recalc_order_status_after_return(db, order_id)
        if shipment_completed:
            completed_shipments.append(shipment_completed)
    await cache_mgr.invalidate_stock_and_order()
    schedule_post_commit_invalidation(db, cache_mgr.invalidate_stock_and_order)
    product = await db.get(Product, stockout_obj.product_id)
    if product is not None:
        await safe_publish_event(stock_service.publish_stock_event, StockEvent.STOCK_CHANGED, {'product_id': stockout_obj.product_id, 'product_name': product.name, 'change_type': '出库编辑', 'quantity': new_quantity, 'current_stock': product.current_stock}, context="出库编辑事件发布")
    if completed_shipments:
        await _publish_shipment_completed_events(completed_shipments)

    # 领域事件总线：出库单更新 → 发布 STOCK_OUT_UPDATED 事件，触发采购计划缓存失效（异步）
    # 提交后发布（同 create_stockout：订阅者用独立 session 读库）
    plan_month = fmt_business(stockout_obj.stockout_date, '%Y-%m') if stockout_obj.stockout_date else ''
    schedule_post_commit_domain_event(db, DomainEvent(
        event_type=DomainEventType.STOCK_OUT_UPDATED,
        domain='stock',
        payload={
            'product_id': stockout_obj.product_id,
            'customer': customer,
            'product_name': product.name if product is not None else '',
            'plan_month': plan_month,
        },
    ))

    logger.info(f'出库编辑成功：{old_stockout_no}，数量变更：{old_quantity} -> {new_quantity}')


async def delete_stockout(db: AsyncSession, stockout_id: int, operator_id: int | None = None) -> None:
    """删除出库记录"""
    # 第十四轮：锁序统一为 Product→StockOut —— update_stockout 是 P→SO，本函数原为
    # SO→P（先锁出库行、delete_stockout_core 内再锁产品），同张出库单「编辑 vs 删除」
    # 并发会互等行锁死锁。与 cancel_stockreturn_core / update_stockin 的既修口径一致。
    pid_result = await db.execute(select(StockOut.product_id).where(StockOut.id == stockout_id))
    pid_row = pid_result.one_or_none()
    if not pid_row:
        raise ValueError('出库记录不存在')
    await stock_service.get_product_for_update(db, pid_row[0])
    result = await db.execute(select(StockOut).where(StockOut.id == stockout_id).with_for_update())
    stockout_obj = result.scalar_one_or_none()
    if not stockout_obj:
        raise ValueError('出库记录不存在')
    stockout_no = stockout_obj.stockout_no
    deleted_quantity = stockout_obj.quantity
    customer_name = stockout_obj.customer or ''
    order_id = stockout_obj.order_id
    product_result = await db.execute(select(Product.name).where(Product.id == stockout_obj.product_id))
    product_name_row = product_result.one_or_none()
    product_name = product_name_row[0] if product_name_row else ''
    await stock_service.delete_stockout_core(db, stockout_obj, operator_id=operator_id)
    await db.flush()
    # 订单状态派生重算：删掉一条出货（含抵扣行）会释放对应出货/抵扣量
    if order_id:
        await recalc_order_status_after_return(db, order_id)
    await cache_mgr.invalidate_stock_and_order()
    schedule_post_commit_invalidation(db, cache_mgr.invalidate_stock_and_order)
    product = await db.get(Product, stockout_obj.product_id)
    if product is not None:
        await safe_publish_event(stock_service.publish_stock_event, StockEvent.STOCK_CHANGED, {'product_id': stockout_obj.product_id, 'product_name': product.name, 'change_type': '出库删除', 'quantity': -deleted_quantity, 'current_stock': product.current_stock}, context="出库删除事件发布")

    # 领域事件总线：出库单删除 → 发布 STOCK_OUT_DELETED 事件，触发采购计划重算与缓存失效（异步）
    # 提交后发布（同 create_stockout：订阅者用独立 session 读库）
    plan_month = fmt_business(stockout_obj.stockout_date, '%Y-%m') if stockout_obj.stockout_date else ''
    schedule_post_commit_domain_event(db, DomainEvent(
        event_type=DomainEventType.STOCK_OUT_DELETED,
        domain='stock',
        payload={
            'product_id': stockout_obj.product_id,
            'customer': customer_name,
            'product_name': product_name,
            'stockout_no': stockout_no,
            'deleted_quantity': deleted_quantity,
            'plan_month': plan_month,
        },
    ))

    logger.info(f'出库删除成功：{stockout_no}，数量：{deleted_quantity}')


def _validate_stockout_batch(stockouts_data: list) -> tuple[list, dict]:
    """校验批量出库数据，返回 (有效项 (idx, item) 列表, 错误映射)"""
    validated = []
    errors_map = {}
    for idx, item in enumerate(stockouts_data):
        product_id = item.get('product_id')
        customer = str(item.get('customer', '')).strip()
        quantity = item.get('quantity', 0)
        if not all([product_id, quantity]):
            errors_map[idx] = '缺少必填字段'
            continue
        if not customer:
            errors_map[idx] = '出货必须选择客户'
            continue
        if int(quantity) <= 0:
            errors_map[idx] = '出货数量必须大于0'
            continue
        validated.append((idx, item))
    return validated, errors_map


def _resolve_stockout_datetime(date_str: str) -> datetime:
    """YYYY-MM-DD → 该日北京墙钟（时分秒取当前北京时间）对应的 aware UTC。

    stock_out.stockout_date 是 timestamptz，报表用 ``to_char(...)`` 在会话时区
    Asia/Shanghai 下渲染。旧实现把北京墙钟 ``.replace(tzinfo=UTC)``，等于把它当
    UTC 再按 +8 渲染 → 显示晚 8 小时（2026-10-14 SO-20261014-0001 实测 11:20 → 19:20）。
    口径与 ``order_batch_create._resolve_order_date`` 一致（2026-10-13 下单时间同类修复）。
    """
    return _parse_date_preserve_time(date_str).replace(tzinfo=_BUSINESS_TZ).astimezone(UTC)


async def _create_stockout_records(db: AsyncSession, product_id: int, customer: str,
                                   note: str, stockout_date: datetime, quantity: int,
                                   orders: list, batch_no: str | None = None) -> list[StockOut]:
    """按 FIFO 分配订单，创建出库记录。

    batch_no 非空时写到该次产生的**每一张** stock_out（FIFO 拆多行时全写）——
    语义 = 这批货都出自该批次，供成品库存批次级扣减聚合。
    """
    remaining_qty = quantity
    created_stockouts: list[StockOut] = []
    for order_detail in orders:
        if remaining_qty <= 0:
            break
        if order_detail['available'] <= 0:
            continue
        ship_qty = min(remaining_qty, order_detail['available'])
        stockout_no = await stock_service.generate_stockout_number(db)
        stockout = StockOut(
            stockout_no=stockout_no, product_id=product_id, quantity=ship_qty,
            stockout_date=stockout_date,
            customer=customer, order_id=order_detail['order_id'], note=note,
            batch_no=batch_no or None,
        )
        db.add(stockout)
        created_stockouts.append(stockout)
        remaining_qty -= ship_qty
    # 单次 flush：批量写入所有 StockOut INSERT 并填充 id，供调用方构建 related_id
    # 原 N 次 flush（N=FIFO订单数）合并为 1 次
    if created_stockouts:
        await db.flush()
    return created_stockouts


async def _process_single_stockout(db: AsyncSession, item: dict, operator_id: int | None = None) -> dict:
    """处理单条出库记录的创建（含库存校验、订单分配、库存扣减）"""
    product_id = item.get('product_id')
    customer = str(item.get('customer', '')).strip()
    quantity = int(item.get('quantity', 0))
    note = item.get('note', '')
    stockout_date_str = item.get('stockout_date') or ''
    batch_no = str(item.get('batch_no') or '').strip()
    item_id = item.get('id', '未知')
    try:
        # P2-A2 类型收窄：_validate_stockout_batch 已过滤缺 product_id 的项；
        # None 时抛出的文案与 get_product_for_update 内部逐字一致，且同样由下方 except ValueError 捕获
        if product_id is None:
            raise ValueError(f'产品ID {product_id} 不存在')
        product = await stock_service.get_product_for_update(db, product_id)

        # 库存结余主闸门（2026-10-07 用户裁决）：按 /stock 页「库存」列口径
        # （包装部入库 − 已出货，产品级）先拦一道，不足即拒。
        await _assert_inventory_balance(db, product_id, product.name, customer, quantity)

        # 批次级闸门（成品库存方案 §三）：指定批次时按该批次可用量再拦一道。
        # 产品级结余闸门（上面）保持不变，批次闸门只是在其上叠加更细的约束，
        # 两页（/stock 与 /finished-stock）不会分叉。持产品行锁后校验，避免 TOCTOU。
        if batch_no:
            from fastapi_app.services.finished_stock_service import get_batch_available
            batch_available = await get_batch_available(db, product_id, batch_no)
            if quantity > batch_available:
                return {'success': False, 'error': f'批次「{batch_no}」可用库存不足：可用 {batch_available}，本次 {quantity}', 'id': item_id}

        # 库存准入校准（2026-10-06 用户裁决）：按「客户+产品」订单余量口径
        # ——出货量受限于该客户该产品的订单总量与已出货量之差，与 /stock 页
        # available_stock 同源。前置的 product.current_stock 校验移除：
        # 它是备货口径，与客户级出货准入自相矛盾（且 apply_stock_delta_locked
        # 已在扣减时附带原子负库存守卫，最终不可能写出负库存）。
        shipment_info = await stock_service.calculate_available_shipment_quantity(db, product_id, customer)
        if shipment_info['available_quantity'] <= 0:
            return {'success': False, 'error': '该客户没有可用的订单支持出货！请先创建订单。', 'id': item_id}
        if quantity > shipment_info['available_quantity']:
            return {'success': False, 'error': f"出货数量超过可出货量！订单总量：{shipment_info['order_quantity']}，已出货：{shipment_info['shipped_quantity']}，可出货：{shipment_info['available_quantity']}", 'id': item_id}

        # 日期解析必须放在扣减之前：非法日期会抛 ValueError，被本函数外层 except
        # 转成逐条失败而不回滚；若此时库存已扣，就会静默丢库存（审核 High）。
        resolved_stockout_date = (
            _resolve_stockout_datetime(stockout_date_str) if stockout_date_str else datetime.now(UTC)
        )
        # 先扣库存再建出货行：扣减被负库存守卫拒绝时（ValueError）此时尚未写入任何
        # stock_out 行，失败分支直接 return 不会留下幽灵出货行（P0-1）。
        # 建行/写流水若抛 DB 异常则向上冒泡，外层事务整体回滚，同样不会半写。
        try:
            updated = await apply_stock_delta_locked(db, product, -quantity)
        except ValueError as stock_denied:
            # 与历史「库存不足，当前库存: X」同形态返回，避免前端单条错误解析变化
            return {'success': False, 'error': str(stock_denied), 'id': item_id}
        created_stockouts = await _create_stockout_records(db, product_id, customer, note, resolved_stockout_date, quantity, shipment_info['orders'], batch_no=batch_no or None)
        before, after = inventory_balance_bounds(updated.current_stock, -quantity)
        stock_service.log_inventory_change(db, product_id=product_id, change_type='出库', change_quantity=-quantity, related_id=','.join(str(stockout.id) for stockout in created_stockouts) if created_stockouts else '', note=f'出库数量：{quantity}', quantity_before=before, quantity_after=after, product_name=updated.name, operator_id=operator_id)
        await db.flush()

        stockout_nos = [stockout.stockout_no for stockout in created_stockouts] if created_stockouts else []
        return {'success': True, 'stockout_no': stockout_nos[0] if stockout_nos else '', 'id': item_id}
    except ValueError as e:
        return {'success': False, 'error': str(e), 'id': item_id}
    except (TypeError, OSError) as e:
        logger.error(f'批量出库单项失败: {e}', exc_info=True)
        return {'success': False, 'error': str(e) or '出库处理失败，请稍后重试', 'id': item_id}


async def batch_create_stockouts(db: AsyncSession, stockouts_data: list, operator_id: int | None = None) -> dict:
    """批量创建出库记录（自包含，不调用 create_stockout_core，无嵌套事务）"""
    validated, errors_map = _validate_stockout_batch(stockouts_data)
    results: list[dict[str, Any] | None] = [None] * len(stockouts_data)
    for idx, err in errors_map.items():
        results[idx] = {'success': False, 'error': err, 'id': stockouts_data[idx].get('id', '未知')}
    for orig_idx, item in validated:
        results[orig_idx] = await _process_single_stockout(db, item, operator_id=operator_id)
    all_success = all(result is not None and result.get('success') for result in results)
    return {'success': all_success, 'results': results}


# 底部引入 stock_service 以提供命名空间解析（延迟到调用期，避免循环依赖）
from fastapi_app.services import stock_service
