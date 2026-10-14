"""对比复现：同样一套操作，退货退【出货】 vs 退【抵扣】。

场景（用户给的数字）：下单10000 → 备货10000 → 新订单5000+抵扣5000 → 包装入库15000
→ 出货10000 → 退货1000。唯一差别：退货选中【出货单】还是【抵扣行】。
只打 ZZTEST_CMP 标记，跑完自动清理。需提权 + ERP_ALLOW_PROD_WRITE=1。
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

require_prod_write_consent('ZZTEST_CMP 对比复现：退货退出货 vs 退抵扣', hint='打 ZZTEST_CMP 标记，跑完自清')

import httpx
from sqlalchemy import create_engine, text

from fastapi_app.core.auth.token import create_access_token
from fastapi_app.core.config import settings

BASE = 'http://127.0.0.1:5002'
CUST = 'ZZTEST_CMP_客户'
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


def stock_cols(pid):
    """从原始台账按 /stock CTE 口径算 5 列。"""
    c = {'p': pid, 'c': CUST}
    ord_qty = int(one('SELECT COALESCE(SUM(oi.quantity),0) FROM order_item oi JOIN "order" o ON o.id=oi.order_id '
                      'WHERE o.product_id=:p AND o.customer=:c AND o.is_deleted IS NOT TRUE', c))
    r = q('SELECT '
          'COALESCE(SUM(CASE WHEN stockin_id IS NULL AND order_id IS NOT NULL THEN quantity-returned_quantity ELSE 0 END),0), '
          'COALESCE(SUM(CASE WHEN stockin_id IS NULL AND order_id IS NULL THEN quantity-returned_quantity ELSE 0 END),0) '
          'FROM stock_out WHERE product_id=:p AND customer=:c', c, fetch=True)
    ship, direct = int(r[0][0]), int(r[0][1])
    avail = int(one('SELECT COALESCE(SUM(si.quantity - COALESCE(sub.consumed,0)),0) FROM stock_in si '
                    'LEFT JOIN (SELECT stockin_id, SUM(quantity-returned_quantity) consumed FROM stock_out '
                    'WHERE stockin_id IS NOT NULL GROUP BY stockin_id) sub ON sub.stockin_id=si.id '
                    'WHERE si.product_id=:p AND si.customer=:c', c))
    pack = int(one("SELECT COALESCE(SUM(quantity),0) FROM daily_production_record WHERE product_id=:p AND department='packaging'", {'p': pid}))
    logship = int(one("SELECT COALESCE(SUM(change_quantity),0) FROM inventory_log WHERE product_id=:p "
                      "AND change_type IN ('出库','出库修改','出库删除','退货','退货取消')", {'p': pid}))
    remaining = max(0, ord_qty - direct - ship)
    return {'订单数量': remaining, '备货数量': avail, '出货数量': direct + ship,
            '总订单': avail + remaining, '库存结余': pack + logship}


def cleanup():
    pids = [r[0] for r in q("SELECT id FROM product WHERE name LIKE 'ZZTEST_CMP%'", fetch=True)]
    oids = [r[0] for r in q('SELECT id FROM "order" WHERE customer=:c', {'c': CUST}, fetch=True)]
    pset = f"({','.join(map(str, pids))})" if pids else '(NULL)'
    oset = f"({','.join(map(str, oids))})" if oids else '(NULL)'
    for sql in (f'DELETE FROM stock_return WHERE product_id IN {pset}',
                f'DELETE FROM inventory_log WHERE product_id IN {pset}',
                f'DELETE FROM daily_production_record WHERE product_id IN {pset}',
                'DELETE FROM stock_out WHERE customer=:c', 'DELETE FROM stock_in WHERE customer=:c',
                f'DELETE FROM order_item WHERE order_id IN {oset}', 'DELETE FROM "order" WHERE customer=:c',
                f'DELETE FROM product_customer WHERE product_id IN {pset}',
                f'DELETE FROM product WHERE id IN {pset}', 'DELETE FROM customer WHERE name=:c'):
        with contextlib.suppress(Exception):
            q(sql, {'c': CUST})


def run(label, return_target):
    print('\n' + '=' * 74)
    print(f'场景 {label}')
    print('=' * 74)
    name = f'ZZTEST_CMP-{return_target}'
    post = client.post
    post('/api/v1/customers/create', json={'name': CUST, 'note': 'ZZTEST_CMP'})
    cid = q('SELECT id FROM customer WHERE name=:n ORDER BY id DESC LIMIT 1', {'n': CUST}, fetch=True)[0][0]
    post('/api/v1/products/create', json={'name': name, 'barcode': f'CMP{return_target}', 'price': 1, 'initial_stock': 0, 'customer_ids': [cid]})
    pid = q('SELECT id FROM product WHERE name=:n ORDER BY id DESC LIMIT 1', {'n': name}, fetch=True)[0][0]

    steps = [
        ('下单 10000', lambda: post('/api/v1/orders/create', json={'product_id': pid, 'quantity': 10000, 'customer': CUST, 'note': 'ZZTEST_CMP'})),
        ('备货入库 10000', lambda: post('/api/v1/stock/in/create', json={'product_id': pid, 'quantity': 10000, 'customer': CUST, 'stockin_date': '2026-06-01', 'note': 'ZZTEST_CMP'})),
        ('新订单 5000', lambda: post('/api/v1/orders/create', json={'product_id': pid, 'quantity': 5000, 'customer': CUST, 'note': 'ZZTEST_CMP'})),
        ('抵扣 5000', lambda: client.put(f"/api/v1/orders/deduct/{q('SELECT id FROM \"order\" WHERE customer=:c ORDER BY id DESC LIMIT 1', {'c': CUST}, fetch=True)[0][0]}", params={'deduct_quantity': 5000})),
        ('包装入库 15000', lambda: post('/api/v1/daily-production/records', json={'department': 'packaging', 'product_id': pid, 'product_name': name, 'barcode': f'CMP{return_target}', 'unit_price': 0, 'quantity': 15000, 'production_date': '2026-06-01', 'remark': 'ZZTEST_CMP'})),
        ('出货 10000', lambda: post('/api/v1/stock/out/create', json={'product_id': pid, 'quantity': 10000, 'customer': CUST, 'stockout_date': '2026-06-01', 'note': 'ZZTEST_CMP'})),
    ]
    for desc, fn in steps:
        fn()
        print(f'  {desc:<16} {stock_cols(pid)}')

    before = stock_cols(pid)
    # 退货 1000：A 退【出货单】；B 退【抵扣行】
    if return_target == 'ship':
        sid = q('SELECT id FROM stock_out WHERE product_id=:p AND customer=:c AND stockin_id IS NULL '
                'AND quantity-returned_quantity >= 1000 ORDER BY id DESC LIMIT 1', {'p': pid, 'c': CUST}, fetch=True)[0][0]
        who = '出货单'
    else:
        sid = q('SELECT id FROM stock_out WHERE product_id=:p AND customer=:c AND stockin_id IS NOT NULL '
                'AND quantity-returned_quantity >= 1000 ORDER BY id DESC LIMIT 1', {'p': pid, 'c': CUST}, fetch=True)[0][0]
        who = '抵扣行'
    post('/api/v1/stock-returns/create', json={'stockout_id': sid, 'quantity': 1000, 'return_date': '2026-06-01', 'reason': 'ZZTEST_CMP', 'note': 'ZZTEST_CMP'})
    after = stock_cols(pid)
    print(f'  {"退货1000(退" + who + ")":<16} {after}')
    print(f'  → 退货前结余={before["库存结余"]}  退货后结余={after["库存结余"]}  变化={after["库存结余"] - before["库存结余"]:+d}')
    return before, after


print('=' * 74)
print('对比：同一套操作，退货退【出货】 vs 退【抵扣】')
print('=' * 74)
cleanup()
run('A：退货退的是【出货单】（你点界面能选到的）', 'ship')
run('B：退货退的是【抵扣行】（界面选不到，只能走接口）', 'deduct')
cleanup()
print('\n已清理 ZZTEST_CMP 测试数据。')
print('=' * 74)
