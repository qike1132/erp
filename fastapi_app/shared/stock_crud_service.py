"""
库存核心业务逻辑（跨框架共享）

统一 Flask 和 FastAPI 的库存 CRUD 逻辑，消除业务规则漂移。
所有函数接受 SQLAlchemy Session 参数，不依赖任何 Web 框架。
函数内部不做 commit/rollback，由调用方控制事务边界。
"""
import logging
import threading
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from fastapi_app.shared.stock_concurrency import get_product_for_update_sync
from fastapi_app.shared_models import InventoryLog, Order, Product, StockIn, StockOut, StockReturn

logger = logging.getLogger(__name__)


import contextlib

from fastapi_app.services import escape_like

# ==================== 编号生成 ====================

class SyncNumberGenerator:
    """同步编号生成器（跨进程安全），与 AsyncNumberGenerator 逻辑一致"""
    _instance = None
    _counters = {}
    _initialized = {}
    _lock = threading.Lock()
    _last_cleanup_date = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    @classmethod
    def _cleanup_old_entries(cls):
        """清理非当日的计数器条目，防止内存泄漏"""
        today_str = datetime.now().strftime('%Y%m%d')
        # 防御性清理：条目过多时强制清理（即使日期相同）
        if cls._last_cleanup_date == today_str and len(cls._counters) < 500:
            return
        expired_keys = [k for k in cls._counters if not k.endswith(today_str)]
        for k in expired_keys:
            cls._counters.pop(k, None)
            cls._initialized.pop(k, None)
        cls._last_cleanup_date = today_str


_sync_number_generator = SyncNumberGenerator()


def generate_number_sync(prefix: str, model, date_field: str, number_field: str, session: Session) -> str:
    """
    同步编号生成器（跨进程安全）

    每次从数据库查询当日最大编号，同时考虑内存计数器，
    确保同进程内连续生成时不会重复。

    Args:
        prefix: 编号前缀 (如 'PO', 'SI', 'SO')
        model: 数据模型类
        date_field: 日期字段名称
        number_field: 编号字段名称
        session: SQLAlchemy 同步会话

    Returns:
        str: 生成的编号,格式为 PREFIX-YYYYMMDD-XXXX
    """
    today = datetime.now()
    date_str = today.strftime('%Y%m%d')

    # DB 查询在锁外执行，减少锁持有时间
    # FOR UPDATE 行锁确保数据库层面的并发安全
    result = session.execute(
        select(model)
        .where(func.date(getattr(model, date_field)) == today.date())
        .order_by(getattr(model, number_field).desc())
        .limit(1)
        .with_for_update()
    )
    record = result.scalar_one_or_none()

    db_max = 0
    if record:
        last_number = getattr(record, number_field)
        with contextlib.suppress(ValueError, IndexError):
            db_max = int(last_number.split('-')[-1])

    with _sync_number_generator._lock:
        _sync_number_generator._cleanup_old_entries()
        current_seq = max(db_max, _sync_number_generator._counters.get(f"{prefix}:{date_str}", 0)) + 1
        _sync_number_generator._counters[f"{prefix}:{date_str}"] = current_seq
        _sync_number_generator._initialized[f"{prefix}:{date_str}"] = True

    return f"{prefix}-{date_str}-{str(current_seq).zfill(4)}"


def generate_order_number_sync(session: Session) -> str:
    """生成订单编号 PO-YYYYMMDD-XXXX"""
    return generate_number_sync('PO', Order, 'order_date', 'order_no', session)


def generate_stockin_number_sync(session: Session) -> str:
    """生成备货编号 SI-YYYYMMDD-XXXX"""
    return generate_number_sync('SI', StockIn, 'stockin_date', 'stockin_no', session)


def generate_stockout_number_sync(session: Session) -> str:
    """生成出货编号 SO-YYYYMMDD-XXXX"""
    return generate_number_sync('SO', StockOut, 'stockout_date', 'stockout_no', session)


# ==================== 可出货量计算 ====================

