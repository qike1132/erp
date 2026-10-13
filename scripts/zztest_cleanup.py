"""ZZTEST 数据清理（按 ZZTEST 作用域删除，只删测试数据，不碰真实业务）

- 需提权（根 .env 的 ACL）。
- 需显式授权写库：ERP_ALLOW_PROD_WRITE=1 或 --allow-prod-write。
- 作用域：product.name LIKE 'ZZTEST%' 与 customer.name = 'ZZTEST_客户A'。
- 删完刷新物化视图 + 清 Redis 应用缓存，并复核残留为 0。
"""
from __future__ import annotations

import contextlib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'scripts'))
with contextlib.suppress(Exception):
    sys.stdout.reconfigure(encoding='utf-8')  # type: ignore[union-attr]

from _prod_write_guard import require_prod_write_consent

require_prod_write_consent(
    'ZZTEST 数据清理：按 ZZTEST 作用域删除测试数据',
    hint='只删 ZZTEST_ 前缀测试数据；删完复核残留为 0',
)

from sqlalchemy import create_engine, text

from fastapi_app.core.config import settings

CUST = 'ZZTEST_客户A'
eng = create_engine(settings.DATABASE_URL, pool_pre_ping=True)


def q(sql, p=None, fetch=False):
    with eng.begin() as c:
        r = c.execute(text(sql), p or {})
        return r.fetchall() if fetch else r.rowcount


def one(sql, p=None):
    r = q(sql, p, fetch=True)
    return r[0][0] if r else 0


def idl(x):
    return ','.join(str(int(i)) for i in x)


pids = [r[0] for r in q("SELECT id FROM product WHERE name LIKE 'ZZTEST%'", fetch=True)]
oids = [r[0] for r in q('SELECT id FROM "order" WHERE customer=:c', {'c': CUST}, fetch=True)]
pset = f'({idl(pids)})' if pids else '(NULL)'
oset = f'({idl(oids)})' if oids else '(NULL)'
print(f'ZZTEST 作用域: products={len(pids)}  orders={len(oids)}')

print('\n=== 删除（按外键依赖顺序）===')
for name, sql in [
    ('stock_return', f'DELETE FROM stock_return WHERE product_id IN {pset}'),
    ('inventory_log', f'DELETE FROM inventory_log WHERE product_id IN {pset}'),
    ('daily_production_record', f'DELETE FROM daily_production_record WHERE product_id IN {pset}'),
    ('stock_out', 'DELETE FROM stock_out WHERE customer=:c'),
    ('stock_in', 'DELETE FROM stock_in WHERE customer=:c'),
    ('order_item', f'DELETE FROM order_item WHERE order_id IN {oset}'),
    ('approval_request', f'DELETE FROM approval_request WHERE order_id IN {oset}'),
    ('order', 'DELETE FROM "order" WHERE customer=:c'),
    ('product_customer', f'DELETE FROM product_customer WHERE product_id IN {pset}'),
    ('product', f'DELETE FROM product WHERE id IN {pset}'),
    ('customer', 'DELETE FROM customer WHERE name=:c'),
]:
    try:
        print(f'  {name:<24} {q(sql, {"c": CUST})} 行')
    except Exception as e:  # noqa: BLE001
        print(f'  {name:<24} skip: {str(e)[:110]}')
try:
    print(f'  {"packaging_record":<24} {q("DELETE FROM packaging_record WHERE product_name LIKE :x", {"x": "ZZTEST%"})} 行')
except Exception as e:  # noqa: BLE001
    print(f'  packaging_record         skip: {str(e)[:80]}')

print('\n=== 刷新物化视图 ===')
for mv in ('mv_daily_order_quantity', 'mv_daily_stockin_quantity', 'mv_daily_stockout_quantity', 'mv_product_aggregate'):
    try:
        q(f'REFRESH MATERIALIZED VIEW "{mv}"')
        print(f'  REFRESH {mv} ok')
    except Exception as e:  # noqa: BLE001
        print(f'  REFRESH {mv} skip: {str(e)[:80]}')

print('\n=== 清 Redis 应用缓存 ===')
try:
    import redis
    client = redis.Redis(host=settings.REDIS_HOST, port=settings.REDIS_PORT, db=settings.REDIS_DB,
                         password=settings.REDIS_PASSWORD or None, decode_responses=True)
    client.ping()
    n = 0
    for pattern in ('erp:*',):
        keys = list(client.scan_iter(pattern))
        if keys:
            n += client.delete(*keys)
    client.close()
    print(f'  删除 {n} 个缓存键')
except Exception as e:  # noqa: BLE001
    print(f'  Redis 跳过: {str(e)[:120]}')

print('\n=== 复核残留（必须全 0）===')
leftover = 0
for name, sql in [
    ('product', "SELECT count(*) FROM product WHERE name LIKE 'ZZTEST%'"),
    ('customer', 'SELECT count(*) FROM customer WHERE name=:c'),
    ('order', 'SELECT count(*) FROM "order" WHERE customer=:c'),
    ('order_item', 'SELECT count(*) FROM order_item oi JOIN "order" o ON o.id=oi.order_id WHERE o.customer=:c'),
    ('stock_in', 'SELECT count(*) FROM stock_in WHERE customer=:c'),
    ('stock_out', 'SELECT count(*) FROM stock_out WHERE customer=:c'),
    ('inventory_log', f'SELECT count(*) FROM inventory_log WHERE product_id IN {pset}'),
    ('daily_production_record', f'SELECT count(*) FROM daily_production_record WHERE product_id IN {pset}'),
]:
    n = one(sql, {'c': CUST})
    leftover += n
    print(f'  {name:<24} 残留 {n} 行')
print('\nDONE  残留合计=' + str(leftover))
