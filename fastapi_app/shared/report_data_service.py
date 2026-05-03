"""
报表数据查询服务（跨框架共享）

从 app/routes/report.py 提取，消除 FastAPI 对 Flask 路由层的直接依赖。
接受 SQLAlchemy Session 参数，不依赖 Flask 应用上下文。
"""
import logging
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import or_
from sqlalchemy.orm import Session, joinedload

from fastapi_app.shared_models import Order, Product, StockIn, StockOut

logger = logging.getLogger(__name__)


from fastapi_app.services import escape_like


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
        session: SQLAlchemy 同步会话（Flask db.session 或 SyncSessionLocal()）
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
        logger.error(f'获取报表数据错误: {str(e)}', exc_info=True)
        return [], {}


def _get_order_logs(session, customer, product, status, start_date, end_date):
    query = session.query(Order).join(Product).options(
        joinedload(Order.product),
        joinedload(Order.order_stockouts)
    )
    if customer:
        query = query.filter(Order.customer.like(f'%{escape_like(customer)}%'))
    if product:
        query = query.filter(
            or_(
                Product.name.like(f'%{escape_like(product)}%'),
                Product.barcode.like(f'%{escape_like(product)}%')
            )
        )
    if status:
        valid_statuses = ['待备货', '部分备货', '已备货', '待出货', '已出货', '已取消']
        if status in valid_statuses:
            query = query.filter(Order.status == status)
    if start_date:
        try:
            start = datetime.strptime(start_date, '%Y-%m-%d')
            query = query.filter(Order.order_date >= start)
        except ValueError:
            pass
    if end_date:
        try:
            end = datetime.strptime(end_date, '%Y-%m-%d') + timedelta(days=1)
            query = query.filter(Order.order_date < end)
        except ValueError:
            pass

    total = query.count()
    logger.info(f'订单查询结果数: {total}')
    orders = query.order_by(Order.order_date.desc()).all()

    logs = []
    for order in orders:
        deducted_quantity = sum(so.quantity for so in order.order_stockouts if so.stockin_id) if hasattr(order, 'order_stockouts') and order.order_stockouts else 0
        note = order.note or ''
        if deducted_quantity > 0:
            deduction_note = f'订单{order.quantity}抵扣备货{deducted_quantity}'
            if note:
                note = f'{deduction_note}，{note}'
            else:
                note = deduction_note
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
        'total_quantity': sum(o.quantity for o in orders),
        'pending_count': sum(1 for o in orders if o.status == '待备货'),
        'completed_count': sum(1 for o in orders if o.status == '已出货')
    }
    logger.info('订单报表数据处理完成')
    return logs, stats


def _get_stockin_logs(session, customer, product, start_date, end_date):
    query = session.query(StockIn).join(Product).options(
        joinedload(StockIn.product),
        joinedload(StockIn.stockin_stockouts)
    )
    if customer:
        query = query.filter(StockIn.customer.like(f'%{escape_like(customer)}%'))
    if product:
        query = query.filter(
            or_(
                Product.name.like(f'%{escape_like(product)}%'),
                Product.barcode.like(f'%{escape_like(product)}%')
            )
        )
    if start_date:
        try:
            start = datetime.strptime(start_date, '%Y-%m-%d')
            query = query.filter(StockIn.stockin_date >= start)
        except ValueError:
            pass
    if end_date:
        try:
            end = datetime.strptime(end_date, '%Y-%m-%d') + timedelta(days=1)
            query = query.filter(StockIn.stockin_date < end)
        except ValueError:
            pass

    total = query.count()
    logger.info(f'备货查询结果数: {total}')
    stockins = query.order_by(StockIn.stockin_date.desc()).all()

    logs = []
    total_quantity = 0
    total_remaining = 0
    for stockin in stockins:
        remaining = stockin.quantity - sum(so.quantity for so in stockin.stockin_stockouts) if stockin.stockin_stockouts else stockin.quantity
        total_quantity += stockin.quantity
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
        'total_quantity': total_quantity,
        'total_remaining': total_remaining
    }
    logger.info('备货报表数据处理完成')
    return logs, stats


def _get_stockout_logs(session, customer, product, start_date, end_date):
    query = session.query(StockOut).join(Product).filter(
        StockOut.quantity > 0,
        StockOut.stockin_id.is_(None)
    ).options(
        joinedload(StockOut.product),
        joinedload(StockOut.order)
    )
    if customer:
        query = query.filter(StockOut.customer.like(f'%{escape_like(customer)}%'))
    if product:
        query = query.filter(
            or_(
                Product.name.like(f'%{escape_like(product)}%'),
                Product.barcode.like(f'%{escape_like(product)}%')
            )
        )
    if start_date:
        try:
            start = datetime.strptime(start_date, '%Y-%m-%d')
            query = query.filter(StockOut.stockout_date >= start)
        except ValueError:
            pass
    if end_date:
        try:
            end = datetime.strptime(end_date, '%Y-%m-%d') + timedelta(days=1)
            query = query.filter(StockOut.stockout_date < end)
        except ValueError:
            pass

    total = query.count()
    logger.info(f'出货查询结果数: {total}')
    stockouts = query.order_by(StockOut.stockout_date.desc()).all()

    logs = []
    total_quantity = 0
    for so in stockouts:
        order_no = so.order.order_no if so.order else None
        order_id = so.order.id if so.order else None
        total_quantity += so.quantity
        logs.append({
            'id': so.id,
            'stockout_no': so.stockout_no,
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
        'total_quantity': total_quantity
    }
    logger.info('出货报表数据处理完成')
    return logs, stats


def _get_deduction_logs(session, customer, product, start_date, end_date):
    query = session.query(StockOut).join(Product).filter(StockOut.stockin_id.isnot(None)).options(
        joinedload(StockOut.product),
        joinedload(StockOut.order)
    )
    if customer:
        query = query.filter(StockOut.customer.like(f'%{escape_like(customer)}%'))
    if product:
        query = query.filter(
            or_(
                Product.name.like(f'%{escape_like(product)}%'),
                Product.barcode.like(f'%{escape_like(product)}%')
            )
        )
    if start_date:
        try:
            start = datetime.strptime(start_date, '%Y-%m-%d')
            query = query.filter(StockOut.stockout_date >= start)
        except ValueError:
            pass
    if end_date:
        try:
            end = datetime.strptime(end_date, '%Y-%m-%d') + timedelta(days=1)
            query = query.filter(StockOut.stockout_date < end)
        except ValueError:
            pass

    total = query.count()
    logger.info(f'抵扣查询结果数: {total}')
    stockouts = query.order_by(StockOut.stockout_date.desc()).all()

    logs = []
    total_quantity = 0
    order_ids = set()
    for so in stockouts:
        order_no = None
        order_note = None
        order_id = None
        if so.order:
            order_no = so.order.order_no
            order_note = so.order.note
            order_id = so.order.id
            order_ids.add(so.order.id)
        total_quantity += so.quantity
        logs.append({
            'id': so.id,
            'deduction_time': so.stockout_date.strftime('%Y-%m-%d %H:%M'),
            'customer': so.customer or '',
            'product_name': so.product.name,
            'sku': so.product.barcode or '',
            'quantity': so.quantity,
            'order_no': order_no,
            'order_id': order_id,
            'order_note': order_note or ''
        })

    stats = {
        'total_count': total,
        'total_quantity': total_quantity,
        'total_orders': len(order_ids)
    }
    logger.info('抵扣报表数据处理完成')
    return logs, stats
