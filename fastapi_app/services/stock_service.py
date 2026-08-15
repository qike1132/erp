"""
库存管理业务逻辑服务

核心 CRUD 和库存计算已统一至 fastapi_app.shared.stock_crud_service。
本服务负责异步适配层：将同步 shared 函数包装为异步调用，
并处理事件发布等 FastAPI 特有逻辑。
"""
import hashlib
import logging
from datetime import datetime, timezone

from sqlalchemy import and_, func, or_, select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload, selectinload

from fastapi_app.core.cache import cache_result
from fastapi_app.core.cache_invalidation import cache_mgr
from fastapi_app.core.exception_handler import safe_publish_event
from fastapi_app.core.number_generator import generate_number_async
from fastapi_app.core.sanitizer import escape_like
from fastapi_app.services.batch_service import calculate_available_shipment_quantity
from fastapi_app.services.numbering import generate_stockin_number, generate_stockout_number
from fastapi_app.services.notification_service import StockEvent, publish_stock_event
from fastapi_app.shared.stock_concurrency import get_product_for_update
from fastapi_app.core.business_rules import MAX_QUANTITY
from fastapi_app.shared_models import Order, Product, StockIn, StockOut, StockReturn
from fastapi_app.utils import log_inventory_change
# 领域事件总线：出库单创建时发布跨域事件
from fastapi_app.core.domain_events import DomainEvent, DomainEventType, publish_with_retry as publish_domain_event

logger = logging.getLogger(__name__)

MAX_STOCK_QUANTITY = MAX_QUANTITY  # 库存数量上限，超过此值拒绝操作（值统一由 business_rules 管理）

# ---------------------------------------------------------------------------
# SQL 条件片段常量（安全边界说明）
#
# 以下常量均为硬编码 SQL 片段，不包含任何用户输入。用户提供的筛选值
# （客户名、产品ID列表）一律通过 SQLAlchemy 绑定参数 :sc / :pids 传递，
# 不直接拼入 SQL 字符串。将这些片段提取为常量是为了：
#   1. 避免在多处重复书写相同字符串，降低拼写不一致风险；
#   2. 明确标识"此处为受控的静态 SQL 片段"，便于安全审查；
#   3. 防止未来修改时误将动态值拼入条件字符串。
# 任何新增条件片段都必须遵循同一规则：片段本身为字面量，值走绑定参数。
# ---------------------------------------------------------------------------
# 客户筛选条件（值通过 :sc 绑定）
_CUST_CLAUSE = ' AND customer = :sc'
_SI_CUST = ' AND si.customer = :sc'
_SO_CUST = ' AND so.customer = :sc'
_O_CUST = ' AND o.customer = :sc'
# 产品ID筛选条件（值通过 :pids 绑定，pids 为元组）
_PID_CLAUSE = ' AND product_id = ANY(:pids)'
_SI_PID = ' AND si.product_id = ANY(:pids)'
_SO_PID = ' AND so.product_id = ANY(:pids)'
_O_PID = ' AND o.product_id = ANY(:pids)'
_PROD_PID = ' AND product_id = ANY(:pids)'

async def create_stockin_core(db: AsyncSession, product_id: int, quantity: int, customer: str, stockin_date: datetime, note: str, order_type: str = 'regular', country: str | None = None) -> StockIn:
    if quantity <= 0:
        raise ValueError('入库数量必须大于 0')
    if quantity > MAX_STOCK_QUANTITY:
        raise ValueError(f'入库数量不能超过 {MAX_STOCK_QUANTITY}')
    stockin = StockIn(stockin_no=await generate_stockin_number(db), product_id=product_id, quantity=quantity, customer=customer, stockin_date=stockin_date, note=note, order_type=order_type, country=country)
    db.add(stockin)
    product = await get_product_for_update(db, product_id)
    product.current_stock += quantity
    await db.flush()  # 单次 flush：同时写入 StockIn INSERT + Product UPDATE，并填充 stockin.id
    log_inventory_change(db, product_id=product_id, change_type='入库', change_quantity=quantity, related_id=str(stockin.id), note=f'入库ID：{stockin.id}')
    return stockin  # 日志条目由调用方的 flush/commit 写入

async def update_stockin_core(db: AsyncSession, stockin: StockIn, quantity: int, customer: str, stockin_date: datetime, note: str, order_type: str = 'regular', country: str | None = None) -> StockIn:
    result = await db.execute(select(StockIn).where(StockIn.id == stockin.id).with_for_update())
    stockin = result.scalar_one_or_none()
    if not stockin:
        raise ValueError('入库记录不存在')
    old_quantity = stockin.quantity
    stockin.quantity = quantity
    stockin.customer = customer
    stockin.stockin_date = stockin_date
    stockin.note = note
    stockin.order_type = order_type
    stockin.country = country
    if quantity != old_quantity:
        product = await get_product_for_update(db, stockin.product_id)
        product.current_stock += quantity - old_quantity
        log_inventory_change(db, product_id=stockin.product_id, change_type='入库修改', change_quantity=quantity - old_quantity, related_id=str(stockin.id), note=f'入库修改ID：{stockin.id}')
    await db.flush()
    return stockin

async def delete_stockin_core(db: AsyncSession, stockin: StockIn) -> None:
    if stockin.stockin_stockouts:
        raise ValueError('该入库记录已有出库关联，无法删除')
    product = await get_product_for_update(db, stockin.product_id)
    if product.current_stock - stockin.quantity < 0:
        raise ValueError(f'删除入库记录将导致库存为负数（产品：{product.name}，当前库存：{product.current_stock}，入库数量：{stockin.quantity}）')
    product.current_stock -= stockin.quantity
    log_inventory_change(db, product_id=stockin.product_id, change_type='入库删除', change_quantity=-stockin.quantity, related_id=str(stockin.id), note=f'入库删除ID：{stockin.id}')
    await db.delete(stockin)
    await db.flush()

async def create_stockout_core(db: AsyncSession, product_id: int, quantity: int, customer: str, stockout_date: datetime, note: str, order_type: str='regular', country: str | None=None) -> list[StockOut]:
    product = await get_product_for_update(db, product_id)
    if product.current_stock < quantity:
        raise ValueError('库存不足！')
    if order_type == 'custom' and (not country):
        raise ValueError('定制订单必须填写国家名称！')
    shipment_info = await calculate_available_shipment_quantity(db, product_id, customer, order_type=order_type, country=country)
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
            stockout = StockOut(stockout_no=await generate_stockout_number(db), product_id=product_id, quantity=ship_qty, stockout_date=stockout_date, customer=customer, order_id=order_detail['order_id'], note=note)
            db.add(stockout)
            created_stockouts.append(stockout)
            remaining_qty -= ship_qty
        product.current_stock -= quantity
        # 第一次 flush：批量写入所有 StockOut INSERT + Product UPDATE，并填充 stockout.id
        # 原 N 次 flush（N=FIFO订单数）合并为 1 次，减少数据库往返
        await db.flush()
        log_inventory_change(db, product_id=product_id, change_type='出库', change_quantity=-quantity, related_id=','.join(str(stock_out.id) for stock_out in created_stockouts) if created_stockouts else '', note=f'出库数量：{quantity}')
        # 第二次 flush：提前暴露 InventoryLog 写入错误（约束违反等），而非依赖 SAVEPOINT 退出时自动 flush
        # 保留原因：错误早暴露便于定位；移除则错误会延迟到 begin_nested 退出时才触发
        await db.flush()
    return created_stockouts

async def update_stockout_core(db: AsyncSession, stockout: StockOut, new_quantity: int, customer: str, stockout_date: datetime, note: str) -> StockOut:
    if stockout.stockin_id is not None:
        raise ValueError('订单抵扣的出货记录不能直接编辑！请通过订单管理进行修改。')
    if new_quantity < stockout.returned_quantity:
        raise ValueError(f'出货数量不能小于已退货数量({stockout.returned_quantity})')
    old_quantity = stockout.quantity
    old_net = old_quantity - stockout.returned_quantity
    product = await get_product_for_update(db, stockout.product_id)
    if product.current_stock + old_net < new_quantity - stockout.returned_quantity:
        raise ValueError('库存不足！')
    if customer and customer.strip():
        shipment_info = await calculate_available_shipment_quantity(db, stockout.product_id, customer)
        available_with_current = shipment_info['available_quantity'] + old_net
        if new_quantity - stockout.returned_quantity > available_with_current:
            raise ValueError(f"出货数量超过可出货量！订单总量：{shipment_info['order_quantity']}，可出货（含当前记录）：{available_with_current}")
    stockout.quantity = new_quantity
    stockout.stockout_date = stockout_date
    stockout.customer = customer
    stockout.note = note
    if new_quantity != old_quantity:
        product.current_stock -= new_quantity - old_quantity
        log_inventory_change(db, product_id=stockout.product_id, change_type='出库修改', change_quantity=-(new_quantity - old_quantity), related_id=str(stockout.id), note=f'出库修改ID：{stockout.id}')
    await db.flush()
    return stockout

