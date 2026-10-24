"""
退货（StockReturn）业务逻辑

包含退货核心操作（*_core）与对外编排函数（create/cancel）。
取消退货 = **直接删除记录**（2026-10-09 起，取代 P1-① 的「软取消保留记录」）：
库存/流水/订单状态走与删除完全相同的对称回冲链路，回冲完成后删除该行。
P1-② 订单抵扣出货（stockin_id 非空）与独立出货同等可退。
create 支持 request_id 幂等令牌（前端每次打开弹窗生成，重试去重）。

说明：内部对 generate_stockreturn_number / get_product_for_update /
log_inventory_change / publish_stock_event 的引用统一通过 `stock_service.<name>`
解析，以便测试通过 `fastapi_app.services.stock_service.<name>` 打 patch 时能够拦截，
同时保持对外命名空间一致。底部 import 该模块以避免循环依赖。
库存写入（product.current_stock）统一走 fastapi_app.shared.stock_concurrency 的
update_stock_with_optimistic_lock，不再直写。
"""
import logging
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from fastapi_app.core.cache_invalidation import cache_mgr, schedule_post_commit_invalidation
from fastapi_app.core.domain_events import DomainEvent, DomainEventType, schedule_post_commit_domain_event
from fastapi_app.core.exception_handler import safe_publish_event
from fastapi_app.core.sanitizer import escape_like
from fastapi_app.services.notification_service import StockEvent
from fastapi_app.services.numbering import generate_number_async
from fastapi_app.services.numbering_sequence import _BUSINESS_TZ
from fastapi_app.services.stock_common import _parse_date_preserve_time, business_now
from fastapi_app.services.stock_event_service import recalc_order_status_after_return
from fastapi_app.shared.stock_concurrency import assert_stock_available, update_stock_with_optimistic_lock
from fastapi_app.shared_models import InventoryLog, Product, StockOut, StockReturn
from fastapi_app.utils import inventory_balance_bounds

logger = logging.getLogger(__name__)


async def generate_stockreturn_number(db: AsyncSession) -> str:
    """生成退货编号 SR-YYYYMMDD-XXXX"""
    return await generate_number_async('SR', StockReturn, 'return_no', db)


async def create_stockreturn_core(db: AsyncSession, stockout_id: int, quantity: int,
                                  return_date: datetime, reason: str | None = None,
                                  note: str | None = None,
                                  request_id: str | None = None,
                                  operator_id: int | None = None) -> StockReturn:
    """创建退货记录核心逻辑（按出货明细退货：搜产品 -> 选出货单 -> 录数量）

    录入流程：新建退货单 -> 搜索产品名 -> 弹出该产品全部出货明细 -> 勾选要退的
    出货单 -> 录数量。可退量 = 该出货单数量 - 已退货量；客户/产品/订单由所选
    明细带出，退回数量落在该出货单的已退量上，并重算订单状态、回补总库存。
    仅独立出货（``stockin_id IS NULL``）可退；备货抵扣行不是实际出货，拒绝退货。

    request_id：前端每次打开新增弹窗生成的幂等令牌（同一次弹窗内重试视为同一请求）。
    命中即拒，防网络重试/双击造成的重复退货；重新打开弹窗会生成新令牌，不误杀合法的二次退货。
    idem_key 直接存原始令牌（UUID），不与 staging 的键空间重叠，无需前缀拼接。
    """
    if quantity <= 0:
        raise ValueError('退货数量必须大于0')

    # 锁序统一为 Product->StockOut（第十四轮死锁修复口径）
    pid_row = (await db.execute(select(StockOut.product_id).where(StockOut.id == stockout_id))).one_or_none()
    if not pid_row:
        raise ValueError('出货记录不存在')
    await stock_service.get_product_for_update(db, pid_row[0])

    stockout_result = await db.execute(select(StockOut).where(StockOut.id == stockout_id).with_for_update())
    stockout = stockout_result.scalar_one_or_none()
    if not stockout:
        raise ValueError('出货记录不存在')
    # 只退真出货：备货抵扣行（stockin_id 非空）不是实际出货，拒绝退货。
    # 否则会写 '退货' 正流水，而结余公式含「退货」、不含「订单抵扣」→
    # /stock「库存(结余)」虚增（抵扣从未减过结余、退货却往上加）。
    # 与界面 search_returnable_stockouts（仅列 stockin_id IS NULL）对齐。
    if stockout.stockin_id is not None:
        raise ValueError('备货抵扣行不是实际出货，不可退货')

    available = stockout.quantity - stockout.returned_quantity
    if quantity > available:
        raise ValueError(f'退货数量超过可退数量！出货数量：{stockout.quantity}，已退货：{stockout.returned_quantity}，可退：{available}')

    # 幂等键 = 前端原始 requestId（UUID 字符串）。刻意不做任何拼接/格式化
    # （Mimosa 写入门禁对外部输入构造查询键零容忍），uq_inventory_log_idem 兜底。
    idem_key = request_id or None
    if idem_key:
        dup = (await db.execute(
            select(InventoryLog.id).where(InventoryLog.idem_key == idem_key)
        )).first()
        if dup:
            raise ValueError('请勿重复提交：该请求已登记过退货')

    return_no = await stock_service.generate_stockreturn_number(db)

    stockreturn = StockReturn(
        return_no=return_no,
        return_date=return_date,
        product_id=stockout.product_id,
        quantity=quantity,
        customer=stockout.customer,
        stockout_id=stockout_id,
        order_id=stockout.order_id,
        reason=reason,
        note=note,
    )
    db.add(stockreturn)
    await db.flush()

    # 退回数量落在所选出货明细上：累计已退量（列表/订单状态均可见）
    stockout.returned_quantity += quantity

    # 恢复库存（统一走乐观锁写入口，WHERE version=旧值；不直写 current_stock）
    await stock_service.get_product_for_update(db, stockout.product_id)
    updated = await update_stock_with_optimistic_lock(db, stockout.product_id, quantity)

    # 写入库存日志（idem_key 供请求级防重；uq_inventory_log_idem 兜底）
    before, after = inventory_balance_bounds(updated.current_stock, quantity)
    stock_service.log_inventory_change(db, product_id=stockout.product_id, change_type='退货', change_quantity=quantity, related_id=str(stockreturn.id), note=f'退货ID：{stockreturn.id}，关联出货ID：{stockout_id}', customer=stockout.customer, idem_key=idem_key, quantity_before=before, quantity_after=after, product_name=updated.name, operator_id=operator_id)

    # 重算订单状态（需先flush确保SUM查询读到最新的returned_quantity）
    if stockout.order_id:
        await db.flush()
        await recalc_order_status_after_return(db, stockout.order_id)

    await db.flush()
    return stockreturn