def calculate_available_shipment_quantity(
    session: Session,
    product_id: int,
    customer: str,
    order_type: str | None = None,
    country: str | None = None,
) -> dict:
    """
    计算指定客户和产品的可出货量

    业务规则：
    1. 出货量严格受限于订单量
    2. 备货量只能通过订单抵扣使用，不能直接出货
    3. 可出货量 = 订单总量 - 已出货量（非抵扣出货）
    4. 当指定 order_type 时，仅计算该类型订单（逻辑隔离）

    Args:
        session: SQLAlchemy 同步会话
        product_id: 产品ID
        customer: 客户名称
        order_type: 订单类型过滤 ('regular'/'custom'，None=全部)
        country: 国家过滤（仅定制订单使用）

    Returns:
        dict: { order_quantity, shipped_quantity, available_quantity,
                regular_available, custom_available, orders }
    """
    where_clause = [Order.product_id == product_id, Order.customer == customer]
    if order_type:
        if order_type in ('regular', 'normal'):
            where_clause.append(Order.order_type.in_(['regular', 'normal']))
        else:
            where_clause.append(Order.order_type == order_type)
            if country:
                where_clause.append(Order.country == country)

    result = session.execute(
        select(Order).where(*where_clause).order_by(Order.order_date.asc())
    )
    orders = result.scalars().all()

    if not orders:
        return {
            'order_quantity': 0,
            'shipped_quantity': 0,
            'available_quantity': 0,
            'regular_available': 0,
            'custom_available': 0,
            'orders': []
        }

    # 单次查询获取所有订单的已出货量（扣除退货后的净出货量），加 FOR UPDATE 行锁
    order_ids = [o.id for o in orders]
    shipped_result = session.execute(
        select(StockOut.order_id, func.sum(StockOut.quantity - StockOut.returned_quantity))
        .where(
            StockOut.order_id.in_(order_ids),
            StockOut.stockin_id.is_(None)
        )
        .group_by(StockOut.order_id)
        .with_for_update()
    )
    shipped_map = dict(shipped_result.all())

    total_order_quantity = 0
    regular_order_quantity = 0
    custom_order_quantity = 0
    regular_shipped = 0
    custom_shipped = 0
    order_details = []

    for order in orders:
        total_order_quantity += order.quantity
        _order_type = order.order_type or 'regular'
        _country = order.country or ''
        non_deduction_shipped = shipped_map.get(order.id, 0)

        if _order_type in ('regular', 'normal'):
            regular_order_quantity += order.quantity
            regular_shipped += non_deduction_shipped
        else:
            custom_order_quantity += order.quantity
            custom_shipped += non_deduction_shipped

        order_details.append({
            'order_id': order.id,
            'order_no': order.order_no,
            'quantity': order.quantity,
            'shipped': non_deduction_shipped,
            'available': order.quantity - non_deduction_shipped,
            'order_type': _order_type,
            'country': _country
        })

    total_shipped = sum(shipped_map.values())
    available_quantity = max(0, total_order_quantity - total_shipped)

    return {
        'order_quantity': total_order_quantity,
        'shipped_quantity': total_shipped,
        'available_quantity': available_quantity,
        'regular_available': max(0, regular_order_quantity - regular_shipped),
        'custom_available': max(0, custom_order_quantity - custom_shipped),
        'orders': order_details
    }


# ==================== 入库 CRUD ====================

def create_stockin(session: Session, product_id: int, quantity: int,
                   customer: str, stockin_date: datetime, note: str,
                   stockin_no: str = None) -> StockIn:
    """
    创建入库记录，同时更新库存和写入日志。
    不做 commit，由调用方控制事务。

    Args:
        session: SQLAlchemy 同步会话
        product_id: 产品ID
        quantity: 入库数量
        customer: 客户名称
        stockin_date: 入库日期
        note: 备注
        stockin_no: 编号（None 则自动生成）

    Returns:
        StockIn: 创建的入库记录
    """
    if quantity <= 0:
        raise ValueError('入库数量必须大于0')

    if not stockin_no:
        stockin_no = generate_stockin_number_sync(session)

    stockin = StockIn(
        stockin_no=stockin_no,
        product_id=product_id,
        quantity=quantity,
        customer=customer,
        stockin_date=stockin_date,
        note=note
    )
    session.add(stockin)
    session.flush()

    product = get_product_for_update_sync(session, product_id)
    product.current_stock += quantity

    log = InventoryLog(
        product_id=product_id,
        change_type='入库',
        change_quantity=quantity,
        related_id=str(stockin.id),
        note=f'入库ID：{stockin.id}'
    )
    session.add(log)
    return stockin


