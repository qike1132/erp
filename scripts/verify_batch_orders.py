"""验证批次号查询 API 是否正常返回测试订单"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi_app.core.database import SyncSessionLocal
from fastapi_app.shared_models import Order, OrderSyncConfig

session = SyncSessionLocal()
try:
    cfg = session.query(OrderSyncConfig).filter_by(config_key='order_batch_whitelist').first()
    if cfg:
        print(f'Whitelist: {cfg.config_value}')
    else:
        print('Whitelist: NOT CONFIGURED!')

    count = session.query(Order).filter(
        Order.customer.in_(['MINISO电商', 'MINISO国际', 'MINISO国内', 'MINISO小程序']),
        Order.is_deleted.isnot(True),
    ).count()
    print(f'MINISO orders total: {count}')

    recent = session.query(Order).filter(
        Order.order_no.like('OR260509%'),
    ).count()
    print(f'Test orders (OR260509*): {recent}')

    print('\nLatest 5 orders:')
    latest = session.query(Order).filter(
        Order.order_no.like('OR260509%'),
    ).order_by(Order.order_no.desc()).limit(5).all()
    for o in latest:
        print(f'  {o.order_no} | {o.customer:14s} | qty={o.quantity:3d} | status={o.status} | batch_no={o.batch_no}')

finally:
    session.close()