async def search_returnable_stockouts(db: AsyncSession, keyword: str, limit: int = 50) -> list[dict]:
    """按产品名称模糊搜索可退的**独立出货**明细（退货单录入第二步的数据源）。

    录入流程：搜产品名 -> 弹出该产品全部出货明细（单号/客户/数量/已退/可退/日期）
    -> 勾选要退的明细 -> 录数量。仅独立出货（``stockin_id IS NULL``）——备货抵扣行不是
    实际出货，退货只针对真正出过货的单；仅列可退量 > 0 的明细，按出货时间倒序；
    关键词为空时列最近的全部可退明细。客户/订单由所选明细带出。
    """
    name_filter = '%' + escape_like(keyword) + '%' if keyword else '%'
    result = await db.execute(
        select(StockOut)
        .options(joinedload(StockOut.product))
        .join(Product, StockOut.product_id == Product.id)
        .where(
            StockOut.stockin_id.is_(None),
            StockOut.quantity > StockOut.returned_quantity,
            Product.name.like(name_filter),
        )
        .order_by(StockOut.stockout_date.desc(), StockOut.id.desc())
        .limit(limit)
    )
    stockouts = result.scalars().unique().all()
    data = []
    for s in stockouts:
        data.append({
            'stockout_id': s.id,
            'stockout_no': s.stockout_no,
            'stockout_date': s.stockout_date.strftime('%Y-%m-%d') if s.stockout_date else '',
            'product_id': s.product_id,
            'product_name': s.product.name if s.product else '',
            'customer': s.customer,
            'quantity': s.quantity,
            'returned_quantity': s.returned_quantity,
            'batch_no': s.batch_no or '',
            'available': s.quantity - s.returned_quantity,
        })
    return data