def update_stockin(session: Session, stockin: StockIn, new_quantity: int,
                   customer: str, stockin_date: datetime, note: str) -> StockIn:
    """
    更新入库记录，调整库存差异。
    不做 commit，由调用方控制事务。
    """
    old_quantity = stockin.quantity
    stockin.quantity = new_quantity
    stockin.customer = customer
    stockin.stockin_date = stockin_date
    stockin.note = note

    if new_quantity != old_quantity:
        product = get_product_for_update_sync(session, stockin.product_id)
        product.current_stock += (new_quantity - old_quantity)
        log = InventoryLog(
            product_id=stockin.product_id,
            change_type='入库修改',
            change_quantity=new_quantity - old_quantity,
            related_id=str(stockin.id),
            note=f'入库修改ID：{stockin.id}'
        )
        session.add(log)
    return stockin


def delete_stockin(session: Session, stockin: StockIn) -> None:
    """
    删除入库记录，回退库存。如果有关联出库则拒绝删除。
    不做 commit，由调用方控制事务。
    """
    if stockin.stockin_stockouts:
        raise ValueError('该入库记录已有出库关联，无法删除')

    product = get_product_for_update_sync(session, stockin.product_id)
    if product.current_stock - stockin.quantity < 0:
        raise ValueError(f'删除入库记录将导致库存为负数（产品：{product.name}，当前库存：{product.current_stock}，入库数量：{stockin.quantity}）')
    product.current_stock -= stockin.quantity

    log = InventoryLog(
        product_id=stockin.product_id,
        change_type='入库删除',
        change_quantity=-stockin.quantity,
        related_id=str(stockin.id),
        note=f'入库删除ID：{stockin.id}'
    )
    session.add(log)
    session.delete(stockin)


# ==================== 出库 CRUD ====================

def create_stockout(session: Session, product_id: int, quantity: int,
                    customer: str, stockout_date: datetime, note: str,
                    order_type: str = 'regular',
                    country: str = None) -> list[StockOut]:
    """
    创建出库记录（含 FIFO 订单分配），扣减库存和写入日志。
    不做 commit，由调用方控制事务。

    业务规则：
    - 出货量严格受限于订单量
    - 按订单日期 FIFO 分配到各订单
    - 定制订单必须指定国家

    Args:
        session: SQLAlchemy 同步会话
        product_id: 产品ID
        quantity: 出库数量
        customer: 客户名称
        stockout_date: 出库日期
        note: 备注
        order_type: 订单类型 ('regular'/'custom')
        country: 国家（定制订单必填）

    Returns:
        List[StockOut]: 创建的出库记录列表（FIFO 可能拆分为多条）
    """
    product = get_product_for_update_sync(session, product_id)

    if product.current_stock < quantity:
        raise ValueError('库存不足！')

    if order_type == 'custom' and not country:
        raise ValueError('定制订单必须填写国家名称！')

    # 验证可出货量
    shipment_info = calculate_available_shipment_quantity(
        session, product_id, customer, order_type=order_type, country=country
    )
    if shipment_info['available_quantity'] <= 0:
        raise ValueError('该客户没有可用的订单支持出货！请先创建订单。')

    if quantity > shipment_info['available_quantity']:
        raise ValueError(
            f'出货数量超过可出货量！订单总量：{shipment_info["order_quantity"]}，'
            f'已出货：{shipment_info["shipped_quantity"]}，'
            f'可出货：{shipment_info["available_quantity"]}'
        )

    # FIFO 分配到各订单
    remaining_qty = quantity
    created_stockouts = []
    for order_detail in shipment_info['orders']:
        if remaining_qty <= 0:
            break
        if order_detail['available'] > 0:
            ship_qty = min(remaining_qty, order_detail['available'])
            stockout_no = generate_stockout_number_sync(session)
            stockout = StockOut(
                stockout_no=stockout_no,
                product_id=product_id,
                quantity=ship_qty,
                stockout_date=stockout_date,
                customer=customer,
                order_id=order_detail['order_id'],
                note=note
            )
            session.add(stockout)
            session.flush()
            created_stockouts.append(stockout)
            remaining_qty -= ship_qty

    product.current_stock -= quantity

    log = InventoryLog(
        product_id=product_id,
        change_type='出库',
        change_quantity=-quantity,
        related_id=','.join(str(s.id) for s in created_stockouts) if created_stockouts else '',
        note=f'出库数量：{quantity}'
    )
    session.add(log)
    return created_stockouts


