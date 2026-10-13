"""
报表数据查询服务

接受 SQLAlchemy Session 参数，框架无关。

多 SKU 订单：``Order.product_id/quantity`` 是「首个 SKU / 全部 SKU 之和」兼容值。
订单流水（``_get_order_logs``）已按 ``order_item`` 展开为一行一个 SKU，产品筛选/
工厂隔离也落到明细；无明细的历史订单回退到兼容列。其余四类流水（备货/出货/抵扣/
退货）的源表本身就是 SKU 粒度（``product_id`` 在主表上），无需展开。
"""
import logging
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, selectinload

from fastapi_app.services.business_time import fmt_business
from fastapi_app.shared_models import Order, OrderItem, Product, StockIn, StockOut, StockReturn
from fastapi_app.shared_models.order import (
    ORDER_STATUS_PENDING_STOCK,
    ORDER_STATUS_SHIPPED,
    VALID_ORDER_STATUSES,
)

logger = logging.getLogger(__name__)


from fastapi_app.core.sanitizer import escape_like

_YIELD_PER_BATCH = 500
_MAX_EXPORT_ROWS = 10000  # 报表导出最大行数，避免内存溢出


def get_all_logs_data(
    session: Session,
    report_type: str,
    customer: str = '',
    product: str = '',
    status: str = '',
    start_date: str = '',
    end_date: str = '',
    factory: str = '',
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """
    获取指定类型报表的所有数据（不分页，用于导出）

    Args:
        session: SQLAlchemy 同步会话
        report_type: 报表类型 (order, stockin, stockout, deduction, return)
        customer: 客户筛选
        product: 产品筛选
        status: 状态筛选（仅订单）
        start_date: 开始日期
        end_date: 结束日期

    Returns:
        (logs, stats) - logs 为记录列表，stats 为统计摘要
    """
    try:
        logger.info(f'开始获取报表数据, 类型: {report_type}')
        customer = customer.strip()[:100]
        product = product.strip()[:100]
        status = status.strip()[:20]

        if report_type == 'order':
            return _get_order_logs(session, customer, product, status, start_date, end_date, factory)
        elif report_type == 'stockin':
            return _get_stockin_logs(session, customer, product, start_date, end_date, factory)
        elif report_type == 'stockout':
            return _get_stockout_logs(session, customer, product, start_date, end_date, factory)
        elif report_type == 'deduction':
            return _get_deduction_logs(session, customer, product, start_date, end_date, factory)
        elif report_type == 'return':
            return _get_return_logs(session, customer, product, start_date, end_date, factory)
        else:
            logger.warning(f'未知报表类型: {report_type}')
            return [], {}

    except (ValueError, TypeError, OSError) as e:
        logger.error(f'获取报表数据错误: {e!s}', exc_info=True)
        return [], {}


def _apply_date_filters(query, date_field, start_date, end_date):
    if start_date:
        try:
            start = datetime.strptime(start_date, '%Y-%m-%d')
            query = query.where(date_field >= start)
        except ValueError:
            # 非法日期参数被忽略时留痕，避免静默过滤失败难以排查
            logger.warning('非法日期参数被忽略: start_date=%r', start_date)
    if end_date:
        try:
            end = datetime.strptime(end_date, '%Y-%m-%d') + timedelta(days=1)
            query = query.where(date_field < end)
        except ValueError:
            logger.warning('非法日期参数被忽略: end_date=%r', end_date)
    return query


def _apply_product_filter(query, product):
    if product:
        query = query.where(
            or_(
                Product.name.like(f'%{escape_like(product)}%'),
                Product.barcode.like(f'%{escape_like(product)}%')
            )
        )
    return query


def _apply_factory_filter(query, factory):
    """工厂隔离：产品维度的 factory（与 order/unified.py 的 Product.factory 过滤同口径）。

    非超管且绑定工厂的用户只看本厂产品的流水；NULL 工厂产品与 unified 的 == 语义
    一致，不出现在任何厂绑定用户的视图里。
    """
    if factory:
        query = query.where(Product.factory == factory)
    return query


def _apply_order_filters(query, customer, product, status, start_date, end_date, factory):
    """订单流水的公共筛选（明细查询与统计查询同源，两者才对得上）。

    工厂条件复用 ``_apply_factory_filter``：调用方已把 ``Product`` 外连接到「该行的
    SKU 产品」（见 ``_get_order_logs``），故条件天然落到明细行 —— 任一 SKU 命中即算
    命中，与屏幕口径一致。产品条件**不走**共享的 ``_apply_product_filter``，理由见下。
    """
    # 与屏幕口径对齐（report_service.get_order_logs 的 "(o.is_deleted = false OR
    # o.is_deleted IS NULL)"）：软删订单不进导出，否则导出数字会大于页面显示值。
    # 该列可空，用 IS NOT TRUE 同时覆盖 false 与 NULL。
    query = query.where(Order.is_deleted.isnot(True))
    if customer:
        query = query.where(Order.customer.like(f'%{escape_like(customer)}%'))
    # 产品筛选与显示同源：显示用 COALESCE(Product.name, OrderItem.product_name)
    # （见 _order_log_row），筛选也必须带上 SKU 快照，否则产品行缺失（被删）的行
    # 「显示得出、按名字搜不到」（左连接下 Product.name 为 NULL，旧写法把它排除）。
    # ⚠️ 不能改共享的 _apply_product_filter —— 备货/出货/抵扣/退货四类流水的查询里
    # 没有 OrderItem 连接，在那里引用会打挂 SQL。
    if product:
        like = f'%{escape_like(product)}%'
        query = query.where(
            or_(
                func.coalesce(Product.name, OrderItem.product_name).like(like),
                func.coalesce(Product.barcode, OrderItem.product_barcode).like(like),
            )
        )
    query = _apply_factory_filter(query, factory)
    if status and status in VALID_ORDER_STATUSES:
        query = query.where(Order.status == status)
    return _apply_date_filters(query, Order.order_date, start_date, end_date)


def _order_log_row(order, item, prod) -> dict[str, Any]:
    """单行「订单 × SKU」报表记录；``item`` 为 None 时回退 ``order`` 兼容列。

    ``prod`` 是该行 SKU 的产品（左连接，可能为 None）；产品名优先取实时产品名
    （与屏幕 ``COALESCE(p.name, oi.product_name)`` 同口径），缺失时回退 SKU 快照。
    """
    if item is not None:
        row_id, qty = item.id, item.quantity
        name = (prod.name if prod is not None else item.product_name) or ''
        barcode = (prod.barcode if prod is not None else item.product_barcode) or ''
    else:
        row_id, qty = order.id, order.quantity
        name = (prod.name if prod is not None else '') or ''
        barcode = (prod.barcode or '') if prod is not None else ''
    return {
        'id': row_id,
        'order_no': order.order_no,
        'customer': order.customer,
        'product_name': name,
        'product_barcode': barcode,
        'quantity': qty,
        'status': order.status,
        'order_date': fmt_business(order.order_date),
    }


def _get_order_logs(session, customer, product, status, start_date, end_date, factory=''):
    # 多 SKU：一行 = 一个 (订单 × SKU)。按 order_item 外连接展开（无明细的历史订单
    # 回退 order 兼容列），产品/工厂筛选也因此落到明细行 —— 与屏幕 get_order_logs
    # 同口径（按某个非首个 SKU 筛选时只出那一行，而非整单全部 SKU）。
    item_product_id = func.coalesce(OrderItem.product_id, Order.product_id)
    item_qty = func.coalesce(OrderItem.quantity, Order.quantity)
    query = (
        select(Order, OrderItem, Product)
        .outerjoin(OrderItem, OrderItem.order_id == Order.id)
        .outerjoin(Product, Product.id == item_product_id)
        # Order.order_stockouts 由 StockOut.order 的 backref 在运行时注入
        # （shared_models/stock_out.py:38），mypy 无法静态感知该属性。
        # 改为显式 back_populates 需在 order.py 反向声明 StockOut，会引入
        # 模型层循环导入风险，收益不成比例，故此处作用域化忽略。
        .options(selectinload(Order.order_stockouts))  # type: ignore[attr-defined]
    )
    query = _apply_order_filters(
        query, customer, product, status, start_date, end_date, factory)

    # 统计与明细同粒度（订单 × SKU）：按 SKU 筛选时 count/sum 才对得上明细行。
    stats_query = (
        select(
            func.count(),
            func.coalesce(func.sum(item_qty), 0),
            func.count().filter(Order.status == ORDER_STATUS_PENDING_STOCK),
            func.count().filter(Order.status == ORDER_STATUS_SHIPPED),
        )
        .select_from(Order)
        .outerjoin(OrderItem, OrderItem.order_id == Order.id)
        .outerjoin(Product, Product.id == item_product_id)
    )
    stats_query = _apply_order_filters(
        stats_query, customer, product, status, start_date, end_date, factory)
    total, total_quantity, pending_count, completed_count = session.execute(stats_query).one()

    logger.info(f'订单查询结果数: {total}')
    logs: list[dict[str, Any]] = []
    stmt = (query.order_by(Order.order_date.desc(), Order.id, OrderItem.id)
            .execution_options(yield_per=_YIELD_PER_BATCH))
    for order, item, prod in session.execute(stmt):
        if len(logs) >= _MAX_EXPORT_ROWS:
            logger.warning('订单报表导出达到最大行数 %d，已截断', _MAX_EXPORT_ROWS)
            break
        deducted_quantity = sum(so.quantity - so.returned_quantity for so in order.order_stockouts if so.stockin_id) if hasattr(order, 'order_stockouts') and order.order_stockouts else 0
        note = order.note or ''
        if deducted_quantity > 0:
            # order.quantity 为全部 SKU 之和，抵扣备注是订单级信息，逐 SKU 行重复展示
            deduction_note = f'订单{order.quantity}抵扣备货{deducted_quantity}'
            note = f'{deduction_note}，{note}' if note else deduction_note
        row = _order_log_row(order, item, prod)
        row['note'] = note
        row['deducted_quantity'] = deducted_quantity
        logs.append(row)

    stats = {
        'total_count': total,
        'total_quantity': int(total_quantity),
        'pending_count': pending_count,
        'completed_count': completed_count
    }
    logger.info('订单报表数据处理完成')
    return logs, stats


def _get_stockin_logs(session, customer, product, start_date, end_date, factory=''):
    query = select(StockIn).join(Product).options(
        selectinload(StockIn.product),
        selectinload(StockIn.stockin_stockouts)
    )
    if customer:
        query = query.where(StockIn.customer.like(f'%{escape_like(customer)}%'))
    query = _apply_product_filter(query, product)
    query = _apply_factory_filter(query, factory)
    query = _apply_date_filters(query, StockIn.stockin_date, start_date, end_date)

    stats_query = select(
        func.count(StockIn.id),
        func.coalesce(func.sum(StockIn.quantity), 0),
    ).join(Product, StockIn.product_id == Product.id)
    if customer:
        stats_query = stats_query.where(StockIn.customer.like(f'%{escape_like(customer)}%'))
    stats_query = _apply_product_filter(stats_query, product)
    stats_query = _apply_factory_filter(stats_query, factory)
    stats_query = _apply_date_filters(stats_query, StockIn.stockin_date, start_date, end_date)
    total, total_quantity = session.execute(stats_query).one()

    logger.info(f'备货查询结果数: {total}')
    logs: list[dict[str, Any]] = []
    total_remaining = 0
    stmt = query.order_by(StockIn.stockin_date.desc()).execution_options(yield_per=_YIELD_PER_BATCH)
    for stockin in session.scalars(stmt):
        if len(logs) >= _MAX_EXPORT_ROWS:
            logger.warning('备货报表导出达到最大行数 %d，已截断', _MAX_EXPORT_ROWS)
            break
        remaining = stockin.quantity - sum(so.quantity - so.returned_quantity for so in stockin.stockin_stockouts) if stockin.stockin_stockouts else stockin.quantity
        total_remaining += remaining
        logs.append({
            'id': stockin.id,
            'stockin_no': stockin.stockin_no,
            # 统一键（2026-10-13）：导出器表头按 record_no 取值，与屏幕侧同源
            'record_no': stockin.stockin_no,
            'customer': stockin.customer,
            'product_name': stockin.product.name,
            'product_barcode': stockin.product.barcode or '',
            'quantity': stockin.quantity,
            'remaining': remaining,
            'stockin_date': stockin.stockin_date.strftime('%Y-%m-%d %H:%M'),
            'note': stockin.note or ''
        })

    stats = {
        'total_count': total,
        'total_quantity': int(total_quantity),
        'total_remaining': total_remaining
    }
    logger.info('备货报表数据处理完成')
    return logs, stats


def _get_stockout_logs(session, customer, product, start_date, end_date, factory=''):
    # 左连 Order 以便按软删过滤（与屏幕口径对齐：report_service.py 的
    # "(so.order_id IS NULL OR o2.is_deleted = false OR o2.is_deleted IS NULL)"）——
    # 挂到已软删订单上的出货不进导出，否则导出数字大于页面。
    # 数量取**出货毛量**（quantity，不扣退货），与屏幕「出货流水」一致（2026-10-08 业务裁定）；
    # 故过滤也用 quantity > 0，已全退的出货单仍进导出。
    query = select(StockOut).join(Product).outerjoin(
        Order, StockOut.order_id == Order.id
    ).where(
        StockOut.quantity > 0,
        StockOut.stockin_id.is_(None),
        or_(StockOut.order_id.is_(None), Order.is_deleted.isnot(True)),
    ).options(
        selectinload(StockOut.product),
        selectinload(StockOut.order)
    )
    if customer:
        query = query.where(StockOut.customer.like(f'%{escape_like(customer)}%'))
    query = _apply_product_filter(query, product)
    query = _apply_factory_filter(query, factory)
    query = _apply_date_filters(query, StockOut.stockout_date, start_date, end_date)

    stats_query = select(
        func.count(StockOut.id),
        func.coalesce(func.sum(StockOut.quantity), 0),
    ).join(Product, StockOut.product_id == Product.id).outerjoin(
        Order, StockOut.order_id == Order.id
    ).where(
        StockOut.quantity > 0,
        StockOut.stockin_id.is_(None),
        or_(StockOut.order_id.is_(None), Order.is_deleted.isnot(True)),
    )
    if customer:
        stats_query = stats_query.where(StockOut.customer.like(f'%{escape_like(customer)}%'))
    stats_query = _apply_product_filter(stats_query, product)
    stats_query = _apply_factory_filter(stats_query, factory)
    stats_query = _apply_date_filters(stats_query, StockOut.stockout_date, start_date, end_date)
    total, total_quantity = session.execute(stats_query).one()

    logger.info(f'出货查询结果数: {total}')
    logs: list[dict[str, Any]] = []
    stmt = query.order_by(StockOut.stockout_date.desc()).execution_options(yield_per=_YIELD_PER_BATCH)
    for so in session.scalars(stmt):
        if len(logs) >= _MAX_EXPORT_ROWS:
            logger.warning('出货报表导出达到最大行数 %d，已截断', _MAX_EXPORT_ROWS)
            break
        order_no = so.order.order_no if so.order else None
        order_id = so.order.id if so.order else None
        logs.append({
            'id': so.id,
            'stockout_no': so.stockout_no,
            # 统一键（2026-10-13）：导出器表头按 record_no 取值
            'record_no': so.stockout_no,
            'customer': so.customer or '',
            'product_name': so.product.name,
            'product_barcode': so.product.barcode or '',
            'quantity': so.quantity,
            'stockout_date': so.stockout_date.strftime('%Y-%m-%d %H:%M'),
            'order_no': order_no,
            'order_id': order_id,
            'note': so.note or ''
        })

    stats = {
        'total_count': total,
        'total_quantity': int(total_quantity)
    }
    logger.info('出货报表数据处理完成')
    return logs, stats


def _get_deduction_logs(session, customer, product, start_date, end_date, factory=''):
    # 左连 Order 以便按软删过滤，与出货导出及屏幕口径一致。
    # 第八轮审计：与 _get_stockout_logs(:245) 对齐 —— 补「净量 > 0」过滤，全退抵扣
    # （quantity == returned_quantity）不再以 0 数量计入导出与 total_count。
    query = select(StockOut).join(Product).outerjoin(
        Order, StockOut.order_id == Order.id
    ).where(
        StockOut.stockin_id.isnot(None),
        or_(StockOut.order_id.is_(None), Order.is_deleted.isnot(True)),
        (StockOut.quantity - StockOut.returned_quantity) > 0,
    ).options(
        selectinload(StockOut.product),
        selectinload(StockOut.order)
    )
    if customer:
        query = query.filter(StockOut.customer.like(f'%{escape_like(customer)}%'))
    query = _apply_product_filter(query, product)
    query = _apply_factory_filter(query, factory)
    query = _apply_date_filters(query, StockOut.stockout_date, start_date, end_date)

    stats_query = select(
        func.count(StockOut.id),
        func.coalesce(func.sum(StockOut.quantity - StockOut.returned_quantity), 0),
        func.count(func.distinct(StockOut.order_id)),
    ).join(Product, StockOut.product_id == Product.id).outerjoin(
        Order, StockOut.order_id == Order.id
    ).where(
        StockOut.stockin_id.isnot(None),
        or_(StockOut.order_id.is_(None), Order.is_deleted.isnot(True)),
        (StockOut.quantity - StockOut.returned_quantity) > 0,
    )
    if customer:
        stats_query = stats_query.where(StockOut.customer.like(f'%{escape_like(customer)}%'))
    stats_query = _apply_product_filter(stats_query, product)
    stats_query = _apply_factory_filter(stats_query, factory)
    stats_query = _apply_date_filters(stats_query, StockOut.stockout_date, start_date, end_date)
    total, total_quantity, total_orders = session.execute(stats_query).one()

    logger.info(f'抵扣查询结果数: {total}')
    logs: list[dict[str, Any]] = []
    stmt = query.order_by(StockOut.stockout_date.desc()).execution_options(yield_per=_YIELD_PER_BATCH)
    for so in session.scalars(stmt):
        if len(logs) >= _MAX_EXPORT_ROWS:
            logger.warning('抵扣报表导出达到最大行数 %d，已截断', _MAX_EXPORT_ROWS)
            break
        order_no = None
        order_note = None
        order_id = None
        if so.order:
            order_no = so.order.order_no
            order_note = so.order.note
            order_id = so.order.id
        logs.append({
            'id': so.id,
            'deduction_time': so.stockout_date.strftime('%Y-%m-%d %H:%M'),
            # 统一键（2026-10-13）：抵扣行原只有 sku 键，导出器读 product_barcode/record_no
            'record_no': so.stockout_no,
            'product_barcode': so.product.barcode or '',
            'customer': so.customer or '',
            'product_name': so.product.name,
            'sku': so.product.barcode or '',
            'quantity': so.quantity - so.returned_quantity,
            'order_no': order_no,
            'order_id': order_id,
            'order_note': order_note or ''
        })

    stats = {
        'total_count': total,
        'total_quantity': int(total_quantity),
        'total_orders': total_orders
    }
    logger.info('抵扣报表数据处理完成')
    return logs, stats


def _get_return_logs(session, customer, product, start_date, end_date, factory=''):
    # 与屏幕口径对齐（report_service.get_return_logs 的 sr.status = 'active'）：
    # 已取消退货的库存已对称扣回，不计入导出，否则导出数字会大于页面显示值。
    query = select(StockReturn).join(Product).where(
        StockReturn.status == 'active',
    ).options(selectinload(StockReturn.product))
    if customer:
        query = query.where(StockReturn.customer.like(f'%{escape_like(customer)}%'))
    query = _apply_product_filter(query, product)
    query = _apply_factory_filter(query, factory)
    query = _apply_date_filters(query, StockReturn.return_date, start_date, end_date)

    stats_query = select(
        func.count(StockReturn.id),
        func.coalesce(func.sum(StockReturn.quantity), 0),
    ).join(Product, StockReturn.product_id == Product.id).where(
        StockReturn.status == 'active',
    )
    if customer:
        stats_query = stats_query.where(StockReturn.customer.like(f'%{escape_like(customer)}%'))
    stats_query = _apply_product_filter(stats_query, product)
    stats_query = _apply_factory_filter(stats_query, factory)
    stats_query = _apply_date_filters(stats_query, StockReturn.return_date, start_date, end_date)
    total, total_quantity = session.execute(stats_query).one()

    logger.info(f'退货查询结果数: {total}')
    logs: list[dict[str, Any]] = []
    stmt = query.order_by(StockReturn.return_date.desc()).execution_options(yield_per=_YIELD_PER_BATCH)
    for sr in session.scalars(stmt):
        if len(logs) >= _MAX_EXPORT_ROWS:
            logger.warning('退货报表导出达到最大行数 %d，已截断', _MAX_EXPORT_ROWS)
            break
        note = '；'.join(x for x in (sr.reason or '', sr.note or '') if x)
        logs.append({
            'id': sr.id,
            'return_no': sr.return_no,
            # 统一键（2026-10-13）：导出器表头按 record_no 取值
            'record_no': sr.return_no,
            'return_date': sr.return_date.strftime('%Y-%m-%d %H:%M') if sr.return_date else '',
            'customer': sr.customer or '',
            'product_name': sr.product.name,
            'product_barcode': sr.product.barcode or '',
            'quantity': sr.quantity,
            'note': note,
        })

    stats = {
        'total_count': total,
        'total_quantity': int(total_quantity),
    }
    logger.info('退货报表数据处理完成')
    return logs, stats
