"""ZZTEST Phase 1+2 批量脚本（50 SKU × 180 天 全流程，按 SKU 多线程并行）

在 Phase 0 冻结口径的基础上，批量跑「生产入库 → 备货入库 → 下单 → 抵扣备货 → 出货」，
按天回填日期，并注入**预期失败**的边界用例；最后把 /stock 与 /report 读数
与**从原始台账独立推导的期望值**逐项对账。

并行策略：**每个 SKU 一个任务**（一个线程跑完该 SKU 的整条时间线）。
不同 SKU = 不同 product_id → 备货/订单/产品行锁互不相交，无跨 SKU 竞争；
httpx.Client 与 SQLAlchemy 引擎均线程安全；编号计数器由应用自身并发保护。

- 必须**提权**运行（根 .env 的 ACL 挡非提权进程）。
- 必须显式授权写生产库：`ERP_ALLOW_PROD_WRITE=1` 或 `--allow-prod-write`。
- 全部数据打 `ZZTEST_` 标记；开头先清既有 ZZTEST 数据（幂等）。
- 日期回填：订单 order_date 与抵扣 stockout_date 直连 DB 回填（**当日中午**避免 UTC 跨日）。

用法：
    python scripts/zztest_batch.py --smoke              # 5 SKU × 7 天
    python scripts/zztest_batch.py --days 180 --skus 50 --workers 16

输出：logs/_zztest_batch.log（UTF-8）
"""
from __future__ import annotations

import argparse
import contextlib
import hashlib
import os
import random
import shutil
import subprocess
import sys
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'scripts'))

with contextlib.suppress(Exception):
    sys.stdout.reconfigure(encoding='utf-8')  # type: ignore[union-attr]

LOG_PATH = ROOT / 'logs' / '_zztest_batch.log'
_fh = open(LOG_PATH, 'w', encoding='utf-8')  # noqa: SIM115
_log_lock = threading.Lock()


def log(*a):
    s = ' '.join(str(x) for x in a)
    with _log_lock:
        print(s)
        _fh.write(s + '\n')
        _fh.flush()


def sec(t):
    log('')
    log('=' * 78)
    log(t)
    log('=' * 78)


from _prod_write_guard import require_prod_write_consent

require_prod_write_consent(
    'ZZTEST Phase 1+2 批量测试：向生产库写入 50 SKU × 180 天 全流程测试数据',
    hint='测试数据打 ZZTEST 前缀；测后需按标记清除',
)

import httpx
from sqlalchemy import create_engine, text

from fastapi_app.core.auth.token import create_access_token
from fastapi_app.core.config import settings

BASE_URL = 'http://127.0.0.1:5002'
CUST = 'ZZTEST_客户A'

engine = create_engine(settings.DATABASE_URL, pool_pre_ping=True, pool_size=20, max_overflow=20)
client: httpx.Client = None  # type: ignore[assignment]


# ============================ DB / HTTP 助手 ============================
def db_exec(sql, params=None, fetch=False):
    with engine.begin() as c:
        r = c.execute(text(sql), params or {})
        return r.fetchall() if fetch else r.rowcount


def _idlist(ids):
    return ','.join(str(int(i)) for i in ids)


def q1(sql, p=None):
    r = db_exec(sql, p, fetch=True)
    return r[0] if r else None


def mint_token():
    rows = db_exec('SELECT id FROM "user" WHERE username=:u', {'u': 'admin'}, fetch=True)
    if not rows:
        rows = db_exec('SELECT id FROM "user" WHERE is_super IS TRUE ORDER BY id LIMIT 1', fetch=True)
    if not rows:
        raise SystemExit('找不到 admin/超管账号')
    return create_access_token({'sub': str(rows[0][0])}), rows[0][0]


def pick_origin():
    origins = [o for o in (settings.BACKEND_CORS_ORIGINS or []) if isinstance(o, str) and o]
    return origins[0] if origins else 'http://127.0.0.1:3000'