def update_stockout(session: Session, stockout: StockOut, new_quantity: int,
                    customer: str, stockout_date: datetime, note: str) -> StockOut:
    """
    更新出库记录，调整库存差异。
    不做 commit，由调用方控制事务。
    """
    if stockout.stockin_id is not None:
        raise ValueError('订单抵扣的出货记录不能直接编辑！请通过订单管理进行修改。')

    if new_quantity < stockout.returned_quantity:
        raise ValueError(f'出货数量不能小于已退货数量({stockout.returned_quantity})')

    old_quantity = stockout.quantity
    old_net = old_quantity - stockout.returned_quantity

    product = get_product_for_update_sync(session, stockout.product_id)

    if product.current_stock + old_net < new_quantity - stockout.returned_quantity:
        raise ValueError('库存不足！')

    if customer:
        shipment_info = calculate_available_shipment_quantity(
            session, stockout.product_id, customer
        )
        available_with_current = shipment_info['available_quantity'] + old_net
        if new_quantity - stockout.returned_quantity > available_with_current:
            raise ValueError(
                f'出货数量超过可出货量！订单总量：{shipment_info["order_quantity"]}，'
                f'可出货（含当前记录）：{available_with_current}'
            )

    stockout.quantity = new_quantity
    stockout.stockout_date = stockout_date
    stockout.customer = customer
    stockout.note = note

    if new_quantity != old_quantity:
        product.current_stock -= (new_quantity - old_quantity)
        log = InventoryLog(
            product_id=stockout.product_id,
            change_type='出库修改',
            change_quantity=-(new_quantity - old_quantity),
            related_id=str(stockout.id),
            note=f'出库修改ID：{stockout.id}'
        )
        session.add(log)
    return stockout


def delete_stockout(session: Session, stockout: StockOut) -> None:
    """
    删除出库记录，回退库存。如果是抵扣出库或已有退货则拒绝删除。
    不做 commit，由调用方控制事务。
    """
    if stockout.stockin_id is not None:
        raise ValueError('订单抵扣的出货记录不能直接删除！请通过订单管理进行修改。')

    if stockout.returned_quantity > 0:
        raise ValueError('该出货记录已有退货关联，无法删除！请先删除退货记录。')

    product = get_product_for_update_sync(session, stockout.product_id)
    product.current_stock += stockout.quantity

    log = InventoryLog(
        product_id=stockout.product_id,
        change_type='出库删除',
        change_quantity=stockout.quantity,
        related_id=str(stockout.id),
        note=f'出库删除ID：{stockout.id}'
    )
    session.add(log)
    session.delete(stockout)


# ==================== 退货 CRUD ====================

def create_stockreturn(session: Session, stockout_id: int, quantity: int,
                       return_date: datetime, reason: str | None = None,
                       note: str | None = None) -> StockReturn:
    """
    创建退货记录，恢复库存和写入日志。
    不做 commit，由调用方控制事务。
    """
    if quantity <= 0:
        raise ValueError('退货数量必须大于0')

    stockout_result = session.execute(
        select(StockOut).where(StockOut.id == stockout_id).with_for_update()
    )
    stockout = stockout_result.scalar_one_or_none()
    if not stockout:
        raise ValueError('出货记录不存在')

    available_return = stockout.quantity - stockout.returned_quantity
    if quantity > available_return:
        raise ValueError(f'退货数量超过可退数量！出货数量：{stockout.quantity}，已退货：{stockout.returned_quantity}，可退：{available_return}')

    return_no = generate_stockreturn_number_sync(session)
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
    session.add(stockreturn)

    stockout.returned_quantity += quantity

    product = get_product_for_update_sync(session, stockout.product_id)
    product.current_stock += quantity

    log = InventoryLog(
        product_id=stockout.product_id,
        change_type='退货',
        change_quantity=quantity,
        related_id=str(stockreturn.id),
        note=f'退货ID：{stockreturn.id}，关联出货ID：{stockout_id}',
        customer=customer,
    )
    session.add(log)

    if order_id:
        recalc_order_status_after_return(session, order_id)

    session.flush()
    return stockreturn


