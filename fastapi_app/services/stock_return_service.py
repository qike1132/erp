"""
退货（StockReturn）业务逻辑

包含退货核心操作（*_core）与对外编排函数（create/cancel）。
P1-① 删除语义已由软取消取代：cancel 保留记录（status='cancelled'），
库存/流水/订单状态走与删除完全相同的对称回冲链路。
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
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from fastapi_app.core.cache_invalidation import cache_mgr, schedule_post_commit_invalidation
from fastapi_app.core.domain_events import DomainEvent, DomainEventType
from fastapi_app.core.domain_events import publish_with_retry as publish_domain_event
from fastapi_app.core.exception_handler import safe_publish_event
from fastapi_app.services.notification_service import StockEvent
from fastapi_app.services.numbering import generate_number_async
from fastapi_app.services.stock_common import _parse_date_preserve_time
from fastapi_app.services.stock_event_service import recalc_order_status_after_return
from fastapi_app.shared.stock_concurrency import assert_stock_available, update_stock_with_optimistic_lock
from fastapi_app.shared_models import InventoryLog, Product, StockOut, StockReturn

logger = logging.getLogger(__name__)


async def generate_stockreturn_number(db: AsyncSession) -> str:
    """生成退货编号 SR-YYYYMMDD-XXXX"""
    return await generate_number_async('SR', StockReturn, 'return_no', db)


async def create_stockreturn_core(db: AsyncSession, product_id: int, quantity: int,
                                  return_date: datetime, reason: str | None = None,
                                  note: str | None = None,
                                  customer: str | None = None,
                                  request_id: str | None = None) -> StockReturn:
    """创建退货记录核心逻辑（P1 录入变更：按产品退货，不关联出货单/订单）

    退货 = 收回货物入库的物理事件：选产品 + 数量，库存 +N、流水留痕；
    不指定出货单（stockout_id=NULL）也不影响任何订单状态。数量无上限校验
    （不存在"可退上限"概念，实物为准）。

    request_id：前端每次打开新增弹窗生成的幂等令牌（同一次弹窗内重试视为同一请求）。
    命中即拒，防网络重试/双击造成的重复退货；重新打开弹窗会生成新令牌，不误杀合法的二次退货。
    idem_key 直接存原始令牌（UUID），不与 staging 的 '类型|...' 键空间重叠，无需前缀拼接。
    """
    if quantity <= 0:
        raise ValueError('退货数量必须大于0')

    # 幂等键 = 前端原始 requestId（UUID 字符串）。刻意不做任何拼接/格式化
    # （Mimosa 写入门禁对外部输入构造查询键零容忍），uq_inventory_log_idem 兜底。
    idem_key = request_id or None
    if idem_key:
        dup = (await db.execute(
            select(InventoryLog.id).where(InventoryLog.idem_key == idem_key)
        )).first()
        if dup:
            raise ValueError('请勿重复提交：该请求已登记过退货')

    # 产品行锁（产品不存在时由 get_product_for_update 抛错）；锁序仅 Product 单边
    product = await stock_service.get_product_for_update(db, product_id)

    return_no = await stock_service.generate_stockreturn_number(db)

    stockreturn = StockReturn(
        return_no=return_no,
        return_date=return_date,
        product_id=product_id,
        quantity=quantity,
        customer=customer or None,
        reason=reason,
        note=note,
    )
    db.add(stockreturn)
    await db.flush()

    # 恢复库存（统一走乐观锁写入口，WHERE version=旧值；不直写 current_stock）
    await update_stock_with_optimistic_lock(db, product_id, quantity)

    # 写入库存日志（idem_key 供请求级防重；uq_inventory_log_idem 兜底）
    stock_service.log_inventory_change(db, product_id=product_id, change_type='退货', change_quantity=quantity, related_id=str(stockreturn.id), note=f'退货ID：{stockreturn.id}，产品：{product.name}', customer=customer or None, idem_key=idem_key)

    if idem_key:
        # 并发同 request_id 的竞态兜底：预检（无锁 select）拦不住同时进入的两个请求，
        # 唯一索引在 flush 时抛 IntegrityError——savepoint 内转 400，避免 SQLAlchemyError→500
        async with db.begin_nested():
            try:
                await db.flush()
            except IntegrityError as e:
                raise ValueError('请勿重复提交：该请求已登记过退货') from e
    else:
        await db.flush()
    return stockreturn


async def cancel_stockreturn_core(db: AsyncSession, stockreturn: StockReturn) -> None:
    """取消退货记录核心逻辑（P1-① 软取消：保留记录，库存对称扣回）

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
    # 负库存判定统一走统一入口（P1-2b），文案与改动前逐字一致
    assert_stock_available(
        product.current_stock, -stockreturn.quantity,
        message=f'取消退货将导致库存为负数（当前库存：{product.current_stock}，退货数量：{stockreturn.quantity}）',
    )
    # 扣回库存统一走乐观锁写入口（不直写 current_stock）
    await update_stock_with_optimistic_lock(db, stockreturn.product_id, -stockreturn.quantity)

    # 写入库存日志（取消 = 退货的反向，type 与退货区分便于对账）
    stock_service.log_inventory_change(db, product_id=stockreturn.product_id, change_type='退货取消', change_quantity=-stockreturn.quantity, related_id=str(stockreturn.id), note=f'退货取消ID：{stockreturn.id}', customer=stockreturn.customer)

    # 仅历史关联行有 order_id：按产品退货不重算任何订单
    if stockreturn.order_id:
        await db.flush()
        await recalc_order_status_after_return(db, stockreturn.order_id)

    stockreturn.status = 'cancelled'
    await db.flush()