def call(method, path, quiet=True, **kw):
    try:
        r = client.request(method, path, **kw)
    except Exception as e:  # noqa: BLE001
        if not quiet:
            log(f'  !! {method} {path} EXC {type(e).__name__}: {e}')
        return None
    if not quiet:
        log(f'  -> {method} {path}  [{r.status_code}] {r.text[:200]}')
    return r


def ok(r):
    if r is None or r.status_code != 200:
        return False
    try:
        return bool(r.json().get('success'))
    except Exception:  # noqa: BLE001
        return False


# ============================ 备份 / 清理 ============================
def find_pg_dump():
    exe = shutil.which('pg_dump')
    if exe:
        return exe
    for cand in (r'D:\PostgreSQL\bin\pg_dump.exe',
                 r'C:\Program Files\PostgreSQL\18\bin\pg_dump.exe',
                 r'C:\Program Files\PostgreSQL\17\bin\pg_dump.exe'):
        if Path(cand).exists():
            return cand
    return None


def find_pg_restore():
    exe = shutil.which('pg_restore')
    if exe:
        return exe
    for cand in (r'D:\PostgreSQL\bin\pg_restore.exe',
                 r'C:\Program Files\PostgreSQL\18\bin\pg_restore.exe'):
        if Path(cand).exists():
            return cand
    return None


def backup():
    sec('BACKUP 写库前全库 pg_dump')
    u = urlparse(str(settings.DATABASE_URL))
    host, port = u.hostname or 'localhost', u.port or 5432
    user, pw = u.username or '', u.password or ''
    db = (u.path or '').lstrip('/')
    pg_dump = find_pg_dump()
    if not pg_dump:
        log('  !! 找不到 pg_dump，中止'); sys.exit(3)
    outdir = ROOT / 'backups' / 'zztest'
    outdir.mkdir(parents=True, exist_ok=True)
    dump = outdir / f'erp_system_pre_batch_{datetime.now():%Y%m%d_%H%M%S}.dump'
    env = os.environ.copy()
    env['PGPASSWORD'] = pw
    t0 = datetime.now()
    p = subprocess.run([pg_dump, '-h', host, '-p', str(port), '-U', user, '-d', db,
                        '-F', 'c', '-Z', '6', '-f', str(dump)], capture_output=True, env=env)
    if p.returncode != 0 or not dump.exists() or dump.stat().st_size == 0:
        log(f'  !! pg_dump 失败: {p.stderr.decode("utf-8", "replace")[:400]}'); sys.exit(3)
    pg_restore = find_pg_restore()
    if pg_restore:
        chk = subprocess.run([pg_restore, '--list', str(dump)], capture_output=True, env=env)
        if chk.returncode != 0:
            log('  !! 归档校验失败'); sys.exit(3)
    log(f'  {dump}  {dump.stat().st_size / 1048576:.1f} MB  {(datetime.now() - t0).total_seconds():.0f}s')
    log(f'  sha256: {hashlib.sha256(dump.read_bytes()).hexdigest()}')


def cleanup():
    sec('CLEANUP 清除既有 ZZTEST 数据')
    pids = [r[0] for r in db_exec("SELECT id FROM product WHERE name LIKE 'ZZTEST%'", fetch=True)]
    oids = [r[0] for r in db_exec('SELECT id FROM "order" WHERE customer=:c', {'c': CUST}, fetch=True)]
    pset = f'({_idlist(pids)})' if pids else '(NULL)'
    oset = f'({_idlist(oids)})' if oids else '(NULL)'
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
            log(f'  {name:<24} {db_exec(sql, {"c": CUST})} 行')
        except Exception as e:  # noqa: BLE001
            log(f'  {name:<24} skip: {str(e)[:100]}')
    with contextlib.suppress(Exception):
        db_exec('DELETE FROM packaging_record WHERE product_name LIKE :x', {'x': 'ZZTEST%'})


