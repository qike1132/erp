"""ZZTEST 独立核对（只读）：/stock 与 /report vs 独立推导。

修正：/report 出货流水是**毛量** SUM(quantity)（不扣退货），与 /stock 出货数量（净量）不同源。
其余流水：订单(Σitem_qty)、备货(Σstock_in.quantity)、抵扣(Σ quantity−returned) 均为对应口径。
"""
from __future__ import annotations

import contextlib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
with contextlib.suppress(Exception):
    sys.stdout.reconfigure(encoding='utf-8')  # type: ignore[union-attr]

import httpx
from sqlalchemy import create_engine, text

from fastapi_app.core.auth.token import create_access_token
from fastapi_app.core.config import settings

BASE = 'http://127.0.0.1:5002'
CUST = 'ZZTEST_客户A'
eng = create_engine(settings.DATABASE_URL, pool_pre_ping=True, pool_size=10, max_overflow=10)


def q(sql, p=None):
    with eng.begin() as c:
        return c.execute(text(sql), p or {}).fetchall()


def one(sql, p=None):
    r = q(sql, p)
    return r[0][0] if r else 0


rows = q('SELECT id FROM "user" WHERE username=:u', {'u': 'admin'})
uid = rows[0][0] if rows else q('SELECT id FROM "user" WHERE is_super IS TRUE ORDER BY id LIMIT 1')[0][0]
token = create_access_token({'sub': str(uid)})
origins = [o for o in (settings.BACKEND_CORS_ORIGINS or []) if isinstance(o, str) and o]
client = httpx.Client(base_url=BASE, timeout=60, trust_env=False,
                      headers={'Authorization': f'Bearer {token}', 'Origin': origins[0] if origins else 'http://localhost'})


def ok(r):
    return r is not None and r.status_code == 200 and r.json().get('success')


def get(path, **params):
    return client.get(path, params=params)


prods = q("SELECT id, name FROM product WHERE name LIKE 'ZZTEST%' ORDER BY name")
print(f'ZZTEST SKU 数: {len(prods)}')


def derive(pid):
    d = {}
    d['ord'] = int(one('SELECT COALESCE(SUM(oi.quantity),0) FROM order_item oi JOIN "order" o ON o.id=oi.order_id '
                       'WHERE o.product_id=:p AND o.customer=:c AND o.is_deleted IS NOT TRUE', {'p': pid, 'c': CUST}))
    d['ded'] = int(one('SELECT COALESCE(SUM(quantity-returned_quantity),0) FROM stock_out '
                       'WHERE product_id=:p AND customer=:c AND stockin_id IS NOT NULL', {'p': pid, 'c': CUST}))
    d['ship'] = int(one('SELECT COALESCE(SUM(quantity-returned_quantity),0) FROM stock_out '
                        'WHERE product_id=:p AND customer=:c AND stockin_id IS NULL AND order_id IS NOT NULL', {'p': pid, 'c': CUST}))
    d['direct'] = int(one('SELECT COALESCE(SUM(quantity-returned_quantity),0) FROM stock_out '
                          'WHERE product_id=:p AND customer=:c AND stockin_id IS NULL AND order_id IS NULL', {'p': pid, 'c': CUST}))
    d['ship_gross'] = int(one('SELECT COALESCE(SUM(quantity),0) FROM stock_out '
                              'WHERE product_id=:p AND customer=:c AND stockin_id IS NULL', {'p': pid, 'c': CUST}))
    d['stockin_avail'] = int(one('SELECT COALESCE(SUM(si.quantity - COALESCE(sub.consumed,0)),0) FROM stock_in si '
                                 'LEFT JOIN (SELECT stockin_id, SUM(quantity-returned_quantity) consumed FROM stock_out '
                                 'WHERE stockin_id IS NOT NULL GROUP BY stockin_id) sub ON sub.stockin_id=si.id '
                                 'WHERE si.product_id=:p AND si.customer=:c', {'p': pid, 'c': CUST}))
    d['stockin_total'] = int(one('SELECT COALESCE(SUM(quantity),0) FROM stock_in WHERE product_id=:p AND customer=:c', {'p': pid, 'c': CUST}))
    d['pack'] = int(one("SELECT COALESCE(SUM(quantity),0) FROM daily_production_record WHERE product_id=:p AND department='packaging'", {'p': pid}))
    d['logship'] = int(one("SELECT COALESCE(SUM(change_quantity),0) FROM inventory_log WHERE product_id=:p "
                           "AND change_type IN ('出库','出库修改','出库删除','退货','退货取消')", {'p': pid}))
    d['balance'] = d['pack'] + d['logship']
    d['remaining'] = max(0, d['ord'] - d['direct'] - d['ship'])
    d['total_stock'] = d['stockin_avail'] + d['remaining']
    return d


