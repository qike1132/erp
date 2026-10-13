"""ZZTEST Phase 0 标定脚本（1 客户 / 1 SKU / 1 单 最小闭环）

目的：走真实 HTTP 接口跑通「生产入库 → 备货入库 → 下单 → 抵扣备货 → 出货」，
      逐步 dump 原始台账，再读 /stock 与 /report，用于**冻结期望值口径**。

- 必须**提权**运行（根 .env 的 ACL 挡非提权进程，`load_dotenv` 会 PermissionError）。
- 必须显式授权写生产库：`ERP_ALLOW_PROD_WRITE=1` 或 `--allow-prod-write`。
- 所有测试数据打 `ZZTEST_` 标记；重跑前自动清理既有 ZZTEST 数据（幂等）。
- 本脚本**只读诊断 + 写入打标记的测试数据**；不碰任何非 ZZTEST 业务数据。

输出：logs/_zztest_phase0.log（UTF-8，主日志）+ 控制台。
"""
from __future__ import annotations

import contextlib
import hashlib
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'scripts'))

with contextlib.suppress(Exception):
    sys.stdout.reconfigure(encoding='utf-8')  # type: ignore[union-attr]

LOG_PATH = ROOT / 'logs' / '_zztest_phase0.log'
_fh = open(LOG_PATH, 'w', encoding='utf-8')  # noqa: SIM115


def log(*a):
    s = ' '.join(str(x) for x in a)
    print(s)
    _fh.write(s + '\n')
    _fh.flush()


def sec(t):
    log('')
    log('=' * 78)
    log(t)
    log('=' * 78)


# ---- 写生产库护栏（fail-closed）----
from _prod_write_guard import require_prod_write_consent

require_prod_write_consent(
    'ZZTEST Phase 0 标定：向生产库写入 1 客户 / 1 SKU / 1 单 全流程测试数据',
    hint='测试数据打 ZZTEST 前缀；测后需按标记清除',
)

import httpx
from sqlalchemy import create_engine, text

from fastapi_app.core.auth.token import create_access_token
from fastapi_app.core.config import settings

# ============================ 参数 ============================
BASE_URL = 'http://127.0.0.1:5002'
CUST = 'ZZTEST_客户A'
PROD = 'ZZTEST-SKU-01'
BARCODE = 'ZZTEST690000000001'
PRICE = 99.99
DAY = '2026-05-01'          # 回填业务日（过去日期）
QTY_PROD = 1000             # 包装部生产（喂结余列 + 抬 current_stock）
QTY_STOCKIN = 500           # 备货入库（抬 current_stock + 记「入库」流水）
QTY_ORDER = 300             # 下单
QTY_DEDUCT = 300            # 抵扣备货（从备货 FIFO 扣）
QTY_SHIP = 300              # 出货（受结余闸门 + 订单余量闸门）

engine = create_engine(settings.DATABASE_URL, pool_pre_ping=True)


# ============================ DB 助手 ============================
def db_exec(sql, params=None, fetch=False):
    with engine.begin() as c:
        r = c.execute(text(sql), params or {})
        return r.fetchall() if fetch else r.rowcount


def _idlist(ids):
    return ','.join(str(int(i)) for i in ids)


def get_cid():
    r = db_exec('SELECT id FROM customer WHERE name=:n ORDER BY id DESC LIMIT 1', {'n': CUST}, fetch=True)
    return r[0][0] if r else None


def get_pid():
    r = db_exec('SELECT id FROM product WHERE name=:n ORDER BY id DESC LIMIT 1', {'n': PROD}, fetch=True)
    return r[0][0] if r else None


def get_oid():
    r = db_exec('SELECT id FROM "order" WHERE customer=:c ORDER BY id DESC LIMIT 1', {'c': CUST}, fetch=True)
    return r[0][0] if r else None


# ============================ HTTP 助手 ============================
def mint_token():
    rows = db_exec('SELECT id FROM "user" WHERE username=:u', {'u': 'admin'}, fetch=True)
    if not rows:
        rows = db_exec('SELECT id FROM "user" WHERE is_super IS TRUE ORDER BY id LIMIT 1', fetch=True)
    if not rows:
        raise SystemExit('找不到 admin/超管账号，无法铸 token')
    uid = rows[0][0]
    return create_access_token({'sub': str(uid)}), uid