# ============================ 运行期模型 ============================
class SkuModel:
    __slots__ = (
        'barcode',
        'ded_total',
        'deducted',
        'name',
        'ord_total',
        'pack',
        'pid',
        'returned',
        'ship_total',
        'shipped',
        'stockin_total',
    )

    def __init__(self, pid, name, barcode):
        self.pid = pid
        self.name = name
        self.barcode = barcode
        self.stockin_total = 0
        self.deducted = 0
        self.pack = 0
        self.shipped = 0
        self.returned = 0
        self.ord_total = 0
        self.ded_total = 0
        self.ship_total = 0

    @property
    def stockin_avail(self):
        return self.stockin_total - self.deducted

    @property
    def balance(self):
        return self.pack - self.shipped


# ============================ 单个 SKU 的整条时间线（一个线程）============================
def run_one_sku(m: SkuModel, dates, counters, lock):
    n_order = 0
    for di, d in enumerate(dates):
        ds = d.isoformat()
        oid = None
        # 生产（包装部）
        P = random.randint(800, 2500)
        if ok(call('POST', '/api/v1/daily-production/records', json={
                'department': 'packaging', 'product_id': m.pid, 'product_name': m.name,
                'barcode': m.barcode, 'unit_price': 0, 'quantity': P,
                'production_date': ds, 'remark': 'ZZTEST'})):
            m.pack += P
        # 备货入库
        S = random.randint(300, 1200)
        if ok(call('POST', '/api/v1/stock/in/create', json={
                'product_id': m.pid, 'quantity': S, 'customer': CUST, 'stockin_date': ds, 'note': 'ZZTEST'})):
            m.stockin_total += S
        # 下单
        Q = random.randint(100, 700)
        r = call('POST', '/api/v1/orders/create', json={
            'product_id': m.pid, 'quantity': Q, 'customer': CUST, 'note': 'ZZTEST'})
        if ok(r):
            rr = db_exec('SELECT id FROM "order" WHERE customer=:c AND product_id=:p ORDER BY id DESC LIMIT 1',
                         {'c': CUST, 'p': m.pid}, fetch=True)
            if rr:
                oid = rr[0][0]
                m.ord_total += Q
                n_order += 1
        # 抵扣（随机模式，受备货可用量约束）
        mode = random.choice(['shipped_full', 'shipped_partial', 'stocked_full', 'stocked_partial', 'pending'])
        if mode == 'shipped_full':
            want_D, want_Sh = Q, Q
        elif mode == 'shipped_partial':
            want_D, want_Sh = random.randint(0, Q), random.randint(1, Q)
        elif mode == 'stocked_full':
            want_D, want_Sh = Q, 0
        elif mode == 'stocked_partial':
            want_D, want_Sh = random.randint(1, max(1, Q - 1)), 0
        else:  # pending
            want_D, want_Sh = 0, 0
        D = min(want_D, Q, m.stockin_avail)
        if D > 0 and oid:
            if ok(call('PUT', f'/api/v1/orders/deduct/{oid}', params={'deduct_quantity': D})):
                m.deducted += D
                m.ded_total += D
        # 出货闸门 = 订单余量(Q − 已出货) 与 结余；本单为新单，已出货=0 → 上限 Q
        Sh = min(want_Sh, Q, m.balance)
        if Sh > 0:
            if ok(call('POST', '/api/v1/stock/out/create', json={
                    'product_id': m.pid, 'quantity': Sh, 'customer': CUST,
                    'stockout_date': ds, 'note': 'ZZTEST'})):
                m.shipped += Sh
                m.ship_total += Sh

        # 随机退货（约 20% 天数）：对某条有可退量的出货明细退一部分
        # （抵扣行 stockin_id 非空 与 独立出货 同等可退）
        if random.random() < 0.2:
            row = q1('SELECT id, quantity - returned_quantity AS avail, stockin_id FROM stock_out '
                     'WHERE product_id=:p AND customer=:c AND quantity - returned_quantity > 0 '
                     'ORDER BY random() LIMIT 1', {'p': m.pid, 'c': CUST})
            if row:
                sid, avail, sin_id = int(row[0]), int(row[1]), row[2]
                rq = random.randint(1, avail)
                if ok(call('POST', '/api/v1/stock-returns/create', json={
                        'stockout_id': sid, 'quantity': rq, 'return_date': ds,
                        'reason': 'ZZTEST', 'note': 'ZZTEST'})):
                    if sin_id is not None:
                        m.deducted -= rq      # 抵扣行退货：占用减少 → 备货可用增加
                    else:
                        m.shipped -= rq       # 独立出货退货：净出货减少 → 结余增加
                    m.returned += rq
        # 回填当日 order_date + 抵扣 stockout_date（中午，避免 UTC 跨日）
        if oid:
            db_exec('UPDATE "order" SET order_date=:d WHERE id=:o', {'d': ds + ' 12:00:00', 'o': oid})
            db_exec('UPDATE stock_out SET stockout_date=:d WHERE order_id=:o AND stockin_id IS NOT NULL',
                    {'d': ds + ' 12:00:00', 'o': oid})

        # 失败用例注入（每 20 天一次）：越量出货 + 越量抵扣
        if di % 20 == 0:
            rr = call('POST', '/api/v1/stock/out/create', json={
                'product_id': m.pid, 'quantity': 9999999, 'customer': CUST,
                'stockout_date': ds, 'note': 'ZZTEST-FAIL'})
            with lock:
                counters['over_ship'] += 1
                if not ok(rr):
                    counters['over_ship_rejected'] += 1
            if oid:
                rr2 = call('PUT', f'/api/v1/orders/deduct/{oid}', params={'deduct_quantity': 9999999})
                with lock:
                    counters['over_deduct'] += 1
                    if not ok(rr2):
                        counters['over_deduct_rejected'] += 1

        if di % 30 == 0:
            log(f'  [{m.name}] day {di + 1}/{len(dates)}  {ds}  订单={n_order}')
    return n_order


