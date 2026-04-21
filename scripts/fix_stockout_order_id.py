"""
修复历史出货记录的订单ID关联
将没有关联订单ID的出货记录按FIFO原则关联到对应订单
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi_app.core.database import SyncSessionLocal
from fastapi_app.shared_models import StockOut, Order
from sqlalchemy import func


def fix_stockout_order_ids():
    """修复出货记录的订单ID关联"""
    session = SyncSessionLocal()
    try:
        stockouts = session.query(StockOut).filter(
            StockOut.order_id.is_(None),
            StockOut.stockin_id.is_(None),
            StockOut.customer.isnot(None),
            StockOut.customer != ''
        ).order_by(StockOut.stockout_date.asc()).all()

        print(f"找到 {len(stockouts)} 条需要修复的出货记录")

        fixed_count = 0
        for stockout in stockouts:
            orders = session.query(Order).filter_by(
                product_id=stockout.product_id,
                customer=stockout.customer
            ).order_by(Order.order_date.asc()).all()

            if not orders:
                print(f"  跳过出货记录 {stockout.stockout_no}: 没有找到对应订单")
                continue

            remaining_qty = stockout.quantity
            for order in orders:
                if remaining_qty <= 0:
                    break

                already_shipped = session.query(
                    func.sum(StockOut.quantity)
                ).filter(
                    StockOut.order_id == order.id,
                    StockOut.stockin_id.is_(None),
                    StockOut.id != stockout.id
                ).scalar() or 0

                available = order.quantity - already_shipped
                if available > 0:
                    stockout.order_id = order.id
                    fixed_count += 1
                    print(f"  修复出货记录 {stockout.stockout_no}: 关联到订单 {order.order_no}")
                    break

        if fixed_count > 0:
            session.commit()
            print(f"\n成功修复 {fixed_count} 条出货记录")
        else:
            print("\n没有需要修复的记录")
    finally:
        session.close()


if __name__ == '__main__':
    fix_stockout_order_ids()