def pick_origin():
    origins = [o for o in (settings.BACKEND_CORS_ORIGINS or []) if isinstance(o, str) and o]
    return origins[0] if origins else 'http://127.0.0.1:3000'


def call(method, path, **kw):
    try:
        r = client.request(method, path, **kw)
    except Exception as e:  # noqa: BLE001
        log(f'  !! {method} {path} EXC {type(e).__name__}: {e}')
        return None
    body = r.text[:500].replace('\n', ' ')
    log(f'  -> {method} {path}  [{r.status_code}] {body}')
    return r


# ============================ 台账 dump ============================
def dump_ledger(tag):
    log(f'\n--- LEDGER @ {tag} ---')
    pid = get_pid()
    if pid:
        r = db_exec('SELECT current_stock, version FROM product WHERE id=:p', {'p': pid}, fetch=True)
        if r:
            log(f'  product   : id={pid} current_stock={r[0][0]} version={r[0][1]}')
    for r in db_exec('SELECT id, order_no, quantity, status, order_date FROM "order" WHERE customer=:c ORDER BY id', {'c': CUST}, fetch=True):
        log(f'  order     : id={r[0]} no={r[1]} qty={r[2]} status={r[3]} date={r[4]}')
    for r in db_exec('SELECT oi.id, oi.order_id, oi.product_id, oi.quantity FROM order_item oi JOIN "order" o ON o.id=oi.order_id WHERE o.customer=:c', {'c': CUST}, fetch=True):
        log(f'  order_item: id={r[0]} order={r[1]} pid={r[2]} qty={r[3]}')
    for r in db_exec('SELECT id, stockin_no, quantity, stockin_date FROM stock_in WHERE customer=:c', {'c': CUST}, fetch=True):
        log(f'  stock_in  : id={r[0]} no={r[1]} qty={r[2]} date={r[3]}')
    for r in db_exec('SELECT id, stockout_no, quantity, returned_quantity, order_id, stockin_id, stockout_date FROM stock_out WHERE customer=:c ORDER BY id', {'c': CUST}, fetch=True):
        log(f'  stock_out : id={r[0]} no={r[1]} qty={r[2]} ret={r[3]} order={r[4]} stockin={r[5]} date={r[6]}')
    if pid:
        for r in db_exec('SELECT id, change_type, change_quantity, related_id FROM inventory_log WHERE product_id=:p ORDER BY id', {'p': pid}, fetch=True):
            log(f'  inv_log   : {r[1]:<8} {r[2]:>8} rel={r[3]}')
        for r in db_exec('SELECT id, department, quantity, production_date FROM daily_production_record WHERE product_id=:p', {'p': pid}, fetch=True):
            log(f'  prod_rec  : {r[1]:<10} qty={r[2]} date={r[3]}')


# ============================ 期望值推导（独立 SQL）============================
def derive():
    pid = get_pid()
    d = {}
    r = db_exec('SELECT COALESCE(SUM(oi.quantity),0) FROM order_item oi JOIN "order" o ON o.id=oi.order_id '
                'WHERE o.customer=:c AND o.is_deleted IS NOT TRUE', {'c': CUST}, fetch=True)
    d['ord'] = int(r[0][0])
    r = db_exec('SELECT '
                'COALESCE(SUM(CASE WHEN stockin_id IS NOT NULL THEN quantity-returned_quantity ELSE 0 END),0), '
                'COALESCE(SUM(CASE WHEN stockin_id IS NULL AND order_id IS NOT NULL THEN quantity-returned_quantity ELSE 0 END),0), '
                'COALESCE(SUM(CASE WHEN stockin_id IS NULL AND order_id IS NULL THEN quantity-returned_quantity ELSE 0 END),0) '
                'FROM stock_out WHERE customer=:c', {'c': CUST}, fetch=True)
    d['ded'], d['ship'], d['direct_ship'] = int(r[0][0]), int(r[0][1]), int(r[0][2])
    r = db_exec('SELECT COALESCE(SUM(si.quantity - COALESCE(sub.consumed,0)),0) FROM stock_in si '
                'LEFT JOIN (SELECT stockin_id, SUM(quantity-returned_quantity) consumed FROM stock_out '
                'WHERE stockin_id IS NOT NULL GROUP BY stockin_id) sub ON sub.stockin_id=si.id '
                'WHERE si.customer=:c', {'c': CUST}, fetch=True)
    d['stockin_avail'] = int(r[0][0])
    r = db_exec("SELECT COALESCE(SUM(quantity),0) FROM daily_production_record WHERE product_id=:p AND department='packaging'", {'p': pid}, fetch=True)
    d['pack'] = int(r[0][0])
    r = db_exec("SELECT COALESCE(SUM(change_quantity),0) FROM inventory_log WHERE product_id=:p "
                "AND change_type IN ('出库','出库修改','出库删除','退货','退货取消')", {'p': pid}, fetch=True)
    d['logship'] = int(r[0][0])
    d['balance'] = d['pack'] + d['logship']
    d['remaining'] = max(0, d['ord'] - d['direct_ship'] - d['ship'])
    d['total_stock'] = d['stockin_avail'] + d['remaining']
    return d