# ============================ 期望值（独立推导 SQL）============================
def derive_all(models):
    exp = {}
    for m in models:
        pid = m.pid
        d = {}
        r = db_exec('SELECT COALESCE(SUM(oi.quantity),0) FROM order_item oi JOIN "order" o ON o.id=oi.order_id '
                    'WHERE o.product_id=:p AND o.customer=:c AND o.is_deleted IS NOT TRUE', {'p': pid, 'c': CUST}, fetch=True)
        d['ord'] = int(r[0][0])
        r = db_exec('SELECT '
                    'COALESCE(SUM(CASE WHEN stockin_id IS NOT NULL THEN quantity-returned_quantity ELSE 0 END),0), '
                    'COALESCE(SUM(CASE WHEN stockin_id IS NULL AND order_id IS NOT NULL THEN quantity-returned_quantity ELSE 0 END),0), '
                    'COALESCE(SUM(CASE WHEN stockin_id IS NULL AND order_id IS NULL THEN quantity-returned_quantity ELSE 0 END),0) '
                    'FROM stock_out WHERE product_id=:p AND customer=:c', {'p': pid, 'c': CUST}, fetch=True)
        d['ded'], d['ship'], d['direct'] = int(r[0][0]), int(r[0][1]), int(r[0][2])
        r = db_exec('SELECT COALESCE(SUM(si.quantity - COALESCE(sub.consumed,0)),0) FROM stock_in si '
                    'LEFT JOIN (SELECT stockin_id, SUM(quantity-returned_quantity) consumed FROM stock_out '
                    'WHERE stockin_id IS NOT NULL GROUP BY stockin_id) sub ON sub.stockin_id=si.id '
                    'WHERE si.product_id=:p AND si.customer=:c', {'p': pid, 'c': CUST}, fetch=True)
        d['stockin_avail'] = int(r[0][0])
        r = db_exec('SELECT COALESCE(SUM(quantity),0) FROM stock_in WHERE product_id=:p AND customer=:c', {'p': pid, 'c': CUST}, fetch=True)
        d['stockin_total'] = int(r[0][0])
        r = db_exec("SELECT COALESCE(SUM(quantity),0) FROM daily_production_record WHERE product_id=:p AND department='packaging'", {'p': pid}, fetch=True)
        d['pack'] = int(r[0][0])
        r = db_exec("SELECT COALESCE(SUM(change_quantity),0) FROM inventory_log WHERE product_id=:p "
                    "AND change_type IN ('出库','出库修改','出库删除','退货','退货取消')", {'p': pid}, fetch=True)
        d['logship'] = int(r[0][0])
        d['balance'] = d['pack'] + d['logship']
        d['remaining'] = max(0, d['ord'] - d['direct'] - d['ship'])
        d['total_stock'] = d['stockin_avail'] + d['remaining']
        exp[pid] = d
    return exp