def delete_stockreturn(session: Session, stockreturn: StockReturn) -> None:
    """
    删除退货记录，扣回库存。
    不做 commit，由调用方控制事务。
    """
    stockout_result = session.execute(
        select(StockOut).where(StockOut.id == stockreturn.stockout_id).with_for_update()
    )
    stockout = stockout_result.scalar_one_or_none()
    if not stockout:
        raise ValueError('关联的出货记录不存在')

    stockout.returned_quantity -= stockreturn.quantity

    product = get_product_for_update_sync(session, stockreturn.product_id)
    product.current_stock -= stockreturn.quantity

    log = InventoryLog(
        product_id=stockreturn.product_id,
        change_type='退货删除',
        change_quantity=-stockreturn.quantity,
        related_id=str(stockreturn.id),
        note=f'退货删除ID：{stockreturn.id}，关联出货ID：{stockout.id}',
        customer=stockreturn.customer,
    )
    session.add(log)

    if stockreturn.order_id:
        recalc_order_status_after_return(session, stockreturn.order_id)

    session.delete(stockreturn)


def recalc_order_status_after_return(session: Session, order_id: int) -> None:
    """
    退货后重算订单状态（派生计算）
    """
    order = session.get(Order, order_id)
    if not order:
        return
    if order.status in (None, '已取消'):
        return

    result = session.execute(
        select(StockOut.stockin_id, func.sum(StockOut.quantity - StockOut.returned_quantity))
        .where(StockOut.order_id == order_id)
        .group_by(StockOut.stockin_id)
    )
    deducted_qty = 0
    shipped_qty = 0
    for stockin_id, qty in result:
        if qty is None:
            continue
        if stockin_id is not None:
            deducted_qty += int(qty)
        else:
            shipped_qty += int(qty)
    deducted_qty = max(0, deducted_qty)
    shipped_qty = max(0, shipped_qty)

    from fastapi_app.shared_models.order import compute_status_from_stockouts
    order.status = compute_status_from_stockouts(order, deducted_qty, shipped_qty)


# ==================== 库存查看 ====================