# ============================ 写库前全库备份 ============================
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
    sec('BACKUP 写库前全库 pg_dump（custom 格式 + 归档校验）')
    u = urlparse(str(settings.DATABASE_URL))
    host, port = u.hostname or 'localhost', u.port or 5432
    user, pw = u.username or '', u.password or ''
    db = (u.path or '').lstrip('/')
    pg_dump = find_pg_dump()
    if not pg_dump:
        log('  !! 找不到 pg_dump，中止：不允许无备份写库'); sys.exit(3)
    outdir = ROOT / 'backups' / 'zztest'
    outdir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime('%Y%m%d_%H%M%S')
    dump = outdir / f'erp_system_pre_phase0_{ts}.dump'
    env = os.environ.copy()
    env['PGPASSWORD'] = pw
    log(f'  pg_dump -h {host} -p {port} -U {user} -d {db}  ->  {dump}')
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
        log(f'  归档校验通过（{len(chk.stdout.decode("utf-8", "replace").splitlines())} 目录项）')
    size_mb = dump.stat().st_size / 1048576
    digest = hashlib.sha256(dump.read_bytes()).hexdigest()
    log(f'  大小: {size_mb:.1f} MB  耗时 {(datetime.now() - t0).total_seconds():.0f}s')
    log(f'  sha256: {digest}')
    return str(dump)


# ============================ 清理（幂等，供重跑）============================
def cleanup():
    sec('CLEANUP 清除既有 ZZTEST 数据（幂等）')
    pids = [r[0] for r in db_exec("SELECT id FROM product WHERE name LIKE 'ZZTEST%'", fetch=True)]
    oids = [r[0] for r in db_exec('SELECT id FROM "order" WHERE customer=:c', {'c': CUST}, fetch=True)]
    pset = f'({_idlist(pids)})' if pids else '(NULL)'
    oset = f'({_idlist(oids)})' if oids else '(NULL)'

    stmts = [
        ('stock_return', f'DELETE FROM stock_return WHERE product_id IN {pset}'),
        ('inventory_log', f'DELETE FROM inventory_log WHERE product_id IN {pset}'),
        ('daily_production_record', f'DELETE FROM daily_production_record WHERE product_id IN {pset}'),
        ('stock_out', "DELETE FROM stock_out WHERE customer=:c"),
        ('stock_in', "DELETE FROM stock_in WHERE customer=:c"),
        ('order_item', f'DELETE FROM order_item WHERE order_id IN {oset}'),
        ('approval_request', f'DELETE FROM approval_request WHERE order_id IN {oset}'),
        ('order', 'DELETE FROM "order" WHERE customer=:c'),
        ('product_customer', f'DELETE FROM product_customer WHERE product_id IN {pset}'),
        ('product', f'DELETE FROM product WHERE id IN {pset}'),
        ('customer', 'DELETE FROM customer WHERE name=:c'),
    ]
    for name, sql in stmts:
        try:
            n = db_exec(sql, {'c': CUST})
            log(f'  {name:<24} {n} 行')
        except Exception as e:  # noqa: BLE001
            log(f'  {name:<24} skip: {type(e).__name__}: {str(e)[:120]}')
    try:
        db_exec('DELETE FROM packaging_record WHERE product_name LIKE :x', {'x': 'ZZTEST%'})
    except Exception as e:  # noqa: BLE001
        log(f'  packaging_record         skip: {str(e)[:80]}')


# ============================ 主流程 ============================
client = None  # set in main


