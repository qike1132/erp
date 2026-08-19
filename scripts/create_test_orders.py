"""批量创建 30 个 MINISO 白名单客户订单，用于测试批次号查询"""

import os
import random
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi_app.core.database import SyncSessionLocal
from fastapi_app.shared_models import Order, Product

MINISO_CUSTOMERS = ['MINISO电商', 'MINISO国际', 'MINISO国内', 'MINISO小程序']
PREFIX = 'OR260509'
BATCH_SIZE = 30


def main():
    session = SyncSessionLocal()
    try:
        products = session.query(Product).all()
        if not products:
            print('[ERROR] 数据库无产品数据，请先添加产品')
            return
        print(f'[INFO] 可用产品: {len(products)} 个')

        last = session.query(Order).filter(
            Order.order_no.like(f'{PREFIX}%')
        ).order_by(Order.order_no.desc()).first()

        next_seq = 1
        if last:
            try:
                next_seq = int(last.order_no[-5:]) + 1
            except (ValueError, IndexError):
                next_seq = 1

        print(f'[INFO] 起始序号: {next_seq:05d}')

        now = datetime.now()
        orders = []
        for i in range(BATCH_SIZE):
            seq = next_seq + i
            order_no = f'{PREFIX}{seq:05d}'
            customer = 'MINISO国际'
            product = random.choice(products)
            quantity = random.randint(50, 500)
            days_ago = random.randint(0, 30)
            order_date = now - timedelta(days=days_ago, hours=random.randint(0, 23), minutes=random.randint(0, 59))

            order = Order(
                order_no=order_no,
                customer=customer,
                product_id=product.id,
                quantity=quantity,
                order_date=order_date,
                status='待备货',
                order_type='regular',
            )
            session.add(order)
            orders.append(order)

        session.commit()
        print(f'\n[OK] 成功创建 {len(orders)} 个订单:\n')

        for o in orders:
            prod = session.query(Product).get(o.product_id)
            print(f'  {o.order_no} | {o.customer:12s} | {prod.name if prod else "?":16s} | qty={o.quantity:3d} | {o.order_date.strftime("%Y-%m-%d %H:%M")}')

        print('\n[OK] 所有订单状态: 待备货（白名单客户自动进入批次号查询）')

    finally:
        session.close()


if __name__ == '__main__':
    main()
