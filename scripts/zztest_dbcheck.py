"""ZZTEST 写侧独立复核（只读，需提权）

确认批量写入**无静默丢失**（对照应然值），并校验每 SKU 的库存不变量：
    product.current_stock == Σ生产 + Σ备货 − Σ抵扣 − Σ出货
"""
from __future__ import annotations

import contextlib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
with contextlib.suppress(Exception):
    sys.stdout.reconfigure(encoding='utf-8')  # type: ignore[union-attr]

from sqlalchemy import create_engine, text

from fastapi_app.core.config import settings

CUST = 'ZZTEST_客户A'
eng = create_engine(settings.DATABASE_URL, pool_pre_ping=True)


def q(sql, p=None):
    with eng.begin() as c:
        return c.execute(text(sql), p or {}).fetchall()


def one(sql, p=None):
    r = q(sql, p)
    return r[0][0] if r else 0


print('=== ZZTEST 写侧独立复核 ===')
pids = [r[0] for r in q("SELECT id FROM product WHERE name LIKE 'ZZTEST%'")]
print(f'SKU 数: {len(pids)}')
print(f'订单数       : {one("SELECT count(*) FROM \"order\" WHERE customer=:c", {"c": CUST})}  (应然 9000)')
print(f'订单明细数   : {one("SELECT count(*) FROM order_item oi JOIN \"order\" o ON o.id=oi.order_id WHERE o.customer=:c", {"c": CUST})}  (应然 9000)')
print(f'备货入库数   : {one("SELECT count(*) FROM stock_in WHERE customer=:c", {"c": CUST})}  (应然 9000)')
print(f'生产记录数   : {one("SELECT count(*) FROM daily_production_record WHERE product_id = ANY(:p)", {"p": pids})}  (应然 9000)')
print(f'抵扣出库数   : {one("SELECT count(*) FROM stock_out WHERE customer=:c AND stockin_id IS NOT NULL", {"c": CUST})}')
print(f'独立出货数   : {one("SELECT count(*) FROM stock_out WHERE customer=:c AND stockin_id IS NULL", {"c": CUST})}')
print(f'库存流水数   : {one("SELECT count(*) FROM inventory_log WHERE product_id = ANY(:p)", {"p": pids})}')
print(f'退货记录数   : {one("SELECT count(*) FROM stock_return WHERE customer=:c", {"c": CUST})}')

print('\n=== 订单状态分布 ===')
for st, n in q('SELECT status, count(*) FROM "order" WHERE customer=:c GROUP BY status ORDER BY 2 DESC', {'c': CUST}):
    print(f'  {st}: {n}')

print('\n=== 每 SKU 不变量 current_stock == Σ生产 + Σ备货 − Σ抵扣 − Σ出货 ===')
bad = 0
for pid in pids:
    cs = one('SELECT current_stock FROM product WHERE id=:p', {'p': pid})
    pack = one("SELECT COALESCE(SUM(quantity),0) FROM daily_production_record WHERE product_id=:p AND department='packaging'", {'p': pid})
    sin = one('SELECT COALESCE(SUM(quantity),0) FROM stock_in WHERE product_id=:p', {'p': pid})
    ded = one('SELECT COALESCE(SUM(quantity-returned_quantity),0) FROM stock_out WHERE product_id=:p AND stockin_id IS NOT NULL', {'p': pid})
    shp = one('SELECT COALESCE(SUM(quantity-returned_quantity),0) FROM stock_out WHERE product_id=:p AND stockin_id IS NULL', {'p': pid})
    rhs = pack + sin - ded - shp
    if cs != rhs:
        bad += 1
        print(f'  MISMATCH pid={pid}: current_stock={cs} vs {rhs} (pack={pack} sin={sin} ded={ded} shp={shp})')
print(f'  不变量违反: {bad} / {len(pids)}')

print('\n=== 合计（跨全部 SKU）===')
print(f'  Σ生产: {one("SELECT COALESCE(SUM(quantity),0) FROM daily_production_record WHERE product_id = ANY(:p)", {"p": pids})}')
print(f'  Σ备货: {one("SELECT COALESCE(SUM(quantity),0) FROM stock_in WHERE customer=:c", {"c": CUST})}')
print(f'  Σ订单: {one("SELECT COALESCE(SUM(oi.quantity),0) FROM order_item oi JOIN \"order\" o ON o.id=oi.order_id WHERE o.customer=:c", {"c": CUST})}')
print(f'  Σ抵扣: {one("SELECT COALESCE(SUM(quantity-returned_quantity),0) FROM stock_out WHERE customer=:c AND stockin_id IS NOT NULL", {"c": CUST})}')
print(f'  Σ出货: {one("SELECT COALESCE(SUM(quantity-returned_quantity),0) FROM stock_out WHERE customer=:c AND stockin_id IS NULL", {"c": CUST})}')
print('\nDONE')