async def delete_stockout_core(db: AsyncSession, stockout: StockOut) -> None:
    if stockout.stockin_id is not None:
        raise ValueError('订单抵扣的出货记录不能直接删除！请通过订单管理进行修改。')
    if stockout.returned_quantity > 0:
        raise ValueError('该出货记录已有退货关联，无法删除！请先删除退货记录。')
    product = await get_product_for_update(db, stockout.product_id)
    product.current_stock += stockout.quantity
    log_inventory_change(db, product_id=stockout.product_id, change_type='出库删除', change_quantity=stockout.quantity, related_id=str(stockout.id), note=f'出库删除ID：{stockout.id}')
    await db.delete(stockout)
    await db.flush()


async def generate_stockreturn_number(db: AsyncSession) -> str:
    """生成退货编号 SR-YYYYMMDD-XXXX"""
    return await generate_number_async('SR', StockReturn, 'return_date', 'return_no', db)


async def create_stockreturn_core(db: AsyncSession, stockout_id: int, quantity: int,
                                  return_date: datetime, reason: str | None = None,
                                  note: str | None = None) -> StockReturn:
    """创建退货记录核心逻辑"""
    if quantity <= 0:
        raise ValueError('退货数量必须大于0')

    stockout_result = await db.execute(select(StockOut).where(StockOut.id == stockout_id).with_for_update())
    stockout = stockout_result.scalar_one_or_none()
    if not stockout:
        raise ValueError('出货记录不存在')
    if stockout.stockin_id is not None:
        raise ValueError('订单抵扣的出货记录不能直接退货！请通过订单管理进行处理。')

    available_return = stockout.quantity - stockout.returned_quantity
    if quantity > available_return:
        raise ValueError(f'退货数量超过可退数量！出货数量：{stockout.quantity}，已退货：{stockout.returned_quantity}，可退：{available_return}')

    return_no = await generate_stockreturn_number(db)
    customer = stockout.customer
    order_id = stockout.order_id

    stockreturn = StockReturn(
        return_no=return_no,
        return_date=return_date,
        product_id=stockout.product_id,
        quantity=quantity,
        customer=customer,
        stockout_id=stockout_id,
        order_id=order_id,
        reason=reason,
        note=note,
    )
    db.add(stockreturn)
    await db.flush()

    # 更新出货记录的累计退货量
    stockout.returned_quantity += quantity

    # 恢复库存
    product = await get_product_for_update(db, stockout.product_id)
    product.current_stock += quantity

    # 写入库存日志
    log_inventory_change(db, product_id=stockout.product_id, change_type='退货', change_quantity=quantity, related_id=str(stockreturn.id), note=f'退货ID：{stockreturn.id}，关联出货ID：{stockout_id}', customer=customer)

    # 重算订单状态（需先flush确保SUM查询读到最新的returned_quantity）
    if order_id:
        await db.flush()
        await recalc_order_status_after_return(db, order_id)

    await db.flush()
    return stockreturn


async def delete_stockreturn_core(db: AsyncSession, stockreturn: StockReturn) -> None:
    """删除退货记录核心逻辑"""
    stockout_result = await db.execute(select(StockOut).where(StockOut.id == stockreturn.stockout_id).with_for_update())
    stockout = stockout_result.scalar_one_or_none()
    if not stockout:
        raise ValueError('关联的出货记录不存在')

    # 回减出货记录的累计退货量
    if stockout.returned_quantity < stockreturn.quantity:
        raise ValueError('退货数量异常：累计退货量小于待删除的退货数量')
    stockout.returned_quantity -= stockreturn.quantity

    # 扣回库存
    product = await get_product_for_update(db, stockreturn.product_id)
    if product.current_stock < stockreturn.quantity:
        raise ValueError(f'删除退货将导致库存为负数（当前库存：{product.current_stock}，退货数量：{stockreturn.quantity}）')
    product.current_stock -= stockreturn.quantity

    # 写入库存日志
    log_inventory_change(db, product_id=stockreturn.product_id, change_type='退货删除', change_quantity=-stockreturn.quantity, related_id=str(stockreturn.id), note=f'退货删除ID：{stockreturn.id}，关联出货ID：{stockout.id}', customer=stockreturn.customer)

    # 重算订单状态（需先flush确保SUM查询读到最新的returned_quantity）
    if stockreturn.order_id:
        await db.flush()
        await recalc_order_status_after_return(db, stockreturn.order_id)

    await db.delete(stockreturn)
    await db.flush()


async def recalc_order_status_after_return(db: AsyncSession, order_id: int) -> dict | None:
    """
    退货后重算订单状态（派生计算）

    根据订单关联的实际出入库数据推导状态，无需手动维护状态流转。
    返回出货完成的订单信息（如状态变更为'已出货'），否则返回 None。
    调用方需在 commit 后自行发布事件。
    """
    from fastapi_app.shared_models import Order
    order_result = await db.execute(select(Order).where(Order.id == order_id).with_for_update())
    order = order_result.scalar_one_or_none()
    if not order:
        return None
    if order.status in (None, '已取消'):
        return None

    old_status = order.status
    from fastapi_app.services.order_utils import compute_order_status_from_db
    order.status = await compute_order_status_from_db(db, order)

    if order.status == '已出货' and old_status != '已出货':
        return {'order_id': order.id, 'order_no': order.order_no, 'customer': order.customer}
    return None

@cache_result(
    key_prefix='stockins:list',
    ttl=30,
    local_ttl=10,
    key_builder=lambda *args, **kwargs: f"pg:{kwargs.get('page',1)}:pp:{kwargs.get('per_page',50)}:c:{kwargs.get('customer','') or ''}:ot:{kwargs.get('order_type','') or ''}:sd:{kwargs.get('start_date','') or ''}:ed:{kwargs.get('end_date','') or ''}",
)
async def get_stockins(db: AsyncSession, page: int=1, per_page: int=50,
                       customer: str | None = None, order_type: str | None = None,
                       start_date: str | None = None, end_date: str | None = None) -> dict:
    """获取入库列表（含关联数据，支持分页和筛选）- SQL子查询优化版"""
    conditions = []
    if customer:
        conditions.append(StockIn.customer.like(f'%{escape_like(customer)}%'))
    if order_type:
        conditions.append(StockIn.order_type == order_type)
    if start_date:
        try:
            from datetime import datetime, timezone
            sd = datetime.strptime(start_date, '%Y-%m-%d').replace(tzinfo=timezone.utc)
            conditions.append(StockIn.stockin_date >= sd)
        except ValueError:
            pass
    if end_date:
        try:
            from datetime import datetime, timezone
            ed = datetime.strptime(end_date, '%Y-%m-%d').replace(hour=23, minute=59, second=59, tzinfo=timezone.utc)
            conditions.append(StockIn.stockin_date <= ed)
        except ValueError:
            pass

    base_where = select(StockIn.id)
    for condition in conditions:
        base_where = base_where.where(condition)

    total = (await db.execute(select(func.count()).select_from(base_where.subquery()))).scalar() or 0
    id_result = await db.execute(
        base_where
        .order_by(StockIn.stockin_date.desc())
        .offset((page - 1) * per_page)
        .limit(per_page)
    )
    page_ids = [row[0] for row in id_result.all()]
    if not page_ids:
        return {'items': [], 'total': total, 'page': page, 'per_page': per_page}
    deducted_sub = (
        select(
            StockOut.stockin_id.label('sid'),
            func.coalesce(func.sum(StockOut.quantity - StockOut.returned_quantity), 0).label('deducted')
        )
        .where(StockOut.stockin_id.isnot(None))
        .group_by(StockOut.stockin_id)
        .subquery()
    )
    result = await db.execute(
        select(StockIn, func.coalesce(deducted_sub.c.deducted, 0).label('deducted'))
        .outerjoin(deducted_sub, StockIn.id == deducted_sub.c.sid)
        .options(joinedload(StockIn.product))
        .where(StockIn.id.in_(page_ids))
        .order_by(StockIn.stockin_date.desc())
    )
    data = []
    for row in result.all():
        stock_in = row.StockIn
        deducted = int(row.deducted) if row.deducted is not None else 0
        data.append({
            'id': stock_in.id, 'stockin_no': stock_in.stockin_no,
            'stockin_date': stock_in.stockin_date.strftime('%Y-%m-%d') if stock_in.stockin_date else '',
            'customer': stock_in.customer,
            'product': {'id': stock_in.product.id, 'name': stock_in.product.name, 'barcode': stock_in.product.barcode or '', 'image': stock_in.product.image or ''} if stock_in.product else None,
            'quantity': stock_in.quantity,
            'order_type': stock_in.order_type or 'regular',
            'country': stock_in.country or '',
            'deducted': deducted,
            'note': stock_in.note or '',
        })
    return {'items': data, 'total': total, 'page': page, 'per_page': per_page}

