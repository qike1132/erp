"""
报表数据查询服务

接受 SQLAlchemy Session 参数，框架无关。

TODO(multi-sku-order): 本模块多处 SQL 直接引用 Order.product_id/Order.quantity
（JOIN、sum 聚合）及遍历 order.product/order.quantity。多 SKU 模型下这些为首 item
兼容值，完整改造涉及业务语义变更，待后续 spec 改造为 JOIN OrderItem。
当前依赖 Task 3 设置的兼容值。
"""
import logging
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, selectinload

from fastapi_app.shared_models import Order, Product, StockIn, StockOut
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
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """
    获取指定类型报表的所有数据（不分页，用于导出）

    Args:
        session: SQLAlchemy 同步会话
        report_type: 报表类型 (order, stockin, stockout, deduction)
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
            return _get_order_logs(session, customer, product, status, start_date, end_date)
        elif report_type == 'stockin':
            return _get_stockin_logs(session, customer, product, start_date, end_date)
        elif report_type == 'stockout':
            return _get_stockout_logs(session, customer, product, start_date, end_date)
        elif report_type == 'deduction':
            return _get_deduction_logs(session, customer, product, start_date, end_date)
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


def _get_order_logs(session, customer, product, status, start_date, end_date):
    query = select(Order).join(Product).options(
        selectinload(Order.product),
        # Order.order_stockouts 由 StockOut.order 的 backref 在运行时注入
        # （shared_models/stock_out.py:38），mypy 无法静态感知该属性。
        # 改为显式 back_populates 需在 order.py 反向声明 StockOut，会引入
        # 模型层循环导入风险，收益不成比例，故此处作用域化忽略。
        selectinload(Order.order_stockouts),  # type: ignore[attr-defined]
    )
    # 与屏幕口径对齐（report_service.get_order_logs 的 "(o.is_deleted = false OR
    # o.is_deleted IS NULL)"）：软删订单不进导出，否则导出数字会大于页面显示值。
    # 该列可空，用 IS NOT TRUE 同时覆盖 false 与 NULL。
    query = query.where(Order.is_deleted.isnot(True))
    if customer:
        query = query.where(Order.customer.like(f'%{escape_like(customer)}%'))
    query = _apply_product_filter(query, product)
    if status:
        valid_statuses = VALID_ORDER_STATUSES
        if status in valid_statuses:
            query = query.where(Order.status == status)
    query = _apply_date_filters(query, Order.order_date, start_date, end_date)

    stats_query = select(
        func.count(Order.id),
        func.coalesce(func.sum(Order.quantity), 0),
        func.count(Order.id).filter(Order.status == ORDER_STATUS_PENDING_STOCK),
        func.count(Order.id).filter(Order.status == ORDER_STATUS_SHIPPED),
    ).join(Product, Order.product_id == Product.id)
    # 与上方明细查询同口径：统计也排除软删订单，两者才对得上。
    stats_query = stats_query.where(Order.is_deleted.isnot(True))
    if customer:
        stats_query = stats_query.where(Order.customer.like(f'%{escape_like(customer)}%'))
    stats_query = _apply_product_filter(stats_query, product)
    if status and status in VALID_ORDER_STATUSES:
        stats_query = stats_query.where(Order.status == status)
    stats_query = _apply_date_filters(stats_query, Order.order_date, start_date, end_date)
    total, total_quantity, pending_count, completed_count = session.execute(stats_query).one()

    logger.info(f'订单查询结果数: {total}')
    logs: list[dict[str, Any]] = []
    stmt = query.order_by(Order.order_date.desc()).execution_options(yield_per=_YIELD_PER_BATCH)
    for order in session.scalars(stmt):
        if len(logs) >= _MAX_EXPORT_ROWS:
            logger.warning('订单报表导出达到最大行数 %d，已截断', _MAX_EXPORT_ROWS)
            break
        deducted_quantity = sum(so.quantity - so.returned_quantity for so in order.order_stockouts if so.stockin_id) if hasattr(order, 'order_stockouts') and order.order_stockouts else 0
        note = order.note or ''
        if deducted_quantity > 0:
            # TODO(multi-sku-order): order.quantity 在多 SKU 下为首 item 兼容值，抵扣备注需按 OrderItem 维度；待后续 spec 改造。
            deduction_note = f'订单{order.quantity}抵扣备货{deducted_quantity}'
            if note:
                note = f'{deduction_note}，{note}'
            else:
                note = deduction_note
        # TODO(multi-sku-order): order.product.name/order.quantity 在多 SKU 下为首 item 兼容值，报表需按 OrderItem 维度展开；待后续 spec 改造。
        logs.append({
            'id': order.id,
            'order_no': order.order_no,
            'customer': order.customer,
            'product_name': order.product.name,
            'product_barcode': order.product.barcode or '',
            'quantity': order.quantity,
            'status': order.status,
            'order_date': order.order_date.strftime('%Y-%m-%d %H:%M'),
            'note': note,
            'deducted_quantity': deducted_quantity
        })

    stats = {
        'total_count': total,
        'total_quantity': int(total_quantity),
        'pending_count': pending_count,
        'completed_count': completed_count
    }
    logger.info('订单报表数据处理完成')
    return logs, stats


def _get_stockin_logs(session, customer, product, start_date, end_date):
    query = select(StockIn).join(Product).options(
        selectinload(StockIn.product),
        selectinload(StockIn.stockin_stockouts)
    )
    if customer:
        query = query.where(StockIn.customer.like(f'%{escape_like(customer)}%'))
    query = _apply_product_filter(query, product)
    query = _apply_date_filters(query, StockIn.stockin_date, start_date, end_date)

    stats_query = select(
        func.count(StockIn.id),
        func.coalesce(func.sum(StockIn.quantity), 0),
    ).join(Product, StockIn.product_id == Product.id)
    if customer:
        stats_query = stats_query.where(StockIn.customer.like(f'%{escape_like(customer)}%'))
    stats_query = _apply_product_filter(stats_query, product)
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


def _get_stockout_logs(session, customer, product, start_date, end_date):
    # 左连 Order 以便按软删过滤（与屏幕口径对齐：report_service.py 的
    # "(so.order_id IS NULL OR o2.is_deleted = false OR o2.is_deleted IS NULL)"）——
    # 挂到已软删订单上的出货不进导出，否则导出数字大于页面。
    query = select(StockOut).join(Product).outerjoin(
        Order, StockOut.order_id == Order.id
    ).where(
        (StockOut.quantity - StockOut.returned_quantity) > 0,
        StockOut.stockin_id.is_(None),
        or_(StockOut.order_id.is_(None), Order.is_deleted.isnot(True)),
    ).options(
        selectinload(StockOut.product),
        selectinload(StockOut.order)
    )
    if customer:
        query = query.where(StockOut.customer.like(f'%{escape_like(customer)}%'))
    query = _apply_product_filter(query, product)
    query = _apply_date_filters(query, StockOut.stockout_date, start_date, end_date)

    stats_query = select(
        func.count(StockOut.id),
        func.coalesce(func.sum(StockOut.quantity - StockOut.returned_quantity), 0),
    ).join(Product, StockOut.product_id == Product.id).outerjoin(
        Order, StockOut.order_id == Order.id
    ).where(
        (StockOut.quantity - StockOut.returned_quantity) > 0,
        StockOut.stockin_id.is_(None),
        or_(StockOut.order_id.is_(None), Order.is_deleted.isnot(True)),
    )
    if customer:
        stats_query = stats_query.where(StockOut.customer.like(f'%{escape_like(customer)}%'))
    stats_query = _apply_product_filter(stats_query, product)
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
            'customer': so.customer or '',
            'product_name': so.product.name,
            'product_barcode': so.product.barcode or '',
            'quantity': so.quantity - so.returned_quantity,
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


def _get_deduction_logs(session, customer, product, start_date, end_date):
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
