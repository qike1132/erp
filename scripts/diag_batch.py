"""批次号查询诊断 — 逐环节检查数据链路"""
import sys, os, json, asyncio
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi_app.core.database import SyncSessionLocal
from fastapi_app.shared_models import Order, Permission, User, OrderSyncConfig

session = SyncSessionLocal()
try:
    print('=' * 60)
    print('1. 白名单配置')
    print('=' * 60)
    cfg = session.query(OrderSyncConfig).filter_by(config_key='order_batch_whitelist').first()
    if cfg:
        print(f'   OK: {cfg.config_value}')
    else:
        print('   MISSING: order_batch_whitelist 不存在!')

    print()
    print('=' * 60)
    print('2. batch_manage 权限记录')
    print('=' * 60)
    perm = session.query(Permission).filter_by(code='batch_manage').first()
    if perm:
        print(f'   id={perm.id}, is_nav={perm.is_nav}, url={perm.url}, section={perm.section}')
    else:
        print('   MISSING: batch_manage 不存在!')

    print()
    print('=' * 60)
    print('3. 后端直接查询订单 (不走 API)')
    print('=' * 60)
    async def test_query():
        from fastapi_app.core.database import get_async_read_db
        from fastapi_app.services.order_batch_service import get_whitelist, get_batch_query_list
        async for db in get_async_read_db():
            whitelist = await get_whitelist(db)
            print(f'   白名单: {whitelist}')

            result = await get_batch_query_list(db, page=1, per_page=5)
            print(f'   total: {result["total"]}')
            if result['items']:
                for item in result['items'][:5]:
                    print(f"     {item['order_no']} | {item['customer']:12s} | qty={item['quantity']} | deducted={item['deducted_qty']} | shipped={item['shipped_qty']} | batch={item.get('batch_no','')}")
            else:
                print('   ❌ items 为空!')
            break

    try:
        asyncio.run(test_query())
    except (OSError, ConnectionError, RuntimeError) as e:
        print(f'   异步查询失败: {e}')

    print()
    print('=' * 60)
    print('4. 同步直查订单数量')
    print('=' * 60)
    import json as _json
    whitelist_raw = session.query(OrderSyncConfig).filter_by(config_key='order_batch_whitelist').first()
    if whitelist_raw:
        customers = _json.loads(whitelist_raw.config_value)
        count = session.query(Order).filter(
            Order.customer.in_(customers),
            Order.is_deleted.isnot(True),
        ).count()
        print(f'   MINISO 白名单订单: {count} 条')
        recent = session.query(Order).filter(
            Order.order_no.like('OR260509%'),
        ).count()
        print(f'   今天新建测试订单: {recent} 条')

    print()
    print('=' * 60)
    print('5. 检查超级管理员')
    print('=' * 60)
    super_users = session.query(User).filter_by(is_super=True).all()
    if super_users:
        for u in super_users:
            print(f'   id={u.id}, username={u.username}')
    else:
        print('   无超级管理员!')

finally:
    session.close()