async def create_stockin(db: AsyncSession, product_id: int, quantity: int, customer: str, stockin_date_str: str, note: str) -> dict:
    """创建入库记录"""
    stockin_date = _parse_date_preserve_time(stockin_date_str)
    stockin = await create_stockin_core(db, product_id, quantity, customer, stockin_date, note)
    await db.flush()
    await cache_mgr.invalidate_stock_and_order()
    product = await db.get(Product, product_id)
    if product is not None:
        await safe_publish_event(publish_stock_event, StockEvent.STOCK_CHANGED, {'product_id': product_id, 'product_name': product.name, 'change_type': '入库', 'quantity': quantity, 'current_stock': product.current_stock}, context="入库事件发布")
    else:
        logger.warning('入库事件发布失败：产品ID %s 不存在', product_id)
    logger.info(f'入库添加成功：{stockin.stockin_no}，客户：{customer}，产品ID：{product_id}，数量：{quantity}')
    return {'id': stockin.id, 'stockin_no': stockin.stockin_no}

async def update_stockin(db: AsyncSession, stockin_id: int, quantity: int, customer: str, stockin_date_str: str, note: str) -> None:
    """更新入库记录"""
    result = await db.execute(select(StockIn).where(StockIn.id == stockin_id).options(selectinload(StockIn.stockin_stockouts)).with_for_update())
    stockin_obj = result.scalar_one_or_none()
    if not stockin_obj:
        raise ValueError('入库记录不存在')
    stockin_date = _parse_date_preserve_time(stockin_date_str, stockin_obj.stockin_date)
    old_quantity = stockin_obj.quantity
    old_stockin_no = stockin_obj.stockin_no
    await update_stockin_core(db, stockin_obj, quantity, customer, stockin_date, note)
    await db.flush()
    await cache_mgr.invalidate_stock_and_order()
    product = await db.get(Product, stockin_obj.product_id)
    if product is not None:
        await safe_publish_event(publish_stock_event, StockEvent.STOCK_CHANGED, {'product_id': stockin_obj.product_id, 'product_name': product.name, 'change_type': '入库编辑', 'quantity': quantity, 'current_stock': product.current_stock}, context="入库编辑事件发布")
    logger.info(f'入库编辑成功：{old_stockin_no}，数量变更：{old_quantity} -> {quantity}')

async def delete_stockin(db: AsyncSession, stockin_id: int) -> None:
    """删除入库记录"""
    result = await db.execute(select(StockIn).where(StockIn.id == stockin_id).options(selectinload(StockIn.stockin_stockouts)).with_for_update())
    stockin_obj = result.scalar_one_or_none()
    if not stockin_obj:
        raise ValueError('入库记录不存在')
    stockin_no = stockin_obj.stockin_no
    await delete_stockin_core(db, stockin_obj)
    await db.flush()
    await cache_mgr.invalidate_stock_and_order()
    product = await db.get(Product, stockin_obj.product_id)
    if product is not None:
        await safe_publish_event(publish_stock_event, StockEvent.STOCK_CHANGED, {'product_id': stockin_obj.product_id, 'product_name': product.name, 'change_type': '入库删除', 'quantity': -stockin_obj.quantity, 'current_stock': product.current_stock}, context="入库删除事件发布")
    logger.info(f'入库删除成功：{stockin_no}，数量：{stockin_obj.quantity}')

@cache_result(
    key_prefix='stockouts:list',
    ttl=30,
    local_ttl=10,
    key_builder=lambda *args, **kwargs: f"pg:{kwargs.get('page',1)}:pp:{kwargs.get('per_page',50)}:c:{kwargs.get('customer','') or ''}:ot:{kwargs.get('order_type','') or ''}:sd:{kwargs.get('start_date','') or ''}:ed:{kwargs.get('end_date','') or ''}",
)
async def get_stockouts(db: AsyncSession, page: int=1, per_page: int=50,
                        customer: str | None = None, order_type: str | None = None,
                        start_date: str | None = None, end_date: str | None = None) -> dict:
    """获取出库列表（仅独立出库，非抵扣，支持分页和筛选）

    筛选维度：customer（模糊匹配）、order_type（需 JOIN Order，regular 含无订单记录）、
    start_date/end_date（按 stockout_date 过滤）。
    """
    from fastapi_app.shared_models import Order

    conditions = [StockOut.stockin_id.is_(None)]
    needs_order_join = False
    if customer:
        conditions.append(StockOut.customer.like(f'%{escape_like(customer)}%'))
    if order_type:
        needs_order_join = True
        # regular 包含无关联订单的出库（前端展示时默认为 regular）；custom 必须有关联定制订单
        if order_type == 'regular':
            conditions.append(or_(StockOut.order_id.is_(None), Order.order_type == 'regular'))
        else:
            conditions.append(Order.order_type == order_type)
    if start_date:
        try:
            sd = datetime.strptime(start_date, '%Y-%m-%d').replace(tzinfo=timezone.utc)
            conditions.append(StockOut.stockout_date >= sd)
        except ValueError:
            pass
    if end_date:
        try:
            ed = datetime.strptime(end_date, '%Y-%m-%d').replace(hour=23, minute=59, second=59, tzinfo=timezone.utc)
            conditions.append(StockOut.stockout_date <= ed)
        except ValueError:
            pass

    # 先用子查询过滤 + 分页取 ID，再按 ID 批量加载关联数据，避免 joinedload 与过滤 JOIN 冲突
    id_query = select(StockOut.id)
    if needs_order_join:
        if order_type == 'regular':
            id_query = id_query.outerjoin(Order)
        else:
            id_query = id_query.join(Order)
    id_query = id_query.where(*conditions)

    total = (await db.execute(select(func.count()).select_from(id_query.subquery()))).scalar() or 0

    id_result = await db.execute(
        id_query.order_by(StockOut.stockout_date.desc()).offset((page - 1) * per_page).limit(per_page)
    )
    page_ids = [row[0] for row in id_result.all()]
    if not page_ids:
        return {'items': [], 'total': total, 'page': page, 'per_page': per_page}

    result = await db.execute(
        select(StockOut)
        .options(joinedload(StockOut.product), joinedload(StockOut.order))
        .where(StockOut.id.in_(page_ids))
        .order_by(StockOut.stockout_date.desc())
    )
    stockouts = result.scalars().unique().all()
    data = []
    for stock_out in stockouts:
        item = {
            'id': stock_out.id,
            'stockout_no': stock_out.stockout_no,
            'stockout_date': stock_out.stockout_date.strftime('%Y-%m-%d') if stock_out.stockout_date else '',
            'customer': stock_out.customer,
            'product_id': stock_out.product_id,
            'product_name': stock_out.product.name if stock_out.product else '',
            'product_image': stock_out.product.image if stock_out.product else '',
            'barcode': stock_out.product.barcode if stock_out.product else '',
            'product': {'id': stock_out.product.id, 'name': stock_out.product.name, 'barcode': stock_out.product.barcode or '', 'image': stock_out.product.image or ''} if stock_out.product else None,
            'quantity': stock_out.quantity,
            'returned_quantity': stock_out.returned_quantity,
            'note': stock_out.note or '',
            # TODO(multi-sku-order): stock_out.order.order_type/country 在多 SKU 下为首 item 兼容值，待后续 spec 改造为按 OrderItem 维度。
            'order_type': stock_out.order.order_type if stock_out.order else 'regular',
            'country': stock_out.order.country if stock_out.order and stock_out.order.country else ''
        }
        data.append(item)
    return {'items': data, 'total': total, 'page': page, 'per_page': per_page}

async def _recalc_shipment_order_statuses(db: AsyncSession, created_stockouts: list[StockOut]) -> list[dict]:
    """重算受影响订单的状态，返回变为'已出货'的订单信息列表"""
    if not created_stockouts:
        return []
    from fastapi_app.services.order_utils import compute_order_status_from_db
    from fastapi_app.shared_models import Order
    affected_order_ids: set[int] = {stock_out.order_id for stock_out in created_stockouts if stock_out.order_id}
    if not affected_order_ids:
        return []
    order_result = await db.execute(select(Order).where(Order.id.in_(affected_order_ids)))
    order_map = {order.id: order for order in order_result.scalars().all()}
    shipment_completed_orders = []
    for oid in affected_order_ids:
        order = order_map.get(oid)
        if not order or order.status == '已出货':
            continue
        old_status = order.status
        new_status = await compute_order_status_from_db(db, order)
        if new_status != old_status:
            order.status = new_status
        if new_status == '已出货' and old_status != '已出货':
            shipment_completed_orders.append({'order_id': order.id, 'order_no': order.order_no, 'customer': order.customer})
    return shipment_completed_orders


async def _publish_shipment_completed_events(shipment_completed_orders: list[dict]) -> None:
    """发布出货完成事件（单个失败不影响主操作）"""
    if not shipment_completed_orders:
        return
    from fastapi_app.services.notification_service import publish_event_with_fcm
    for order_info in shipment_completed_orders:
        try:
            await publish_event_with_fcm(
                StockEvent.SHIPMENT_COMPLETED,
                order_info,
                fcm_title="出货完成",
                fcm_body=f"订单 {order_info['order_no']} 已完成出货",
            )
        except Exception as e:  # defensive: 单个事件发布失败不影响主操作
            logger.warning('出货完成事件发布失败: %s', e)