async def create_stockreturn(db: AsyncSession, product_id: int, quantity: int,
                             return_date_str: str, reason: str | None = None,
                             note: str | None = None,
                             customer: str | None = None,
                             request_id: str | None = None) -> dict:
    """创建退货记录（按产品制，不关联出货单/订单）"""
    return_date = _parse_date_preserve_time(return_date_str)
    stockreturn = await create_stockreturn_core(
        db, product_id, quantity, return_date, reason, note, customer, request_id,
    )
    await db.flush()
    await cache_mgr.invalidate_stock_and_order()
    schedule_post_commit_invalidation(db, cache_mgr.invalidate_stock_and_order)
    product = await db.get(Product, stockreturn.product_id)
    if product is not None:
        await safe_publish_event(stock_service.publish_stock_event, StockEvent.STOCK_CHANGED, {'product_id': stockreturn.product_id, 'product_name': product.name, 'change_type': '退货', 'quantity': quantity, 'current_stock': product.current_stock}, context="退货事件发布")

    # 领域事件总线：退货创建 → 发布 STOCK_RETURN_CREATED 事件，触发采购计划重算（异步）
    # 按产品退货不关联出货/订单，payload 仅携带产品维度信息
    product_name = product.name if product is not None else ''
    await publish_domain_event(DomainEvent(
        event_type=DomainEventType.STOCK_RETURN_CREATED,
        domain='stock',
        payload={
            'product_id': stockreturn.product_id,
            'customer': stockreturn.customer or '',
            'product_name': product_name,
            'return_no': stockreturn.return_no,
            'deleted_quantity': quantity,
        },
    ))

    logger.info(f'退货添加成功：{stockreturn.return_no}，产品ID：{product_id}，数量：{quantity}')
    return {'id': stockreturn.id, 'return_no': stockreturn.return_no}


async def cancel_stockreturn(db: AsyncSession, stockreturn_id: int) -> None:
    """取消退货记录（P1-① 软取消：记录保留，库存/订单状态对称回冲）"""
    result = await db.execute(select(StockReturn).where(StockReturn.id == stockreturn_id).with_for_update())
    stockreturn_obj = result.scalar_one_or_none()
    if not stockreturn_obj:
        raise ValueError('退货记录不存在')
    return_no = stockreturn_obj.return_no
    cancelled_quantity = stockreturn_obj.quantity
    product_id = stockreturn_obj.product_id
    stockout_id = stockreturn_obj.stockout_id
    await cancel_stockreturn_core(db, stockreturn_obj)
    await db.flush()
    await cache_mgr.invalidate_stock_and_order()
    schedule_post_commit_invalidation(db, cache_mgr.invalidate_stock_and_order)
    product = await db.get(Product, product_id)
    if product is not None:
        await safe_publish_event(stock_service.publish_stock_event, StockEvent.STOCK_CHANGED, {'product_id': product_id, 'product_name': product.name, 'change_type': '退货取消', 'quantity': -cancelled_quantity, 'current_stock': product.current_stock}, context="退货取消事件发布")

    # 领域事件总线：退货取消 → 发布 STOCK_RETURN_CANCELLED 事件，触发采购计划重算（异步）
    # 取消退货会恢复已出货量，复用 recalc_plans_after_stockout_delete 逻辑（语义：回滚退货扣减）
    # 按产品退货（stockout_id=NULL）无出货可查，payload 不带出货单号
    stockout = None
    if stockout_id is not None:
        stockout = await db.get(StockOut, stockout_id)
    customer_name = stockout.customer if stockout and stockout.customer else ''
    product_name = product.name if product is not None else ''
    plan_month = stockout.stockout_date.strftime('%Y-%m') if stockout and stockout.stockout_date else ''
    await publish_domain_event(DomainEvent(
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


# 底部引入 stock_service 以提供命名空间解析（延迟到调用期，避免循环依赖）
from fastapi_app.services import stock_service
