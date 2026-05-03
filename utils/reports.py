"""
增强报表功能
提供订单、备货、出货的详细报表 (FastAPI 兼容版本)
"""
from datetime import datetime, timedelta
from typing import Any

from fastapi_app.core.database import SyncSessionLocal
from fastapi_app.shared_models import Order, StockIn, StockOut


class ReportGenerator:
    """报表生成器"""

    def __init__(self):
        pass

    # ==================== 订单报表 ====================

    def get_order_report(self, start_date: datetime = None,
                        end_date: datetime = None) -> dict[str, Any]:
        """
        订单报表

        Args:
            start_date: 开始日期
            end_date: 结束日期
        """
        if not start_date:
            start_date = datetime.now() - timedelta(days=30)
        if not end_date:
            end_date = datetime.now()

        session = SyncSessionLocal()
        try:
            # 查询订单数据
            orders = session.query(Order).filter(
                Order.order_date >= start_date,
                Order.order_date <= end_date
            ).all()

            # 统计数据
            total_orders = len(orders)
            total_quantity = sum(o.quantity for o in orders)

            # 按状态统计
            status_stats = {}
            for order in orders:
                status = order.status
                if status not in status_stats:
                    status_stats[status] = {'count': 0, 'quantity': 0}
                status_stats[status]['count'] += 1
                status_stats[status]['quantity'] += order.quantity

            # 按客户统计
            customer_stats = {}
            for order in orders:
                customer = order.customer
                if customer not in customer_stats:
                    customer_stats[customer] = {'count': 0, 'quantity': 0}
                customer_stats[customer]['count'] += 1
                customer_stats[customer]['quantity'] += order.quantity

            # 按产品统计
            product_stats = {}
            for order in orders:
                product_name = order.product.name if order.product else '未知'
                if product_name not in product_stats:
                    product_stats[product_name] = {'count': 0, 'quantity': 0}
                product_stats[product_name]['count'] += 1
                product_stats[product_name]['quantity'] += order.quantity

            # 按日期统计(趋势)
            daily_stats = {}
            for order in orders:
                date_key = order.order_date.strftime('%Y-%m-%d')
                if date_key not in daily_stats:
                    daily_stats[date_key] = {'count': 0, 'quantity': 0}
                daily_stats[date_key]['count'] += 1
                daily_stats[date_key]['quantity'] += order.quantity

            return {
                'report_type': '订单报表',
                'period': {
                    'start': start_date.strftime('%Y-%m-%d'),
                    'end': end_date.strftime('%Y-%m-%d')
                },
                'summary': {
                    'total_orders': total_orders,
                    'total_quantity': total_quantity,
                    'avg_quantity': total_quantity / total_orders if total_orders > 0 else 0
                },
                'by_status': status_stats,
                'by_customer': customer_stats,
                'by_product': product_stats,
                'daily_trend': daily_stats
            }
        finally:
            session.close()

    # ==================== 备货报表 ====================

    def get_stockin_report(self, start_date: datetime = None,
                          end_date: datetime = None) -> dict[str, Any]:
        """
        备货报表

        Args:
            start_date: 开始日期
            end_date: 结束日期
        """
        if not start_date:
            start_date = datetime.now() - timedelta(days=30)
        if not end_date:
            end_date = datetime.now()

        session = SyncSessionLocal()
        try:
            # 查询备货数据
            stockins = session.query(StockIn).filter(
                StockIn.stockin_date >= start_date,
                StockIn.stockin_date <= end_date
            ).all()

            # 统计数据
            total_stockins = len(stockins)
            total_quantity = sum(s.quantity for s in stockins)

            # 按客户统计
            customer_stats = {}
            for stockin in stockins:
                customer = stockin.customer
                if customer not in customer_stats:
                    customer_stats[customer] = {'count': 0, 'quantity': 0}
                customer_stats[customer]['count'] += 1
                customer_stats[customer]['quantity'] += stockin.quantity

            # 按产品统计
            product_stats = {}
            for stockin in stockins:
                product_name = stockin.product.name if stockin.product else '未知'
                if product_name not in product_stats:
                    product_stats[product_name] = {'count': 0, 'quantity': 0}
                product_stats[product_name]['count'] += 1
                product_stats[product_name]['quantity'] += stockin.quantity

            # 按日期统计
            daily_stats = {}
            for stockin in stockins:
                date_key = stockin.stockin_date.strftime('%Y-%m-%d')
                if date_key not in daily_stats:
                    daily_stats[date_key] = {'count': 0, 'quantity': 0}
                daily_stats[date_key]['count'] += 1
                daily_stats[date_key]['quantity'] += stockin.quantity

            return {
                'report_type': '备货报表',
                'period': {
                    'start': start_date.strftime('%Y-%m-%d'),
                    'end': end_date.strftime('%Y-%m-%d')
                },
                'summary': {
                    'total_stockins': total_stockins,
                    'total_quantity': total_quantity,
                    'avg_quantity': total_quantity / total_stockins if total_stockins > 0 else 0
                },
                'by_customer': customer_stats,
                'by_product': product_stats,
                'daily_trend': daily_stats
            }
        finally:
            session.close()

    # ==================== 出货报表 ====================

    def get_stockout_report(self, start_date: datetime = None,
                           end_date: datetime = None) -> dict[str, Any]:
        """
        出货报表

        Args:
            start_date: 开始日期
            end_date: 结束日期
        """
        if not start_date:
            start_date = datetime.now() - timedelta(days=30)
        if not end_date:
            end_date = datetime.now()

        session = SyncSessionLocal()
        try:
            # 查询出货数据
            stockouts = session.query(StockOut).filter(
                StockOut.stockout_date >= start_date,
                StockOut.stockout_date <= end_date
            ).all()

            # 统计数据
            total_stockouts = len(stockouts)
            total_quantity = sum(s.quantity for s in stockouts)

            # 按客户统计
            customer_stats = {}
            for stockout in stockouts:
                customer = stockout.customer or '未知客户'
                if customer not in customer_stats:
                    customer_stats[customer] = {'count': 0, 'quantity': 0}
                customer_stats[customer]['count'] += 1
                customer_stats[customer]['quantity'] += stockout.quantity

            # 按产品统计
            product_stats = {}
            for stockout in stockouts:
                product_name = stockout.product.name if stockout.product else '未知'
                if product_name not in product_stats:
                    product_stats[product_name] = {'count': 0, 'quantity': 0}
                product_stats[product_name]['count'] += 1
                product_stats[product_name]['quantity'] += stockout.quantity

            # 按日期统计
            daily_stats = {}
            for stockout in stockouts:
                date_key = stockout.stockout_date.strftime('%Y-%m-%d')
                if date_key not in daily_stats:
                    daily_stats[date_key] = {'count': 0, 'quantity': 0}
                daily_stats[date_key]['count'] += 1
                daily_stats[date_key]['quantity'] += stockout.quantity

            return {
                'report_type': '出货报表',
                'period': {
                    'start': start_date.strftime('%Y-%m-%d'),
                    'end': end_date.strftime('%Y-%m-%d')
                },
                'summary': {
                    'total_stockouts': total_stockouts,
                    'total_quantity': total_quantity,
                    'avg_quantity': total_quantity / total_stockouts if total_stockouts > 0 else 0
                },
                'by_customer': customer_stats,
                'by_product': product_stats,
                'daily_trend': daily_stats
            }
        finally:
            session.close()

    # ==================== 综合报表 ====================

    def get_comprehensive_report(self, start_date: datetime = None,
                                end_date: datetime = None) -> dict[str, Any]:
        """
        综合报表
        包含订单、备货、出货的综合分析
        """
        order_report = self.get_order_report(start_date, end_date)
        stockin_report = self.get_stockin_report(start_date, end_date)
        stockout_report = self.get_stockout_report(start_date, end_date)

        return {
            'report_type': '综合报表',
            'period': order_report['period'],
            'order': order_report,
            'stockin': stockin_report,
            'stockout': stockout_report,
            'summary': {
                'total_orders': order_report['summary']['total_orders'],
                'total_stockins': stockin_report['summary']['total_stockins'],
                'total_stockouts': stockout_report['summary']['total_stockouts']
            }
        }


if __name__ == '__main__':
    print("增强报表功能模块")
    print("\n支持的报表类型:")
    print("1. 订单报表 - get_order_report()")
    print("2. 备货报表 - get_stockin_report()")
    print("3. 出货报表 - get_stockout_report()")
    print("4. 综合报表 - get_comprehensive_report()")