async def create_stockout(db: AsyncSession, product_id: int, quantity: int, customer: str, stockout_date_str: str, note: str, order_type: str='regular', country: str | None=None) -> dict:
    """创建出库记录"""
    stockout_date = _parse_date_preserve_time(stockout_date_str)
    created_stockouts = await create_stockout_core(db, product_id, quantity, customer, stockout_date, note, order_type, country)
    shipment_completed_orders = await _recalc_shipment_order_statuses(db, created_stockouts)

    await db.flush()
    await cache_mgr.invalidate_stock_and_order()
    product = await db.get(Product, product_id)
    if product is not None:
        await safe_publish_event(publish_stock_event, StockEvent.STOCK_CHANGED, {'product_id': product_id, 'product_name': product.name, 'change_type': '出库', 'quantity': quantity, 'current_stock': product.current_stock}, context="出库事件发布")

    await _publish_shipment_completed_events(shipment_completed_orders)

    # 领域事件总线：出库单创建 → 发布 STOCK_OUT_CREATED 事件，供跨域订阅者消费
    # 采购计划重算与缓存失效由 purchase_plan_service 的事件处理器异步执行，解耦循环依赖
    # publish_with_retry 内部已处理重试与错误日志，无需外层 try/except
    plan_month = stockout_date.strftime('%Y-%m') if stockout_date else ''
    product_name = product.name if product is not None else ''
    await publish_domain_event(DomainEvent(
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

async def update_stockout(db: AsyncSession, stockout_id: int, new_quantity: int, customer: str, stockout_date_str: str, note: str) -> None:
    """更新出库记录"""
    pid_result = await db.execute(select(StockOut.product_id).where(StockOut.id == stockout_id))
    pid_row = pid_result.one_or_none()
    if not pid_row:
        raise ValueError('出库记录不存在')
    await get_product_for_update(db, pid_row[0])
    result = await db.execute(select(StockOut).where(StockOut.id == stockout_id).with_for_update())
    stockout_obj = result.scalar_one_or_none()
    if not stockout_obj:
        raise ValueError('出库记录不存在')
    stockout_date = _parse_date_preserve_time(stockout_date_str)
    old_quantity = stockout_obj.quantity
    old_stockout_no = stockout_obj.stockout_no
    await update_stockout_core(db, stockout_obj, new_quantity, customer, stockout_date, note)
    await db.flush()
    await cache_mgr.invalidate_stock_and_order()
    product = await db.get(Product, stockout_obj.product_id)
    if product is not None:
        await safe_publish_event(publish_stock_event, StockEvent.STOCK_CHANGED, {'product_id': stockout_obj.product_id, 'product_name': product.name, 'change_type': '出库编辑', 'quantity': new_quantity, 'current_stock': product.current_stock}, context="出库编辑事件发布")

    # 领域事件总线：出库单更新 → 发布 STOCK_OUT_UPDATED 事件，触发采购计划缓存失效（异步）
    plan_month = stockout_obj.stockout_date.strftime('%Y-%m') if stockout_obj.stockout_date else ''
    await publish_domain_event(DomainEvent(
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

async def delete_stockout(db: AsyncSession, stockout_id: int) -> None:
    """删除出库记录"""
    result = await db.execute(select(StockOut).where(StockOut.id == stockout_id).with_for_update())
    stockout_obj = result.scalar_one_or_none()
    if not stockout_obj:
        raise ValueError('出库记录不存在')
    stockout_no = stockout_obj.stockout_no
    deleted_quantity = stockout_obj.quantity
    customer_name = stockout_obj.customer or ''
    product_result = await db.execute(select(Product.name).where(Product.id == stockout_obj.product_id))
    product_name_row = product_result.one_or_none()
    product_name = product_name_row[0] if product_name_row else ''
    await delete_stockout_core(db, stockout_obj)
    await db.flush()
    await cache_mgr.invalidate_stock_and_order()
    product = await db.get(Product, stockout_obj.product_id)
    if product is not None:
        await safe_publish_event(publish_stock_event, StockEvent.STOCK_CHANGED, {'product_id': stockout_obj.product_id, 'product_name': product.name, 'change_type': '出库删除', 'quantity': -deleted_quantity, 'current_stock': product.current_stock}, context="出库删除事件发布")

    # 领域事件总线：出库单删除 → 发布 STOCK_OUT_DELETED 事件，触发采购计划重算与缓存失效（异步）
    plan_month = stockout_obj.stockout_date.strftime('%Y-%m') if stockout_obj.stockout_date else ''
    await publish_domain_event(DomainEvent(
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

async def create_stockreturn(db: AsyncSession, stockout_id: int, quantity: int,
                             return_date_str: str, reason: str | None = None,
                             note: str | None = None) -> dict:
    """创建退货记录"""
    return_date = _parse_date_preserve_time(return_date_str)
    stockreturn = await create_stockreturn_core(db, stockout_id, quantity, return_date, reason, note)
    await db.flush()
    await cache_mgr.invalidate_stock_and_order()
    product = await db.get(Product, stockreturn.product_id)
    if product is not None:
        await safe_publish_event(publish_stock_event, StockEvent.STOCK_CHANGED, {'product_id': stockreturn.product_id, 'product_name': product.name, 'change_type': '退货', 'quantity': quantity, 'current_stock': product.current_stock}, context="退货事件发布")

    # 领域事件总线：退货创建 → 发布 STOCK_RETURN_CREATED 事件，触发采购计划重算（异步）
    # 退货会减少已出货量，复用 recalc_plans_after_stockout_delete 逻辑（语义：回滚已分配的出货量）
    stockout = await db.get(StockOut, stockout_id)
    customer_name = stockout.customer if stockout and stockout.customer else ''
    product_name = product.name if product is not None else ''
    plan_month = stockout.stockout_date.strftime('%Y-%m') if stockout and stockout.stockout_date else ''
    await publish_domain_event(DomainEvent(
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

async def delete_stockreturn(db: AsyncSession, stockreturn_id: int) -> None:
    """删除退货记录"""
    result = await db.execute(select(StockReturn).where(StockReturn.id == stockreturn_id).with_for_update())
    stockreturn_obj = result.scalar_one_or_none()
    if not stockreturn_obj:
        raise ValueError('退货记录不存在')
    return_no = stockreturn_obj.return_no
    deleted_quantity = stockreturn_obj.quantity
    product_id = stockreturn_obj.product_id
    stockout_id = stockreturn_obj.stockout_id
    await delete_stockreturn_core(db, stockreturn_obj)
    await db.flush()
    await cache_mgr.invalidate_stock_and_order()
    product = await db.get(Product, product_id)
    if product is not None:
        await safe_publish_event(publish_stock_event, StockEvent.STOCK_CHANGED, {'product_id': product_id, 'product_name': product.name, 'change_type': '退货删除', 'quantity': -deleted_quantity, 'current_stock': product.current_stock}, context="退货删除事件发布")

    # 领域事件总线：退货删除 → 发布 STOCK_RETURN_DELETED 事件，触发采购计划重算（异步）
    # 删除退货会恢复已出货量，复用 recalc_plans_after_stockout_delete 逻辑（语义：回滚退货扣减）
    stockout = await db.get(StockOut, stockout_id)
    customer_name = stockout.customer if stockout and stockout.customer else ''
    product_name = product.name if product is not None else ''
    plan_month = stockout.stockout_date.strftime('%Y-%m') if stockout and stockout.stockout_date else ''
    await publish_domain_event(DomainEvent(
        event_type=DomainEventType.STOCK_RETURN_DELETED,
        domain='stock',
        payload={
            'product_id': product_id,
            'customer': customer_name,
            'product_name': product_name,
            'stockout_no': stockout.stockout_no if stockout else return_no,
            'deleted_quantity': deleted_quantity,
            'plan_month': plan_month,
        },
    ))

    logger.info(f'退货删除成功：{return_no}，数量：{deleted_quantity}')

async def get_stockreturns(db: AsyncSession, stockout_id: int | None = None,
                           page: int = 1, per_page: int = 50) -> dict:
    """获取退货列表（支持按出货ID筛选，支持分页）"""
    # 构建共享过滤条件：stockout_id 为空时不加条件
    # （此前 `== stockout_id if stockout_id else True` 在无筛选时退化为 `== True` 恒假，导致 total 恒为 0）
    conditions = []
    if stockout_id:
        conditions.append(StockReturn.stockout_id == stockout_id)
    total = (await db.execute(select(func.count(StockReturn.id)).where(*conditions))).scalar() or 0
    result = await db.execute(
        select(StockReturn)
        .where(*conditions)
        .options(joinedload(StockReturn.product), joinedload(StockReturn.stockout))
        .order_by(StockReturn.return_date.desc())
        .offset((page - 1) * per_page).limit(per_page)
    )
    returns = result.scalars().unique().all()
    data = []
    for stock_return in returns:
        data.append({
            'id': stock_return.id,
            'return_no': stock_return.return_no,
            'return_date': stock_return.return_date.strftime('%Y-%m-%d') if stock_return.return_date else '',
            'product': {'id': stock_return.product.id, 'name': stock_return.product.name} if stock_return.product else None,
            'quantity': stock_return.quantity,
            'customer': stock_return.customer,
            'stockout_id': stock_return.stockout_id,
            'stockout_no': stock_return.stockout.stockout_no if stock_return.stockout else '',
            'reason': stock_return.reason or '',
            'note': stock_return.note or '',
        })
    return {'items': data, 'total': total, 'page': page, 'per_page': per_page}

@cache_result(key_prefix='inventory', ttl=60, local_ttl=30, key_builder=lambda *args, **kwargs: f"c{kwargs.get('search_customer', '')}:p{kwargs.get('search_product', '')}")
async def get_inventory(db: AsyncSession, search_customer: str='', search_product: str='') -> dict:
    """
    获取库存数据（按产品+客户维度汇总）- SQL聚合优化版
    目标：O(P*C*S) 内存聚合 → SQL GROUP BY，响应时间降低 50-80%
    """
    product_ids = await _resolve_products(db, search_product)
    if product_ids is not None and not product_ids:
        return {'inventory_data': [], 'total_order_qty': 0, 'total_stockin_qty': 0, 'total_stock': 0, 'all_countries': []}
    rows = await _fetch_inventory(db, product_ids, search_customer)
    if not rows:
        return {'inventory_data': [], 'total_order_qty': 0, 'total_stockin_qty': 0, 'total_stock': 0, 'all_countries': []}
    all_countries = set()
    total_stockin_qty = 0
    total_order_qty = 0
    total_stock = 0
    inventory_data = []
    for row in rows:
        customer = row['customer']
        pname = row.get('product_name', '')
        pbarcode = row.get('product_barcode') or ''
        si_qty = int(row.get('stockin_qty') or 0)
        so_dir = int(row.get('direct_stockout_qty') or 0)
        so_reg = int(row.get('regular_stockout_qty') or 0)
        so_cus = int(row.get('custom_stockout_qty') or 0)
        o_reg = int(row.get('regular_order_qty') or 0)
        o_cus = int(row.get('custom_order_qty') or 0)
        has_si = bool(row.get('has_stockin'))
        has_o = bool(row.get('has_order'))
        so_total = so_dir + so_reg + so_cus
        remaining_reg = max(0, o_reg - so_dir - so_reg)
        remaining_cus = max(0, o_cus - so_cus)
        total_qty = si_qty + remaining_reg + remaining_cus
        has_positive = total_qty > 0
        country_data = {}
        raw = row.get('country_data') or ''
        if raw:
            for item in raw.split('|'):
                if ':' in item:
                    country, qty_str = item.split(':', 1)
                    qty = int(qty_str)
                    country_data[country] = qty
                    if country != '常规':
                        all_countries.add(country)
        if (has_si or has_o) and has_positive:
            inventory_data.append({'customer': customer, 'product_name': pname, 'product_barcode': pbarcode, 'order_quantity': remaining_reg if remaining_reg > 0 else '', 'country_orders': country_data, 'stockin_quantity': si_qty if si_qty > 0 else '', 'stockout_quantity': so_total if so_total > 0 else '', 'total_stock': total_qty if total_qty > 0 else ''})
            total_stockin_qty += si_qty
            total_order_qty += remaining_reg + remaining_cus
            total_stock += total_qty
    return {'inventory_data': inventory_data, 'total_order_qty': total_order_qty, 'total_stockin_qty': total_stockin_qty, 'total_stock': total_stock, 'all_countries': sorted(all_countries)}


@cache_result(key_prefix="inventory:paginated", ttl=120, local_ttl=60,
             key_builder=lambda **kwargs: f"{kwargs.get('search_customer','')}-{kwargs.get('search_product','')}-{kwargs.get('country','')}-{kwargs.get('page',1)}-{kwargs.get('per_page',50)}")
async def get_inventory_paginated(db: AsyncSession, search_customer: str = '', search_product: str = '',
                                  country: str = '', page: int = 1, per_page: int = 50) -> dict:
    """
    库存分页查询 - SQL CTE 优化版
    将4次聚合查询合并为单次 CTE 查询，在数据库层面完成合并、过滤和分页，
    避免加载全量数据到 Python 内存。20K+ 条数据时响应时间从秒级降至百毫秒级。
    """
    # 仅在有产品搜索时才加载产品ID列表；无搜索时跳过 ANY(:pids) 条件避免20K元素数组导致全表扫描
    product_ids = await _resolve_products(db, search_product) if search_product else None
    if search_product and not product_ids:
        return _empty_inventory_response(page, per_page)

    params, clauses, pids_param = _build_inventory_filter_params(search_product, search_customer, product_ids)
    cte_sql = _build_inventory_cte_sql(clauses, country)

    params['limit'] = per_page
    params['offset'] = (page - 1) * per_page
    if country:
        params['country'] = country

    # 设置 work_mem 提升大查询性能（避免磁盘溢出）
    await db.execute(text("SET LOCAL work_mem = '64MB'"))
    result = await db.execute(cte_sql, params)
    rows = result.all()

    # 独立查询所有客户列表（不受客户筛选影响，确保客户栏始终显示全部客户）
    all_customers = await _get_all_customers(db, pids_param if search_product else None)

    if not rows:
        return _empty_inventory_response(page, per_page, all_customers=all_customers)

    inventory_data, total_items, sum_stockin, sum_order, sum_stock, all_countries, total_available_stock = \
        _format_inventory_rows(rows)

    return {
        'inventory_data': inventory_data,
        'total_order_qty': sum_order,
        'total_stockin_qty': sum_stockin,
        'total_stock': sum_stock,
        'total_available_stock': total_available_stock,
        'all_countries': all_countries,
        'all_customers': all_customers,
        'total_items': total_items,
        'page': page,
        'per_page': per_page,
    }


def _build_inventory_filter_params(search_product: str, search_customer: str,
                                   product_ids: list[int] | None) -> tuple[dict, dict]:
    """构建库存查询的过滤参数和SQL片段。

    Returns:
        (params, clauses) - params: 查询参数字典; clauses: SQL片段字典
    """
    params: dict = {}
    pid_clause = ''
    pids_param = None
    if search_product and product_ids:
        pids_param = tuple(product_ids)
        params['pids'] = pids_param
        pid_clause = _SI_PID

    si_cust = so_cust = o_cust = cust_clause = ''
    if search_customer:
        params['sc'] = search_customer
        si_cust = _SI_CUST
        so_cust = _SO_CUST
        o_cust = _O_CUST
        cust_clause = _CUST_CLAUSE

    # 各表的产品过滤条件（无搜索时为空字符串，避免 ANY(:pids) 全表扫描）
    si_pid = _SI_PID if search_product else ''
    so_pid = _SO_PID if search_product else ''
    o_pid = _O_PID if search_product else ''
    sub_pid = _PID_CLAUSE if search_product else ''
    prod_pid = _PROD_PID if search_product else ''
    pso_pid = _PID_CLAUSE if search_product else ''

    clauses = {
        'pid_clause': pid_clause, 'si_cust': si_cust, 'so_cust': so_cust,
        'o_cust': o_cust, 'cust_clause': cust_clause,
        'si_pid': si_pid, 'so_pid': so_pid, 'o_pid': o_pid,
        'sub_pid': sub_pid, 'prod_pid': prod_pid, 'pso_pid': pso_pid,
    }
    return params, clauses, pids_param


def _build_inventory_cte_sql(clauses: dict, country: str) -> tuple:
    """构建库存CTE查询SQL。

    Returns:
        (cte_sql, country) - cte_sql: TextClause; country参数由调用方添加
    """
    c = clauses
    # 安全说明：clauses 中所有 SQL 片段均来自模块级常量（_SI_PID/_SO_CUST 等），
    # 不含用户输入；筛选值通过 :pids/:sc 绑定参数传递。重构为完全参数化会
    # 改变 CTE 语义，风险过高，故保留并标注。
    cte_sql = text(f"""
WITH stockin_agg AS (
    SELECT si.product_id, si.customer,
           SUM(si.quantity - COALESCE(sub.consumed, 0)) AS stockin_qty,
           1 AS has_stockin
    FROM stock_in si
    LEFT JOIN (
        SELECT stockin_id, SUM(quantity - returned_quantity) AS consumed
        FROM stock_out WHERE stockin_id IS NOT NULL{c['sub_pid']}
        GROUP BY stockin_id
    ) sub ON sub.stockin_id = si.id
    WHERE 1=1{c['si_pid']}{c['si_cust']}
    GROUP BY si.product_id, si.customer
),
stockout_agg AS (
    SELECT so.product_id, so.customer,
        SUM(CASE WHEN so.order_id IS NULL THEN so.quantity - so.returned_quantity ELSE 0 END) AS direct_stockout_qty,
        SUM(CASE WHEN so.order_id IS NOT NULL AND (o.order_type IS NULL OR o.order_type = 'regular')
            THEN so.quantity - so.returned_quantity ELSE 0 END) AS regular_stockout_qty,
        SUM(CASE WHEN o.order_type = 'custom' THEN so.quantity - so.returned_quantity ELSE 0 END) AS custom_stockout_qty
    FROM stock_out so
    LEFT JOIN "order" o ON so.order_id = o.id
    WHERE so.stockin_id IS NULL{c['so_pid']}{c['so_cust']}
    GROUP BY so.product_id, so.customer
),
order_agg AS (
    SELECT o.product_id, o.customer,
        SUM(CASE WHEN o.order_type IS NULL OR o.order_type = 'regular' THEN o.quantity ELSE 0 END) AS regular_order_qty,
        SUM(CASE WHEN o.order_type = 'custom' THEN o.quantity ELSE 0 END) AS custom_order_qty,
        1 AS has_order
    FROM "order" o
    WHERE 1=1{c['o_pid']}{c['o_cust']}
    GROUP BY o.product_id, o.customer
),
country_agg AS (
    SELECT o.product_id, o.customer,
        COALESCE(o.country, '常规') AS country, SUM(o.quantity) AS qty
    FROM "order" o
    WHERE o.order_type = 'custom'{c['o_pid']}{c['o_cust']}
    GROUP BY o.product_id, o.customer, COALESCE(o.country, '常规')
),
country_stockout_agg AS (
    SELECT o.product_id, o.customer,
        COALESCE(o.country, '常规') AS country,
        SUM(so.quantity - so.returned_quantity) AS shipped_qty
    FROM stock_out so
    JOIN "order" o ON so.order_id = o.id
    WHERE so.stockin_id IS NULL AND o.order_type = 'custom'{c['so_pid']}{c['so_cust']}
    GROUP BY o.product_id, o.customer, COALESCE(o.country, '常规')
),
production_agg AS (
    SELECT product_id, SUM(quantity) AS production_qty
    FROM daily_production_record
    WHERE product_id IS NOT NULL{c['prod_pid']}
    GROUP BY product_id
),
product_stockout_total AS (
    SELECT product_id, SUM(quantity - returned_quantity) AS total_stockout_qty
    FROM stock_out
    WHERE 1=1{c['pso_pid']}
    GROUP BY product_id
),
merged AS (
    SELECT
        COALESCE(si.product_id, so.product_id, od.product_id) AS product_id,
        COALESCE(si.customer, so.customer, od.customer) AS customer,
        COALESCE(si.stockin_qty, 0) AS stockin_qty,
        CASE WHEN si.product_id IS NOT NULL THEN true ELSE false END AS has_stockin,
        COALESCE(so.direct_stockout_qty, 0) AS direct_stockout_qty,
        COALESCE(so.regular_stockout_qty, 0) AS regular_stockout_qty,
        COALESCE(so.custom_stockout_qty, 0) AS custom_stockout_qty,
        COALESCE(od.regular_order_qty, 0) AS regular_order_qty,
        COALESCE(od.custom_order_qty, 0) AS custom_order_qty,
        CASE WHEN od.product_id IS NOT NULL THEN true ELSE false END AS has_order
    FROM stockin_agg si
    FULL OUTER JOIN stockout_agg so ON si.product_id = so.product_id AND si.customer = so.customer
    FULL OUTER JOIN order_agg od
        ON COALESCE(si.product_id, so.product_id) = od.product_id
        AND COALESCE(si.customer, so.customer) = od.customer
),
inventory_calc AS (
    SELECT m.*,
        GREATEST(0, m.regular_order_qty - m.direct_stockout_qty - m.regular_stockout_qty) AS remaining_reg,
        GREATEST(0, m.custom_order_qty - m.custom_stockout_qty) AS remaining_cus,
        m.stockin_qty + GREATEST(0, m.regular_order_qty - m.direct_stockout_qty - m.regular_stockout_qty)
            + GREATEST(0, m.custom_order_qty - m.custom_stockout_qty) AS total_qty
    FROM merged m
),
filtered AS (
    SELECT ic.*, p.name AS product_name, p.barcode AS product_barcode,
        COALESCE(pa.production_qty, 0) AS production_qty,
        COALESCE(pst.total_stockout_qty, 0) AS total_product_stockout,
        COALESCE(pa.production_qty, 0) - COALESCE(pst.total_stockout_qty, 0) AS available_stock
    FROM inventory_calc ic
    JOIN product p ON p.id = ic.product_id
    LEFT JOIN production_agg pa ON pa.product_id = ic.product_id
    LEFT JOIN product_stockout_total pst ON pst.product_id = ic.product_id
    WHERE (ic.has_stockin OR ic.has_order) AND ic.total_qty > 0
    {"AND EXISTS (SELECT 1 FROM country_agg ca WHERE ca.product_id = ic.product_id AND ca.customer = ic.customer AND ca.country = :country)" if country else ""}
),
all_countries_cte AS (
    SELECT STRING_AGG(DISTINCT ca.country, '|') AS countries
    FROM country_agg ca WHERE ca.country != '常规'
)
SELECT f.product_id, f.customer, f.product_name, f.product_barcode,
    f.stockin_qty, f.direct_stockout_qty, f.regular_stockout_qty, f.custom_stockout_qty,
    f.regular_order_qty, f.custom_order_qty, f.remaining_reg, f.remaining_cus, f.total_qty,
    f.production_qty, f.available_stock,
    (SELECT STRING_AGG((ca.country || ':' || GREATEST(0, ca.qty - COALESCE(csa.shipped_qty, 0)))::text, '|')
     FROM country_agg ca
     LEFT JOIN country_stockout_agg csa
       ON csa.product_id = ca.product_id AND csa.customer = ca.customer AND csa.country = ca.country
     WHERE ca.product_id = f.product_id AND ca.customer = f.customer) AS country_data,
    (SELECT countries FROM all_countries_cte) AS all_countries_str,
    COUNT(*) OVER() AS total_count,
    SUM(f.stockin_qty) OVER() AS sum_stockin,
    SUM(f.remaining_reg + f.remaining_cus) OVER() AS sum_order,
    SUM(f.total_qty) OVER() AS sum_stock
FROM filtered f
ORDER BY f.customer, f.product_name
LIMIT :limit OFFSET :offset
""")  # nosec B608 - clauses 为模块级常量，值通过绑定参数传递
    return cte_sql


def _format_inventory_rows(rows) -> tuple[list, int, int, int, int, list[str]]:
    """格式化库存查询结果行。

    Returns:
        (inventory_data, total_items, sum_stockin, sum_order, sum_stock, all_countries)
    """
    first = rows[0]
    total_items = first.total_count
    sum_stockin = int(first.sum_stockin)
    sum_order = int(first.sum_order)
    sum_stock = int(first.sum_stock)
    all_countries = sorted(first.all_countries_str.split('|')) if first.all_countries_str else []

    inventory_data = []
    seen_products: set[int] = set()
    total_available_stock = 0
    for row in rows:
        country_data = _parse_country_data(row.country_data or '')
        so_total = int(row.direct_stockout_qty) + int(row.regular_stockout_qty) + int(row.custom_stockout_qty)
        remaining_reg = int(row.remaining_reg)
        remaining_cus = int(row.remaining_cus)
        production_qty = int(row.production_qty)
        available_stock = int(row.available_stock)

        if row.product_id not in seen_products:
            seen_products.add(row.product_id)
            total_available_stock += available_stock

        inventory_data.append({
            'customer': row.customer,
            'product_name': row.product_name,
            'product_barcode': row.product_barcode or '',
            'order_quantity': remaining_reg if remaining_reg > 0 else '',
            'country_orders': country_data,
            'stockin_quantity': int(row.stockin_qty) if int(row.stockin_qty) > 0 else '',
            'stockout_quantity': so_total if so_total > 0 else '',
            'total_stock': int(row.total_qty) if int(row.total_qty) > 0 else '',
            'production_qty': production_qty if production_qty > 0 else '',
            'available_stock': available_stock if available_stock != 0 else '',
        })

    return inventory_data, total_items, sum_stockin, sum_order, sum_stock, all_countries, total_available_stock


def _empty_inventory_response(page: int = 1, per_page: int = 50, all_countries: list | None = None, all_customers: list | None = None) -> dict:
    """构造空库存响应"""
    return {
        'inventory_data': [],
        'total_order_qty': 0,
        'total_stockin_qty': 0,
        'total_stock': 0,
        'total_available_stock': 0,
        'all_countries': all_countries or [],
        'all_customers': all_customers or [],
        'total_items': 0,
        'page': page,
        'per_page': per_page,
    }


def _parse_country_data(raw: str) -> dict:
    """解析 country_data 字符串为字典"""
    country_data: dict[str, int] = {}
    if not raw:
        return country_data
    for item in raw.split('|'):
        if ':' in item:
            country, qty = item.split(':', 1)
            country_data[country] = int(qty)
    return country_data


async def _get_all_countries(db: AsyncSession, pids: tuple | None, search_customer: str = '') -> list[str]:
    """获取所有定制国家列表"""
    cust_clause = _CUST_CLAUSE if search_customer else ''
    pid_clause = _O_PID if pids else ''
    params: dict = {}
    if pids:
        params['pids'] = pids
    if search_customer:
        params['sc'] = search_customer
    # 安全说明：pid_clause/cust_clause 均为模块级常量（_O_PID/_CUST_CLAUSE），
    # 不含用户输入；筛选值通过 :pids/:sc 绑定参数传递。
    sql = text(f"""
        SELECT DISTINCT COALESCE(o.country, '常规') AS country
        FROM "order" o
        WHERE o.order_type = 'custom'{pid_clause}{cust_clause}
          AND o.country IS NOT NULL AND o.country != '常规'
    """)  # nosec B608 - pid_clause/cust_clause 为模块级常量，值通过绑定参数传递
    result = await db.execute(sql, params)
    return sorted(row[0] for row in result.all())

@cache_result(key_prefix="customers:all", ttl=120, local_ttl=60,
              key_builder=lambda **kwargs: f"pids{hashlib.sha256(str(kwargs.get('pids', '')).encode()).hexdigest()[:16] if kwargs.get('pids') else 'all'}")
async def _get_all_customers(db: AsyncSession, pids: tuple | None) -> list[str]:
    """获取所有客户列表（120s 缓存，客户列表变更频率低）"""
    if pids:
        sql = text("""
            SELECT DISTINCT customer FROM (
                SELECT DISTINCT customer FROM stock_in WHERE product_id = ANY(:pids) AND customer IS NOT NULL
                UNION
                SELECT DISTINCT customer FROM stock_out WHERE product_id = ANY(:pids) AND customer IS NOT NULL
                UNION
                SELECT DISTINCT customer FROM "order" WHERE product_id = ANY(:pids) AND customer IS NOT NULL
            ) sub
        """)
        result = await db.execute(sql, {'pids': pids})
    else:
        sql = text("""
            SELECT DISTINCT customer FROM (
                SELECT DISTINCT customer FROM stock_in WHERE customer IS NOT NULL
                UNION
                SELECT DISTINCT customer FROM stock_out WHERE customer IS NOT NULL
                UNION
                SELECT DISTINCT customer FROM "order" WHERE customer IS NOT NULL
            ) sub
        """)
        result = await db.execute(sql)
    return sorted(row[0] for row in result.all())

async def _resolve_products(db: AsyncSession, search: str) -> list[int] | None:
    """解析产品ID列表。无搜索时返回 None（表示不限制产品），避免全量加载。"""
    if not search:
        return None  # 无搜索时不加载全量产品ID，调用方应跳过 ANY(:pids) 条件
    escaped = escape_like(search)
    result = await db.execute(select(Product.id).where(or_(Product.name.like(f'%{escaped}%', escape='\\'), Product.barcode.like(f'%{escaped}%', escape='\\'))))
    return [row[0] for row in result.all()]

def _build_inventory_query_clauses(pids: list[int] | None, cust: str) -> tuple[dict, str, str, str, str, str, str]:
    """构建库存查询的参数和条件片段（无产品筛选时跳过 ANY(:pids) 避免全表扫描）"""
    params: dict = {}
    si_pid = so_pid = o_pid = ''
    si_cust = so_cust = o_cust = ''
    if pids:
        params['pids'] = tuple(pids)
        si_pid = _SI_PID
        so_pid = _SO_PID
        o_pid = _O_PID
    if cust:
        params['sc'] = cust
        si_cust = _SI_CUST
        so_cust = _SO_CUST
        o_cust = _O_CUST
    return params, si_pid, so_pid, o_pid, si_cust, so_cust, o_cust


def _build_country_data_dict(country_rows: list[dict]) -> dict:
    """将国家聚合行转为 (product_id, customer) -> 'country:qty|...' 映射"""
    cdict = {}
    for row in country_rows:
        key = (row['product_id'], row['customer'])
        entry = f"{row['country']}:{row['qty']}"
        cdict[key] = (cdict.get(key, '') + '|' + entry).lstrip('|')
    return cdict


def _merge_inventory_rows(stockin_rows: list[dict], stockout_rows: list[dict],
                          order_rows: list[dict], country_rows: list[dict],
                          pnames: dict) -> list[dict]:
    """合并四张聚合查询结果为统一库存记录列表"""
    merged = {}
    for row in stockin_rows:
        key = (row['product_id'], row['customer'])
        merged[key] = dict(row)
        for fld in ('direct_stockout_qty', 'regular_stockout_qty', 'custom_stockout_qty', 'regular_order_qty', 'custom_order_qty'):
            merged[key].setdefault(fld, 0)
        merged[key].setdefault('has_order', 0)
        merged[key].setdefault('country_data', '')
    for row in stockout_rows:
        key = (row['product_id'], row['customer'])
        if key not in merged:
            merged[key] = {'stockin_qty': 0, 'has_stockin': 0, 'regular_order_qty': 0, 'custom_order_qty': 0, 'has_order': 0, 'country_data': ''}
        merged[key]['direct_stockout_qty'] = row['direct_stockout_qty']
        merged[key]['regular_stockout_qty'] = row['regular_stockout_qty']
        merged[key]['custom_stockout_qty'] = row['custom_stockout_qty']
    for row in order_rows:
        key = (row['product_id'], row['customer'])
        if key not in merged:
            merged[key] = {'stockin_qty': 0, 'has_stockin': 0, 'direct_stockout_qty': 0, 'regular_stockout_qty': 0, 'custom_stockout_qty': 0, 'country_data': ''}
        merged[key]['regular_order_qty'] = row['regular_order_qty']
        merged[key]['custom_order_qty'] = row['custom_order_qty']
        merged[key]['has_order'] = row['has_order']
    cdict = _build_country_data_dict(country_rows)
    for key in merged:
        merged[key]['country_data'] = cdict.get(key, '')
    result = []
    for key, data in merged.items():
        product_id = key[0]
        data['customer'] = key[1]
        data['product_name'] = pnames.get(product_id, {}).get('name', '')
        data['product_barcode'] = pnames.get(product_id, {}).get('barcode', '')
        result.append(data)
    return result


async def _fetch_inventory(db: AsyncSession, pids: list[int] | None, cust: str='') -> list[dict]:
    """库存聚合查询 - 优化版：无产品筛选时跳过 ANY(:pids) 避免全表扫描"""
    params, si_pid, so_pid, o_pid, si_cust, so_cust, o_cust = _build_inventory_query_clauses(pids, cust)
    # 安全说明：以上条件片段均为模块级常量，不含用户输入；
    # 筛选值通过 :pids/:sc 绑定参数传递。
    stockin_sql = text(f'SELECT si.product_id, si.customer, SUM(si.quantity - COALESCE(sub.consumed, 0)) AS stockin_qty, 1 AS has_stockin FROM stock_in si LEFT JOIN (  SELECT stockin_id, SUM(quantity - returned_quantity) AS consumed   FROM stock_out WHERE stockin_id IS NOT NULL{si_pid}   GROUP BY stockin_id) sub ON sub.stockin_id = si.id WHERE 1=1{si_pid}{si_cust} GROUP BY si.product_id, si.customer')  # nosec B608 — 条件片段为模块级常量，值通过绑定参数传递
    stockout_sql = text(f'SELECT so.product_id, so.customer, SUM(CASE WHEN so.order_id IS NULL THEN so.quantity - so.returned_quantity ELSE 0 END) AS direct_stockout_qty, SUM(CASE WHEN so.order_id IS NOT NULL AND (o.order_type IS NULL OR o.order_type = \'regular\') THEN so.quantity - so.returned_quantity ELSE 0 END) AS regular_stockout_qty, SUM(CASE WHEN o.order_type = \'custom\' THEN so.quantity - so.returned_quantity ELSE 0 END) AS custom_stockout_qty FROM stock_out so LEFT JOIN "order" o ON so.order_id = o.id WHERE so.stockin_id IS NULL{so_pid}{so_cust} GROUP BY so.product_id, so.customer')  # nosec B608 — 条件片段为模块级常量，值通过绑定参数传递
    order_sql = text(f'SELECT o.product_id, o.customer, SUM(CASE WHEN o.order_type IS NULL OR o.order_type = \'regular\' THEN o.quantity ELSE 0 END) AS regular_order_qty, SUM(CASE WHEN o.order_type = \'custom\' THEN o.quantity ELSE 0 END) AS custom_order_qty, 1 AS has_order FROM "order" o WHERE 1=1{o_pid}{o_cust} GROUP BY o.product_id, o.customer')  # nosec B608 — 条件片段为模块级常量，值通过绑定参数传递
    country_sql = text(f'SELECT o.product_id, o.customer, COALESCE(o.country, \'\u5e38\u89c4\') AS country, SUM(o.quantity) AS qty FROM "order" o WHERE o.order_type = \'custom\'{o_pid}{o_cust} GROUP BY o.product_id, o.customer, COALESCE(o.country, \'\u5e38\u89c4\')')  # nosec B608 — 条件片段为模块级常量，值通过绑定参数传递
    stockin_rows = await _run_sql(db, stockin_sql, params)
    stockout_rows = await _run_sql(db, stockout_sql, params)
    order_rows = await _run_sql(db, order_sql, params)
    country_rows = await _run_sql(db, country_sql, params)
    # 收集实际出现的产品ID再查询名称，避免全量加载
    all_pids = set()
    for row in (*stockin_rows, *stockout_rows, *order_rows):
        all_pids.add(row['product_id'])
    pnames = await _get_prod_names(db, list(all_pids)) if all_pids else {}
    return _merge_inventory_rows(stockin_rows, stockout_rows, order_rows, country_rows, pnames)

async def _run_sql(db: AsyncSession, sql, params: dict) -> list[dict]:
    result = await db.execute(sql, params)
    cols = list(result.keys())
    return [dict(zip(cols, row, strict=False)) for row in result.all()]

async def _get_prod_names(db: AsyncSession, pids: list[int]) -> dict:
    result = await db.execute(select(Product.id, Product.name, Product.barcode).where(Product.id.in_(pids)))
    return {row[0]: {'name': row[1], 'barcode': row[2] or ''} for row in result.all()}

def _parse_date_preserve_time(date_str: str, old_time: datetime | None=None) -> datetime:
    """解析入库日期（保留原始时间部分）"""
    try:
        base = datetime.strptime(date_str, '%Y-%m-%d')
    except ValueError:
        raise ValueError('日期格式不正确！') from None
    now = datetime.now(timezone.utc)
    if old_time and (old_time.hour != 0 or old_time.minute != 0 or old_time.second != 0):
        return datetime(base.year, base.month, base.day, old_time.hour, old_time.minute, old_time.second)
    else:
        return datetime(base.year, base.month, base.day, now.hour, now.minute, now.second)

async def batch_create_stockins(db: AsyncSession, stockins_data: list) -> dict:
    """批量创建入库记录"""
    validated = []
    errors_map = {}
    for idx, item in enumerate(stockins_data):
        product_id = item.get('product_id')
        customer = str(item.get('customer', '')).strip()
        quantity = item.get('quantity', 0)
        if not all([product_id, customer, quantity]):
            errors_map[idx] = '缺少必填字段或数量无效'
            continue
        if int(quantity) <= 0:
            errors_map[idx] = '入库数量必须大于0'
            continue
        validated.append((idx, item))
    results = [None] * len(stockins_data)
    for idx, err in errors_map.items():
        results[idx] = {'success': False, 'error': err, 'id': stockins_data[idx].get('id', '未知')}
    if validated:
        for orig_idx, item in validated:
            product_id = item.get('product_id')
            customer = str(item.get('customer', '')).strip()
            quantity = int(item.get('quantity', 0))
            note = item.get('note', '')
            order_type = item.get('order_type', 'regular') or 'regular'
            country = item.get('country') or None
            stockin_date_str = item.get('stockin_date') or ''
            stockin_date = _parse_date_preserve_time(stockin_date_str) if stockin_date_str else datetime.now(timezone.utc).replace(tzinfo=None)  # naive UTC: DB列类型为 TIMESTAMP WITHOUT TIME ZONE
            try:
                async with db.begin_nested():
                    stockin = await create_stockin_core(db, product_id, quantity, customer, stockin_date, note, order_type, country)
                results[orig_idx] = {'success': True, 'stockin_no': stockin.stockin_no, 'id': stockin.id}
            except ValueError as e:
                results[orig_idx] = {'success': False, 'error': str(e), 'id': item.get('id', '未知')}
            except (TypeError, OSError) as e:
                logger.error(f'批量入库单项失败: {e}', exc_info=True)
                results[orig_idx] = {'success': False, 'error': str(e) or '入库处理失败，请稍后重试', 'id': item.get('id', '未知')}
        await db.flush()
    return {'success': True, 'results': results}

def _validate_stockout_batch(stockouts_data: list) -> tuple[list, dict]:
    """校验批量出库数据，返回 (有效项 (idx, item) 列表, 错误映射)"""
    validated = []
    errors_map = {}
    for idx, item in enumerate(stockouts_data):
        product_id = item.get('product_id')
        customer = str(item.get('customer', '')).strip()
        quantity = item.get('quantity', 0)
        order_type = item.get('order_type', 'regular') or 'regular'
        country = item.get('country', '') or ''
        if not all([product_id, quantity]):
            errors_map[idx] = '缺少必填字段'
            continue
        if not customer:
            errors_map[idx] = '出货必须选择客户'
            continue
        if order_type == 'custom' and (not country):
            errors_map[idx] = '定制订单必须填写国家名称'
            continue
        if int(quantity) <= 0:
            errors_map[idx] = '出货数量必须大于0'
            continue
        validated.append((idx, item))
    return validated, errors_map


async def _create_stockout_records(db: AsyncSession, product_id: int, customer: str,
                                   note: str, stockout_date_str: str, quantity: int,
                                   orders: list) -> list[StockOut]:
    """按 FIFO 分配订单，创建出库记录"""
    remaining_qty = quantity
    created_stockouts: list[StockOut] = []
    for order_detail in orders:
        if remaining_qty <= 0:
            break
        if order_detail['available'] <= 0:
            continue
        ship_qty = min(remaining_qty, order_detail['available'])
        stockout_no = await generate_stockout_number(db)
        stockout = StockOut(
            stockout_no=stockout_no, product_id=product_id, quantity=ship_qty,
            stockout_date=(_parse_date_preserve_time(stockout_date_str).replace(tzinfo=timezone.utc)),
            customer=customer, order_id=order_detail['order_id'], note=note
        )
        db.add(stockout)
        created_stockouts.append(stockout)
        remaining_qty -= ship_qty
    # 单次 flush：批量写入所有 StockOut INSERT 并填充 id，供调用方构建 related_id
    # 原 N 次 flush（N=FIFO订单数）合并为 1 次
    if created_stockouts:
        await db.flush()
    return created_stockouts


async def _process_single_stockout(db: AsyncSession, item: dict) -> dict:
    """处理单条出库记录的创建（含库存校验、订单分配、库存扣减）"""
    product_id = item.get('product_id')
    customer = str(item.get('customer', '')).strip()
    quantity = int(item.get('quantity', 0))
    order_type = item.get('order_type', 'regular') or 'regular'
    country = item.get('country', '') or None
    note = item.get('note', '')
    stockout_date_str = item.get('stockout_date') or ''
    item_id = item.get('id', '未知')
    try:
        product = await get_product_for_update(db, product_id)
        if product.current_stock < quantity:
            return {'success': False, 'error': f'库存不足，当前库存: {product.current_stock}', 'id': item_id}

        shipment_info = await calculate_available_shipment_quantity(db, product_id, customer, order_type=order_type, country=country)
        if shipment_info['available_quantity'] <= 0:
            return {'success': False, 'error': '该客户没有可用的订单支持出货！请先创建订单。', 'id': item_id}
        if quantity > shipment_info['available_quantity']:
            return {'success': False, 'error': f"出货数量超过可出货量！订单总量：{shipment_info['order_quantity']}，已出货：{shipment_info['shipped_quantity']}，可出货：{shipment_info['available_quantity']}", 'id': item_id}

        created_stockouts = await _create_stockout_records(db, product_id, customer, note, stockout_date_str, quantity, shipment_info['orders'])
        product.current_stock -= quantity
        log_inventory_change(db, product_id=product_id, change_type='出库', change_quantity=-quantity, related_id=','.join(str(stockout.id) for stockout in created_stockouts) if created_stockouts else '', note=f'出库数量：{quantity}')
        await db.flush()

        stockout_nos = [stockout.stockout_no for stockout in created_stockouts] if created_stockouts else []
        return {'success': True, 'stockout_no': stockout_nos[0] if stockout_nos else '', 'id': item_id}
    except ValueError as e:
        return {'success': False, 'error': str(e), 'id': item_id}
    except (TypeError, OSError) as e:
        logger.error(f'批量出库单项失败: {e}', exc_info=True)
        return {'success': False, 'error': str(e) or '出库处理失败，请稍后重试', 'id': item_id}


async def batch_create_stockouts(db: AsyncSession, stockouts_data: list) -> dict:
    """批量创建出库记录（自包含，不调用 create_stockout_core，无嵌套事务）"""
    validated, errors_map = _validate_stockout_batch(stockouts_data)
    results = [None] * len(stockouts_data)
    for idx, err in errors_map.items():
        results[idx] = {'success': False, 'error': err, 'id': stockouts_data[idx].get('id', '未知')}
    for orig_idx, item in validated:
        results[orig_idx] = await _process_single_stockout(db, item)
    all_success = all(result is not None and result.get('success') for result in results)
    return {'success': all_success, 'results': results}


async def get_stock_overview_stats(db: AsyncSession) -> dict:
    """库存统计聚合（自 stock.py 端点下沉）：订单数量（常规+定制）与备货数量"""
    # TODO(multi-sku-order): 此处按 Order.order_type 分组 sum(Order.quantity) 在多 SKU 下结果错误
    # （order_type 为首 item 兼容值，quantity 为 sum of items），属 A 类统计待改造为 JOIN OrderItem。
    order_regular = int((await db.execute(
        select(func.coalesce(func.sum(Order.quantity), 0)).where(
            and_(Order.order_type == 'regular', Order.is_deleted.isnot(True)))
    )).scalar() or 0)

    order_custom = int((await db.execute(
        select(func.coalesce(func.sum(Order.quantity), 0)).where(
            and_(Order.order_type == 'custom', Order.is_deleted.isnot(True)))
    )).scalar() or 0)

    stockin_quantity = int((await db.execute(
        select(func.coalesce(func.sum(StockIn.quantity), 0))
    )).scalar() or 0)

    return {
        'order_quantity': order_regular + order_custom,
        'order_regular_quantity': order_regular,
        'order_custom_quantity': order_custom,
        'stockin_quantity': stockin_quantity,
    }