async def cancel_stockreturn_core(db: AsyncSession, stockreturn: StockReturn, operator_id: int | None = None) -> None:
    """取消退货记录核心逻辑（回冲库存/出货累计/订单状态后**删除该行**）

    分支：历史关联行（stockout_id 非空）先回减 stock_out.returned_quantity；
    按产品退货的新行（stockout_id=NULL）无出货可回减。锁序 Product→StockOut。
    """
    if stockreturn.status != 'active':
        raise ValueError('该退货已取消，请勿重复操作')
    await stock_service.get_product_for_update(db, stockreturn.product_id)

    stockout = None
    if stockreturn.stockout_id is not None:
        s_res = await db.execute(select(StockOut).where(StockOut.id == stockreturn.stockout_id).with_for_update())
        stockout = s_res.scalar_one_or_none()
        if not stockout:
            raise ValueError('关联的出货记录不存在')
        if stockout.returned_quantity < stockreturn.quantity:
            raise ValueError('退货数量异常：累计退货量小于待取消的退货数量')
        stockout.returned_quantity -= stockreturn.quantity

    # 扣回库存
    product = await stock_service.get_product_for_update(db, stockreturn.product_id)
    # 结余闸门（口径见 stock_inventory_service.get_inventory_balance 的 docstring）：
    # 取消退货 = 这批货重新发出，可出库存必须撑得住，否则结余会被扣成负数 ——
    # 而 /stock 的「库存」列与出货主闸门读的都是结余，不是 current_stock。
    # 退货本身已把 +qty 计入结余，所以正常单据在这里恒能通过；拦住的是
    # 「退货后又被别的出货把结余吃掉」这种超额场景。
    _balance = await stock_service.get_inventory_balance(db, stockreturn.product_id)
    if stockreturn.quantity > _balance:
        raise ValueError(
            f'取消退货将导致库存（结余）为负数：可用 {_balance}，本次回冲 {stockreturn.quantity}'
        )
    # 负库存判定统一走统一入口（P1-2b），文案与改动前逐字一致
    assert_stock_available(
        product.current_stock, -stockreturn.quantity,
        message=f'取消退货将导致库存为负数（当前库存：{product.current_stock}，退货数量：{stockreturn.quantity}）',
    )
    # 扣回库存统一走乐观锁写入口（不直写 current_stock）
    updated = await update_stock_with_optimistic_lock(db, stockreturn.product_id, -stockreturn.quantity)

    # 写入库存日志（取消 = 退货的反向，type 与退货区分便于对账）
    before, after = inventory_balance_bounds(updated.current_stock, -stockreturn.quantity)
    stock_service.log_inventory_change(db, product_id=stockreturn.product_id, change_type='退货取消', change_quantity=-stockreturn.quantity, related_id=str(stockreturn.id), note=f'退货取消ID：{stockreturn.id}', customer=stockreturn.customer, quantity_before=before, quantity_after=after, product_name=updated.name, operator_id=operator_id)

    # 仅历史关联行有 order_id：按产品退货不重算任何订单
    if stockreturn.order_id:
        await db.flush()
        await recalc_order_status_after_return(db, stockreturn.order_id)

    # 取消退货 = 回冲完成后直接删除记录（2026-10-09 起取代「软取消保留记录」）。
    # 保留 cancelled 行会堆积用户看不见的作废记录，且其 product_id 外键
    # （NOT NULL + RESTRICT）会永久阻塞产品删除；库存流水已写下「退货」「退货取消」
    # 两条，对账口径不依赖退货行本身，故直接删行不丢库存真相。
    await db.delete(stockreturn)
    await db.flush()


async def create_stockreturn(db: AsyncSession, stockout_id: int, quantity: int,
                             return_date_str: str, reason: str | None = None,
                             note: str | None = None,
                             request_id: str | None = None,
                             operator_id: int | None = None) -> dict:
    """创建退货记录（关联所选出货明细）"""
    return_date = _parse_date_preserve_time(return_date_str)
    stockreturn = await create_stockreturn_core(
        db, stockout_id, quantity, return_date, reason, note, request_id,
        operator_id=operator_id,
    )
    await db.flush()
    await cache_mgr.invalidate_stock_and_order()
    schedule_post_commit_invalidation(db, cache_mgr.invalidate_stock_and_order)
    product = await db.get(Product, stockreturn.product_id)
    if product is not None:
        await safe_publish_event(stock_service.publish_stock_event, StockEvent.STOCK_CHANGED, {'product_id': stockreturn.product_id, 'product_name': product.name, 'change_type': '退货', 'quantity': quantity, 'current_stock': product.current_stock}, context="退货事件发布")

    # 领域事件总线：退货创建 → 发布 STOCK_RETURN_CREATED 事件，触发采购计划重算（异步）
    # 退货会减少已出货量，触发采购计划重算；客户/单号来自所选出货单
    # 提交后发布：订阅者（采购计划重算）用独立 session 读库，提交前发布读不到本次变更
    stockout = await db.get(StockOut, stockout_id)
    customer_name = stockout.customer if stockout and stockout.customer else ''
    product_name = product.name if product is not None else ''
    plan_month = stockout.stockout_date.strftime('%Y-%m') if stockout and stockout.stockout_date else ''
    schedule_post_commit_domain_event(db, DomainEvent(
        event_type=DomainEventType.STOCK_RETURN_CREATED,
        domain='stock',
        payload={
            'product_id': stockreturn.product_id,
            'customer': customer_name,
            'product_name': product_name,
            'stockout_no': stockout.stockout_no if stockout else stockreturn.return_no,
            'deleted_quantity': quantity,
            'plan_month': plan_month,
        },
    ))

    logger.info(f'退货添加成功：{stockreturn.return_no}，关联出货ID：{stockout_id}，数量：{quantity}')
    return {'id': stockreturn.id, 'return_no': stockreturn.return_no}