def read_stock_rows():
    out = {}
    page = 1
    while True:
        r = call('GET', '/api/v1/stock/inventory', params={'customer': CUST, 'page': page, 'per_page': 200})
        if not ok(r):
            break
        j = r.json()
        for row in j.get('data', []):
            out[row['product_name']] = row
        if len(j.get('data', [])) < 200:
            break
        page += 1
    return out


def read_report_total(flow, product_name):
    r = call('GET', f'/api/v1/reports/{flow}',
             params={'customer': CUST, 'product': product_name, 'per_page': 1})
    if not ok(r):
        return None
    return int(r.json().get('stats', {}).get('total_quantity', 0))


def read_stock_totals():
    """/stock 顶部聚合（客户维度）：订单数量 / 备货数量 / 总订单。"""
    r = call('GET', '/api/v1/stock/inventory', params={'customer': CUST, 'per_page': 1})
    if not ok(r):
        return None
    j = r.json()
    return {'order': int(j.get('total_order_quantity', 0) or 0),
            'stockin': int(j.get('total_stockin_quantity', 0) or 0),
            'stock': int(j.get('total_stock', 0) or 0)}


# ============================ 主流程 ============================
def main():
    global client
    ap = argparse.ArgumentParser()
    ap.add_argument('--days', type=int, default=180)
    ap.add_argument('--skus', type=int, default=50)
    ap.add_argument('--workers', type=int, default=16)
    ap.add_argument('--smoke', action='store_true', help='5 SKU × 7 天')
    args = ap.parse_args()
    days = 7 if args.smoke else args.days
    nskus = 5 if args.smoke else args.skus
    workers = 4 if args.smoke else args.workers

    sec(f'ZZTEST BATCH START {datetime.now().isoformat()}  days={days} skus={nskus} workers={workers}')
    log(f'DB: {str(settings.DATABASE_URL).split("@")[-1]}')

    token, uid = mint_token()
    origin = pick_origin()
    log(f'admin_uid={uid} origin={origin}')
    client = httpx.Client(base_url=BASE_URL, timeout=60, trust_env=False,
                          headers={'Authorization': f'Bearer {token}', 'Origin': origin})
    call('GET', '/api/health')

    backup()
    cleanup()

    sec('建客户')
    call('POST', '/api/v1/customers/create', json={'name': CUST, 'contact': 'ZZTEST', 'note': 'ZZTEST'})
    r = db_exec('SELECT id FROM customer WHERE name=:n ORDER BY id DESC LIMIT 1', {'n': CUST}, fetch=True)
    cid = r[0][0] if r else None
    log(f'  customer id = {cid}')

    sec(f'建 {nskus} 个 SKU')
    models = []
    for i in range(1, nskus + 1):
        name = f'ZZTEST-SKU-{i:02d}'
        bc = f'ZZTEST69{i:010d}'
        price = round(random.uniform(10, 500), 2)
        call('POST', '/api/v1/products/create', json={
            'name': name, 'barcode': bc, 'price': price, 'initial_stock': 0,
            'customer_ids': [cid] if cid else []})
        rr = db_exec('SELECT id FROM product WHERE name=:n ORDER BY id DESC LIMIT 1', {'n': name}, fetch=True)
        pid = rr[0][0] if rr else None
        models.append(SkuModel(pid, name, bc))
        log(f'  {name}  id={pid}  price={price}')
    if any(m.pid is None for m in models):
        log('  !! 有 SKU 未建成功，中止'); sys.exit(4)

    end = date.today() - timedelta(days=1)
    start = end - timedelta(days=days - 1)
    dates = [start + timedelta(days=k) for k in range(days)]
    log(f'日期窗口: {dates[0]} .. {dates[-1]}  ({days} 天)  workers={workers}')

    counters = {'over_ship': 0, 'over_ship_rejected': 0, 'over_deduct': 0, 'over_deduct_rejected': 0}
    lock = threading.Lock()
    t0 = datetime.now()
    n_order = 0
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = [ex.submit(run_one_sku, m, dates, counters, lock) for m in models]
        for f in as_completed(futs):
            n_order += f.result()
    sec(f'写入完成：订单={n_order}  失败用例={counters}  耗时 {(datetime.now() - t0).total_seconds():.0f}s')

    # ============================ Phase 3 核对 ============================
    sec('Phase 3 全量核对：/stock 与 /report vs 独立推导')
    exp = derive_all(models)
    stock_rows = read_stock_rows()

    def num(v):
        return int(v) if v not in ('', None) else 0

    mismatches = []
    for m in models:
        d = exp[m.pid]
        row = stock_rows.get(m.name)
        if row is None:
            if d['total_stock'] != 0:
                mismatches.append(f'{m.name}: /stock 无该行（派生 total_stock={d["total_stock"]}）')
        else:
            for field, got, want in [
                ('order_quantity', num(row.get('order_quantity')), d['remaining']),
                ('stockin_quantity', num(row.get('stockin_quantity')), d['stockin_avail']),
                ('stockout_quantity', num(row.get('stockout_quantity')), d['direct'] + d['ship']),
                ('total_stock', num(row.get('total_stock')), d['total_stock']),
                ('inventory_balance', num(row.get('inventory_balance')), d['balance']),
            ]:
                if got != want:
                    mismatches.append(f'{m.name}: /stock.{field} 实测={got} 期望={want}')
        for flow, want in [('order-logs', d['ord']), ('stockin-logs', d['stockin_total']),
                           ('stockout-logs', d['ship']), ('deduction-logs', d['ded'])]:
            got = read_report_total(flow, m.name)
            if got != want:
                mismatches.append(f'{m.name}: /report/{flow} 实测={got} 期望={want}')

    # 全局聚合（客户维度）：/stock 页顶部「订单数量 / 备货数量 / 总订单」
    totals = read_stock_totals()
    if totals is not None:
        for label, got, want in [
            ('订单数量', totals['order'], sum(d['remaining'] for d in exp.values())),
            ('备货数量', totals['stockin'], sum(d['stockin_avail'] for d in exp.values())),
            ('总订单', totals['stock'], sum(d['total_stock'] for d in exp.values())),
        ]:
            if got != want:
                mismatches.append(f'/stock 顶部「{label}」: 实测={got} 期望={want}')

    fail_ok = (counters['over_ship_rejected'] == counters['over_ship']
               and counters['over_deduct_rejected'] == counters['over_deduct'])

    sec('核对结果')
    log(f'  SKU 数={len(models)}  订单={n_order}')
    log(f'  失败用例: {counters}  闸门全部拒绝={fail_ok}')
    if mismatches:
        log(f'  !! 发现 {len(mismatches)} 处不一致：')
        for x in mismatches[:80]:
            log(f'     - {x}')
    else:
        log('  所有 SKU 的 /stock 与 /report 读数 == 独立推导期望值（0 处不一致）')

    verdict = 'PASS' if (not mismatches and fail_ok) else 'FAIL'
    sec(f'ZZTEST BATCH {verdict}  {datetime.now().isoformat()}')
    log(f'日志: {LOG_PATH}')


if __name__ == '__main__':
    try:
        main()
    except SystemExit:
        raise
    except Exception:
        import traceback
        log('!!! 未捕获异常 !!!')
        log(traceback.format_exc())
        sys.exit(1)
    finally:
        _fh.close()