# /stock 行（按客户过滤分页）
stock_rows = {}
page = 1
while True:
    r = get('/api/v1/stock/inventory', customer=CUST, page=page, per_page=200)
    if not ok(r):
        break
    j = r.json()
    for row in j.get('data', []):
        stock_rows[row['product_name']] = row
    if len(j.get('data', [])) < 200:
        break
    page += 1


def report_total(flow, name):
    r = get(f'/api/v1/reports/{flow}', customer=CUST, product=name, per_page=1)
    return int(r.json().get('stats', {}).get('total_quantity', 0)) if ok(r) else None


def num(v):
    return int(v) if v not in ('', None) else 0


mismatches = []
exp = {}
for pid, name in prods:
    d = derive(pid)
    exp[pid] = d
    row = stock_rows.get(name)
    if row is None:
        if d['total_stock'] != 0:
            mismatches.append(f'{name}: /stock 无该行 (total_stock={d["total_stock"]})')
    else:
        for field, got, want in [
            ('订单数量(order_quantity)', num(row.get('order_quantity')), d['remaining']),
            ('备货数量(stockin_quantity)', num(row.get('stockin_quantity')), d['stockin_avail']),
            ('出货数量(stockout_quantity)', num(row.get('stockout_quantity')), d['direct'] + d['ship']),
            ('总订单(total_stock)', num(row.get('total_stock')), d['total_stock']),
            ('库存结余(inventory_balance)', num(row.get('inventory_balance')), d['balance']),
        ]:
            if got != want:
                mismatches.append(f'{name}: /stock {field} 实测={got} 期望={want}')
    for flow, want in [('order-logs', d['ord']), ('stockin-logs', d['stockin_total']),
                       ('stockout-logs', d['ship_gross']), ('deduction-logs', d['ded'])]:
        got = report_total(flow, name)
        if got != want:
            mismatches.append(f'{name}: /report/{flow} 实测={got} 期望={want}')

# /stock 顶部聚合
r = get('/api/v1/stock/inventory', customer=CUST, per_page=1)
if ok(r):
    j = r.json()
    for label, got, want in [
        ('订单数量', int(j.get('total_order_quantity', 0) or 0), sum(d['remaining'] for d in exp.values())),
        ('备货数量', int(j.get('total_stockin_quantity', 0) or 0), sum(d['stockin_avail'] for d in exp.values())),
        ('总订单', int(j.get('total_stock', 0) or 0), sum(d['total_stock'] for d in exp.values())),
    ]:
        if got != want:
            mismatches.append(f'/stock 顶部「{label}」: 实测={got} 期望={want}')

# /purchase 订单状态派生逐单核对
srows = q(
    'SELECT o.order_no, o.quantity, o.status, o.batch_completed_at, '
    'COALESCE(d.ded,0), COALESCE(s.ship,0) '
    'FROM "order" o '
    'LEFT JOIN (SELECT order_id, SUM(quantity-returned_quantity) ded FROM stock_out '
    '           WHERE stockin_id IS NOT NULL GROUP BY order_id) d ON d.order_id=o.id '
    'LEFT JOIN (SELECT order_id, SUM(quantity-returned_quantity) ship FROM stock_out '
    '           WHERE stockin_id IS NULL GROUP BY order_id) s ON s.order_id=o.id '
    'WHERE o.customer=:c AND o.is_deleted IS NOT TRUE', {'c': CUST})
for ono, qty, status, bca, ded_raw, ship_raw in srows:
    ded, ship = int(ded_raw), int(ship_raw)
    if bca:
        exp_s = '批次已完成'
    elif ship >= qty:
        exp_s = '已出货'
    elif ship > 0:
        exp_s = '待出货'
    elif ded >= qty:
        exp_s = '已备货'
    elif ded > 0:
        exp_s = '部分备货'
    else:
        exp_s = '待备货'
    if status != exp_s:
        mismatches.append(f'/purchase {ono}: status={status} 期望={exp_s}')

print(f'\n=== 核对结果：{"PASS" if not mismatches else "FAIL"} ===')
if mismatches:
    print(f'发现 {len(mismatches)} 处不一致：')
    for x in mismatches[:60]:
        print(f'  - {x}')
else:
    print('全部 SKU 的 /stock（订单数量/备货数量/出货数量/总订单/库存结余）+ 4 条流水 + 顶部聚合'
          ' + /purchase 逐单状态 == 独立推导（0 处不一致）')
print('DONE')
