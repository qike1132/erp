"""复现：对「抵扣行」退货 → /stock「库存(结余)」虚增。

完整流程：建客户/SKU → 生产入库 → 备货入库 → 下单 → 抵扣 → 【对抵扣退货】→ 看结余。
只读 + 打 ZZTEST_REPRO 标记的少量测试数据，跑完自动清理。
需提权（根 .env ACL）；需 ERP_ALLOW_PROD_WRITE=1。
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

require_prod_write_consent('ZZTEST_REPRO 复现：抵扣行退货结余虚增', hint='打 ZZTEST_REPRO 标记，跑完自动清理')

import httpx
from sqlalchemy import create_engine, text

from fastapi_app.core.auth.token import create_access_token
from fastapi_app.core.config import settings

BASE = 'http://127.0.0.1:5002'
CUST = 'ZZTEST_REPRO_客户'
PROD = 'ZZTEST_REPRO-SKU'
BC = 'ZZTESTREPRO690001'
eng = create_engine(settings.DATABASE_URL, pool_pre_ping=True)


def q(sql, p=None, fetch=False):
    with eng.begin() as c:
        r = c.execute(text(sql), p or {})
        return r.fetchall() if fetch else r.rowcount


def one(sql, p=None):
    r = q(sql, p, fetch=True)
    return r[0][0] if r else 0


rows = q('SELECT id FROM "user" WHERE username=:u', {'u': 'admin'}, fetch=True)
uid = rows[0][0] if rows else q('SELECT id FROM "user" WHERE is_super IS TRUE ORDER BY id LIMIT 1', fetch=True)[0][0]
client = httpx.Client(base_url=BASE, timeout=30, trust_env=False,
                      headers={'Authorization': f'Bearer {create_access_token({"sub": str(uid)})}',
                               'Origin': (settings.BACKEND_CORS_ORIGINS or ['http://localhost'])[0]})


def post(path, **json):
    r = client.post(path, json=json)
    return r


def balance(pid):
    """/stock「库存(结余)」公式：包装部生产 − 出货流水净额（含退货，不含抵扣）。"""
    pack = int(one("SELECT COALESCE(SUM(quantity),0) FROM daily_production_record "
                   "WHERE product_id=:p AND department='packaging'", {'p': pid}))
    logship = int(one("SELECT COALESCE(SUM(change_quantity),0) FROM inventory_log WHERE product_id=:p "
                      "AND change_type IN ('出库','出库修改','出库删除','退货','退货取消')", {'p': pid}))
    return pack + logship


def cleanup():
    pids = [r[0] for r in q("SELECT id FROM product WHERE name LIKE 'ZZTEST_REPRO%'", fetch=True)]
    oids = [r[0] for r in q('SELECT id FROM "order" WHERE customer=:c', {'c': CUST}, fetch=True)]
    pset = f"({','.join(map(str, pids))})" if pids else '(NULL)'
    oset = f"({','.join(map(str, oids))})" if oids else '(NULL)'
    for sql in (f'DELETE FROM stock_return WHERE product_id IN {pset}',
                f'DELETE FROM inventory_log WHERE product_id IN {pset}',
                f'DELETE FROM daily_production_record WHERE product_id IN {pset}',
                'DELETE FROM stock_out WHERE customer=:c', 'DELETE FROM stock_in WHERE customer=:c',
                f'DELETE FROM order_item WHERE order_id IN {oset}',
                'DELETE FROM "order" WHERE customer=:c',
                f'DELETE FROM product_customer WHERE product_id IN {pset}',
                f'DELETE FROM product WHERE id IN {pset}', 'DELETE FROM customer WHERE name=:c'):
        with contextlib.suppress(Exception):
            q(sql, {'c': CUST})
    with contextlib.suppress(Exception):
        db = list(client.get('/api/v1/reports/return-logs', params={'customer': CUST}).json().get('logs', []))
        del db


print('=' * 70)
print('复现：对「抵扣行」退货 → /stock「库存(结余)」虚增')
print('=' * 70)
cleanup()

# 1) 建客户 + SKU
post('/api/v1/customers/create', name=CUST, contact='ZZTEST_REPRO', note='ZZTEST_REPRO')
cid = q('SELECT id FROM customer WHERE name=:n ORDER BY id DESC LIMIT 1', {'n': CUST}, fetch=True)[0][0]
post('/api/v1/products/create', name=PROD, barcode=BC, price=9.99, initial_stock=0, customer_ids=[cid])
pid = q('SELECT id FROM product WHERE name=:n ORDER BY id DESC LIMIT 1', {'n': PROD}, fetch=True)[0][0]
print(f'[0] 建客户 id={cid} / SKU id={pid}')

# 2) 生产入库 1000
post('/api/v1/daily-production/records', department='packaging', product_id=pid, product_name=PROD,
     barcode=BC, unit_price=0, quantity=1000, production_date='2026-06-01', remark='ZZTEST_REPRO')
print(f'[1] 生产入库 1000            → 结余 = {balance(pid)}')

# 3) 备货入库 1000
post('/api/v1/stock/in/create', product_id=pid, quantity=1000, customer=CUST,
     stockin_date='2026-06-01', note='ZZTEST_REPRO')
print(f'[2] 备货入库 1000            → 结余 = {balance(pid)}')

# 4) 下单 500
post('/api/v1/orders/create', product_id=pid, quantity=500, customer=CUST, note='ZZTEST_REPRO')
oid = q('SELECT id FROM "order" WHERE customer=:c ORDER BY id DESC LIMIT 1', {'c': CUST}, fetch=True)[0][0]
print(f'[3] 下单 500 (id={oid})        → 结余 = {balance(pid)}')

# 5) 抵扣 300（从备货池划给订单）
client.put(f'/api/v1/orders/deduct/{oid}', params={'deduct_quantity': 300})
before = balance(pid)
print(f'[4] 抵扣 300（货没走）        → 结余 = {before}   ← 正确，抵扣不动结余')

# 6) 对这笔「抵扣」退货 300（界面做不了，只能走接口）
sid = q('SELECT id FROM stock_out WHERE order_id=:o AND stockin_id IS NOT NULL ORDER BY id DESC LIMIT 1',
        {'o': oid}, fetch=True)[0][0]
post('/api/v1/stock-returns/create', stockout_id=sid, quantity=300, return_date='2026-06-01',
     reason='ZZTEST_REPRO', note='ZZTEST_REPRO')
after = balance(pid)
print(f'[5] 对「抵扣行」退货 300      → 结余 = {after}   ← ❌ 应仍为 {before}，却多了 {after - before}')

print('-' * 70)
print('inventory_log（该 SKU）：')
for r in q('SELECT change_type, change_quantity FROM inventory_log WHERE product_id=:p ORDER BY id',
           {'p': pid}, fetch=True):
    print(f'   {r[0]:<8} {r[1]:>8}')
print('-' * 70)
verdict = 'BUG 复现成功（结余虚增）' if after > before else '未复现'
print(f'结论：{verdict}：{before} → {after}（+{after - before}）')
print('=' * 70)

cleanup()
print('已清理 ZZTEST_REPRO 测试数据。')