def get_inventory(session: Session, search_customer: str = '',
                  search_product: str = '') -> dict:
    """
    获取库存数据（按产品+客户维度汇总）

    业务规则（与原 Flask/FastAPI 实现一致）：
    - 备货剩余 = 该客户该产品的入库量 - 已被订单抵扣的量
    - 订单可用 = 该客户该产品的订单总量 - 已出货量（非抵扣）
    - 总库存 = 备货剩余 + 常规订单数量 + 定制订单数量 - 已出货总量

    Args:
        session: SQLAlchemy 同步会话
        search_customer: 客户筛选
        search_product: 产品名称/条码筛选

    Returns:
        dict: { inventory_data, total_order_qty, total_stockin_qty, total_stock, all_countries }
    """
    products_query = (
        select(
            Product.id,
            Product.name,
            Product.barcode,
        )
    )

    if search_product:
        escaped = escape_like(search_product)
        products_query = products_query.where(
            Product.name.like(f'%{escaped}%') | Product.barcode.like(f'%{escaped}%')
        )

    result = session.execute(products_query)
    products = result.all()

    if not products:
        return {
            'inventory_data': [],
            'total_order_qty': 0,
            'total_stockin_qty': 0,
            'total_stock': 0,
            'all_countries': [],
        }

    product_ids = [p.id for p in products]
    product_map = {p.id: p for p in products}

    order_agg = session.execute(
        select(
            Order.product_id,
            Order.customer,
            Order.order_type,
            Order.country,
            func.sum(Order.quantity).label('total_qty'),
        )
        .where(Order.product_id.in_(product_ids), ~Order.is_deleted)
        .group_by(Order.product_id, Order.customer, Order.order_type, Order.country)
    ).all()

    stockin_detail = session.execute(
        select(
            StockIn.id,
            StockIn.product_id,
            StockIn.customer,
            StockIn.quantity,
            func.coalesce(func.sum(StockOut.quantity - StockOut.returned_quantity), 0).label('deducted_qty'),
        )
        .outerjoin(StockOut, StockOut.stockin_id == StockIn.id)
        .where(StockIn.product_id.in_(product_ids))
        .group_by(StockIn.id, StockIn.product_id, StockIn.customer, StockIn.quantity)
    ).all()

    si_remaining = {}
    for r in stockin_detail:
        key = (r.product_id, r.customer or '')
        remaining = r.quantity - r.deducted_qty
        si_remaining[key] = si_remaining.get(key, 0) + remaining

    direct_stockout_agg = session.execute(
        select(
            StockOut.product_id,
            StockOut.customer,
            StockOut.order_id,
            func.sum(StockOut.quantity - StockOut.returned_quantity).label('total_qty'),
        )
        .where(
            StockOut.product_id.in_(product_ids),
            StockOut.stockin_id.is_(None),
        )
        .group_by(StockOut.product_id, StockOut.customer, StockOut.order_id)
    ).all()

    order_type_map = {}
    direct_order_ids = [r.order_id for r in direct_stockout_agg if r.order_id]
    if direct_order_ids:
        order_type_rows = session.execute(
            select(Order.id, Order.order_type).where(Order.id.in_(direct_order_ids))
        ).all()
        order_type_map = {r.id: r.order_type for r in order_type_rows}

    so_by_key = {}
    for r in direct_stockout_agg:
        key = (r.product_id, r.customer or '')
        if key not in so_by_key:
            so_by_key[key] = {'direct': 0, 'regular': 0, 'custom': 0, 'total': 0}
        otype = order_type_map.get(r.order_id, 'regular') if r.order_id else None
        so_by_key[key]['total'] += r.total_qty
        if otype == 'custom':
            so_by_key[key]['custom'] += r.total_qty
        elif otype == 'regular':
            so_by_key[key]['regular'] += r.total_qty
        else:
            so_by_key[key]['direct'] += r.total_qty

    order_by_cust = {}
    for r in order_agg:
        key = (r.product_id, r.customer or '')
        if key not in order_by_cust:
            order_by_cust[key] = {}
        label = r.country if r.order_type == 'custom' and r.country else '常规'
        order_by_cust[key][label] = order_by_cust[key].get(label, 0) + (r.total_qty or 0)

    all_keys = set()
    for k in si_remaining:
        if search_customer and k[1] != search_customer:
            continue
        all_keys.add(k)
    for k in so_by_key:
        if search_customer and k[1] != search_customer:
            continue
        all_keys.add(k)
    for k in order_by_cust:
        if search_customer and k[1] != search_customer:
            continue
        all_keys.add(k)

    inventory_data = []
    total_order_qty = 0
    total_stockin_qty = 0
    total_stock = 0

    for (pid, customer) in all_keys:
        prod = product_map.get(pid)
        if not prod:
            continue

        country_orders = order_by_cust.get((pid, customer), {})
        regular_order_qty = country_orders.get('常规', 0)
        custom_order_qty = sum(v for k, v in country_orders.items() if k != '常规')

        cust_stockin_qty = si_remaining.get((pid, customer), 0)
        so_data = so_by_key.get((pid, customer), {'direct': 0, 'regular': 0, 'custom': 0, 'total': 0})
        cust_stockout_qty = so_data['total']

        direct_shipped = so_data['direct']
        regular_shipped = so_data['regular']
        custom_shipped = so_data['custom']
        remaining_reg = max(0, regular_order_qty - direct_shipped - regular_shipped)
        remaining_cus = max(0, custom_order_qty - custom_shipped)
        total_qty = cust_stockin_qty + remaining_reg + remaining_cus

        has_stockin_record = cust_stockin_qty > 0
        has_order_record = bool(country_orders)
        has_positive_stock = total_qty > 0

        if (has_stockin_record or has_order_record) and has_positive_stock:
            inventory_data.append({
                'customer': customer,
                'product_name': prod.name,
                'product_barcode': prod.barcode or '',
                'order_quantity': remaining_reg if remaining_reg > 0 else '',
                'country_orders': country_orders,
                'stockin_quantity': cust_stockin_qty if cust_stockin_qty > 0 else '',
                'stockout_quantity': cust_stockout_qty if cust_stockout_qty > 0 else '',
                'total_stock': total_qty if total_qty > 0 else '',
            })
            total_stockin_qty += cust_stockin_qty
            total_order_qty += remaining_reg + remaining_cus
            total_stock += total_qty

    all_countries = set()
    for item in inventory_data:
        for k, v in item.get('country_orders', {}).items():
            if k != '常规' and v:
                all_countries.add(k)

    return {
        'inventory_data': inventory_data,
        'total_order_qty': total_order_qty,
        'total_stockin_qty': total_stockin_qty,
        'total_stock': total_stock,
        'all_countries': sorted(all_countries),
    }