def main():
    global client
    sec(f'ZZTEST Phase 0 START {datetime.now().isoformat()}')
    log(f'DB        : {str(settings.DATABASE_URL).split("@")[-1]}')
    log(f'BASE_URL  : {BASE_URL}')

    token, uid = mint_token()
    origin = pick_origin()
    log(f'admin_uid : {uid}')
    log(f'origin    : {origin}')
    log(f'cors      : {settings.BACKEND_CORS_ORIGINS}')
    client = httpx.Client(base_url=BASE_URL, timeout=30, trust_env=False,
                          headers={'Authorization': f'Bearer {token}', 'Origin': origin})

    # 探活
    call('GET', '/api/health')

    backup()          # 写库前全库备份（失败即中止）
    cleanup()

    sec('STEP 1 建客户')
    call('POST', '/api/v1/customers/create', json={'name': CUST, 'contact': 'ZZTEST', 'note': 'ZZTEST'})
    cid = get_cid()
    log(f'  customer id = {cid}')

    sec('STEP 2 建产品/SKU')
    call('POST', '/api/v1/products/create', json={
        'name': PROD, 'barcode': BARCODE, 'price': PRICE, 'initial_stock': 0,
        'customer_ids': [cid] if cid else []})
    pid = get_pid()
    log(f'  product id = {pid}')
    dump_ledger('after create')

    sec('STEP 3 生产入库（包装部 packaging，喂结余 + 抬库存）')
    call('POST', '/api/v1/daily-production/records', json={
        'department': 'packaging', 'product_id': pid, 'product_name': PROD, 'barcode': BARCODE,
        'unit_price': 0, 'quantity': QTY_PROD, 'production_date': DAY, 'remark': 'ZZTEST'})
    dump_ledger('after production')

    sec('STEP 4 备货入库')
    call('POST', '/api/v1/stock/in/create', json={
        'product_id': pid, 'quantity': QTY_STOCKIN, 'customer': CUST, 'stockin_date': DAY, 'note': 'ZZTEST'})
    dump_ledger('after stockin')

    sec('STEP 5 下单 + 回填 order_date')
    call('POST', '/api/v1/orders/create', json={
        'product_id': pid, 'quantity': QTY_ORDER, 'customer': CUST, 'note': 'ZZTEST'})
    oid = get_oid()
    log(f'  order id = {oid}')
    n = db_exec('UPDATE "order" SET order_date=:d WHERE id=:o AND customer=:c',
                {'d': DAY + ' 12:00:00', 'o': oid, 'c': CUST})
    log(f'  backfill order_date -> {DAY}  ({n} 行)')
    dump_ledger('after order + backfill')

    sec('STEP 6 抵扣备货 + 回填抵扣 stockout_date')
    call('PUT', f'/api/v1/orders/deduct/{oid}', params={'deduct_quantity': QTY_DEDUCT})
    n = db_exec('UPDATE stock_out SET stockout_date=:d WHERE order_id=:o AND stockin_id IS NOT NULL AND customer=:c',
                {'d': DAY + ' 12:00:00', 'o': oid, 'c': CUST})
    log(f'  backfill deduction stockout_date -> {DAY}  ({n} 行)')
    dump_ledger('after deduct + backfill')

    sec('STEP 7 出货')
    call('POST', '/api/v1/stock/out/create', json={
        'product_id': pid, 'quantity': QTY_SHIP, 'customer': CUST, 'stockout_date': DAY, 'note': 'ZZTEST'})
    dump_ledger('after ship')

    sec('STEP 8 读三路由（/stock /report /purchase）')
    call('GET', '/api/v1/stock/inventory', params={'customer': CUST, 'product': PROD})
    for t in ('order-logs', 'stockin-logs', 'stockout-logs', 'deduction-logs', 'return-logs'):
        call('GET', f'/api/v1/reports/{t}', params={'customer': CUST, 'product': PROD})
    call('GET', '/api/v1/purchase-center/unprocessed-orders', params={'page': 1, 'per_page': 15})

    sec('STEP 9 期望值（独立推导 SQL）')
    try:
        d = derive()
        log(json.dumps(d, ensure_ascii=False, indent=2))
    except Exception as e:  # noqa: BLE001
        log(f'  derive 失败: {type(e).__name__}: {e}')

    sec(f'ZZTEST Phase 0 DONE {datetime.now().isoformat()}')
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