async def cancel_stockreturn(db: AsyncSession, stockreturn_id: int, operator_id: int | None = None) -> None:
    """取消退货记录（回冲库存/订单状态后删除该行）"""
    result = await db.execute(select(StockReturn).where(StockReturn.id == stockreturn_id).with_for_update())
    stockreturn_obj = result.scalar_one_or_none()
    if not stockreturn_obj:
        raise ValueError('退货记录不存在')
    return_no = stockreturn_obj.return_no
    cancelled_quantity = stockreturn_obj.quantity
    product_id = stockreturn_obj.product_id
    stockout_id = stockreturn_obj.stockout_id
    await cancel_stockreturn_core(db, stockreturn_obj, operator_id=operator_id)
    await db.flush()
    await cache_mgr.invalidate_stock_and_order()
    schedule_post_commit_invalidation(db, cache_mgr.invalidate_stock_and_order)
    product = await db.get(Product, product_id)
    if product is not None:
        await safe_publish_event(stock_service.publish_stock_event, StockEvent.STOCK_CHANGED, {'product_id': product_id, 'product_name': product.name, 'change_type': '退货取消', 'quantity': -cancelled_quantity, 'current_stock': product.current_stock}, context="退货取消事件发布")

    # 领域事件总线：退货取消 → 发布 STOCK_RETURN_CANCELLED 事件，触发采购计划重算（异步）
    # 取消退货会恢复已出货量，复用 recalc_plans_after_stockout_delete 逻辑（语义：回滚退货扣减）
    # 按产品退货（stockout_id=NULL）无出货可查，payload 不带出货单号
    # 提交后发布（同 create_stockreturn：订阅者用独立 session 读库）
    stockout = None
    if stockout_id is not None:
        stockout = await db.get(StockOut, stockout_id)
    customer_name = stockout.customer if stockout and stockout.customer else ''
    product_name = product.name if product is not None else ''
    plan_month = stockout.stockout_date.strftime('%Y-%m') if stockout and stockout.stockout_date else ''
    schedule_post_commit_domain_event(db, DomainEvent(
        event_type=DomainEventType.STOCK_RETURN_CANCELLED,
        domain='stock',
        payload={
            'product_id': product_id,
            'customer': customer_name,
            'product_name': product_name,
            'stockout_no': stockout.stockout_no if stockout else return_no,
            'deleted_quantity': cancelled_quantity,
            'plan_month': plan_month,
        },
    ))

    logger.info(f'退货取消成功：{return_no}，数量：{cancelled_quantity}')


async def edit_stockreturn(db: AsyncSession, return_id: int, quantity: int | None,
                           return_date_str: str | None, reason: str | None,
                           note: str | None, operator_id: int | None = None) -> dict:
    """编辑退货记录（单事务内「取消原退货 + 按同一出货明细重建」，原子）。

    退货没有就地更新端点；编辑 = 软取消旧记录（库存对称回冲）后按新值重建一条，
    两步在同一事务内完成（调用方用 db_transaction 包裹）——任一步失败整体回滚，
    不会留下「旧的取消了、新的没建起来」的中间态。取消会先释放旧占用量，
    因此重建时的可退量校验基于释放后的值。新记录带新的 SR 单号。
    """
    result = await db.execute(select(StockReturn).where(StockReturn.id == return_id))
    old = result.scalar_one_or_none()
    if not old:
        raise ValueError('退货记录不存在')
    if old.status != 'active':
        raise ValueError('该退货已取消，无法编辑')
    stockout_id = old.stockout_id
    if stockout_id is None:
        raise ValueError('该退货未关联出货记录，无法编辑')

    new_quantity = quantity if quantity is not None else old.quantity
    if return_date_str:
        new_date_str = return_date_str
    elif old.return_date:
        # timestamptz 读回是 aware UTC：先换算业务时区再取日期，
        # 否则北京时间 00:00–07:59 创建的退货会在每次编辑时倒退一天。
        _rd = old.return_date
        new_date_str = (
            _rd.astimezone(_BUSINESS_TZ) if _rd.tzinfo else _rd
        ).strftime('%Y-%m-%d')
    else:
        new_date_str = business_now().strftime('%Y-%m-%d')
    new_reason = reason if reason is not None else old.reason
    new_note = note if note is not None else old.note

    await cancel_stockreturn(db, return_id, operator_id=operator_id)
    created = await create_stockreturn(
        db, stockout_id, new_quantity, new_date_str, new_reason, new_note,
        request_id=None, operator_id=operator_id,
    )
    logger.info('退货编辑成功：原单 %s 取消，新建 %s', old.return_no, created['return_no'])
    return created


# 底部引入 stock_service 以提供命名空间解析（延迟到调用期，避免循环依赖）
from fastapi_app.services import stock_service
