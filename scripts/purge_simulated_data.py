"""上线前模拟数据选择性清除脚本

清除范围（业务模拟数据）:
  板房管理 / 湖北订单(含湖北外发) / 采购中心 / 核心业务 / 订单查询派生数据 /
  系统管理(版本管理、审计日志、监控指标、备份历史)

保留范围（禁止任何清除）:
  用户管理: user / user_permission / permission
  客户管理: customer / customer_access_log / country
  运行配置: backup_settings / backup_schedule / order_sync_config / alembic_version

执行流程:
  [1/6] pg_dump 全库备份（custom 格式）+ 归档完整性校验 + sha256
  [2/6] 保留表快照（行数 + 内容 MD5）
  [3/6] 单事务按外键顺序 DELETE 待清除表
  [4/6] 刷新物化视图 + 清理 Redis 缓存
  [5/6] 复核已清除表（必须为 0 行）
  [6/6] 复核保留表（行数 + 内容 MD5 必须与快照一致）

用法:
    python scripts/purge_simulated_data.py --dry-run     # 只预览范围，不写任何数据
    python scripts/purge_simulated_data.py --execute     # 备份 -> 清除 -> 复核（需输入 CONFIRM）
    python scripts/purge_simulated_data.py --execute --yes
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from fastapi_app.core.config import settings

# ---------------------------------------------------------------------------
# 保留表：用户管理 + 客户管理 + 运行配置，脚本绝不触碰
# ---------------------------------------------------------------------------
KEEP_TABLES = [
    'user',
    'user_permission',
    'permission',
    'customer',
    'customer_access_log',
    'country',
    'backup_settings',
    'backup_schedule',
    'order_sync_config',
    'alembic_version',
]

# ---------------------------------------------------------------------------
# 待清除表：严格按外键依赖排序（子表在前、父表在后），保证单事务内不会触发约束冲突
# ---------------------------------------------------------------------------
CLEAR_TABLES = [
    # 板房管理
    'customer_sampling_change_log',
    'customer_sampling_fabric_version',
    'customer_sampling_part',
    'customer_sampling_role',
    'customer_sampling_project',
    'pattern_maker',
    'product_image_orphan_backup',
    'file_records',
    # 核心业务 - 库存与出库
    'stock_return',
    'stock_out',
    'stock_in',
    'inventory_log',
    # 核心业务 - 皮套管理
    'case_movement',
    'case',
    # 核心业务 - 订单附属
    'notification',
    'approval_log',
    'approval_request',
    # 湖北订单 - 湖北外发
    'outsource_shipment_item',
    'outsource_shipment',
    'order_outsource_process_flow',
    'order_outsource_process',
    'outsource_process_type',
    # 核心业务 - 订单
    'order_item',
    'order_status_log',
    'order_batch_audit_log',
    'order_sync_record',
    'sync_retry_queue',
    'order',
    # 核心业务 - 批量导入暂存
    'staging_stock_out',
    'staging_stock_in',
    'staging_order',
    'staging_purchase_plan',
    # 核心业务 - 生产
    'production_plan_log',
    'production_plan',
    'daily_production_record',
    'craft_work',
    'packaging_record',
    # 采购中心 - 采购计划（引用 product，须在 product 之前删除）
    'purchase_plan_details',
    'purchase_plans',
    # 核心业务 - 产品与 BOM（product_packaging 已删，见迁移 pg_standalone_054）
    'product_accessory',
    'product_fabric',
    'product_material',
    'product_role',
    'product',
    # 采购中心
    'material_registration_item',
    'material_registration',
    'purchase_order_sku',
    'purchase_order_item',
    'purchase_order',
    'shipment_records',
    'supplier',
    'role',
    'modification_log',
    'saved_query',
    # 系统管理（用户管理/客户管理/备份配置除外）
    'app_version',
    'audit_log',
    'web_vital',
    'backup_record',
    # 编号计数器（重置，上线后单号从 001 重新开始）
    'numbering_counter',
]

MATERIALIZED_VIEWS = [
    'mv_daily_order_quantity',
    'mv_daily_stockin_quantity',
    'mv_daily_stockout_quantity',
    'mv_product_aggregate',
]

# 应用缓存物理键统一为 `erp:<业务键>`（见 utils/redis_cache.py::_make_key），
# 故按 `erp:*` 整体清理即可；token 黑名单键为 `token_blacklist:<jti>`（无前缀），不受影响。
REDIS_KEY_PATTERNS = [
    'erp:*',
]


def _q(name: str) -> str:
    """标识符引用（表名均为脚本内硬编码常量）"""
    return '"' + name.replace('"', '""') + '"'


def _engine():
    return create_engine(settings.DATABASE_URL)


def _count(db: Session, table: str) -> int:
    return db.execute(text(f'SELECT COUNT(*) FROM {_q(table)}')).scalar() or 0


def _snapshot(db: Session, table: str) -> dict:
    """行数 + 内容指纹（按行 MD5 排序后聚合，与物理顺序无关）"""
    row = db.execute(text(
        f'SELECT COUNT(*), COALESCE(MD5(STRING_AGG(h, \'\' ORDER BY h)), \'\') '
        f'FROM (SELECT MD5(t::text) AS h FROM {_q(table)} t) s'
    )).one()
    return {'rows': int(row[0]), 'md5': row[1]}


def _find_pg_dump() -> str:
    exe = shutil.which('pg_dump')
    if exe:
        return exe
    for cand in (r'D:\PostgreSQL\bin\pg_dump.exe',
                 r'C:\Program Files\PostgreSQL\18\bin\pg_dump.exe',
                 r'C:\Program Files\PostgreSQL\17\bin\pg_dump.exe'):
        if Path(cand).exists():
            return cand
    raise RuntimeError('未找到 pg_dump，可将其加入 PATH 或安装 PostgreSQL 客户端')


def _find_pg_restore() -> str | None:
    exe = shutil.which('pg_restore')
    if exe:
        return exe
    for cand in (r'D:\PostgreSQL\bin\pg_restore.exe',
                 r'C:\Program Files\PostgreSQL\18\bin\pg_restore.exe'):
        if Path(cand).exists():
            return cand
    return None


def backup_database(backup_dir: Path) -> dict:
    print('\n' + '=' * 78)
    print('  [1/6] 全库备份（pg_dump）')
    print('=' * 78)

    backup_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime('%Y%m%d_%H%M%S')
    dump_path = backup_dir / f'erp_system_full_{ts}.dump'

    host = os.getenv('DB_HOST', 'localhost')
    port = os.getenv('DB_PORT', '5432')
    user = os.getenv('DB_USER', 'erp_app')
    dbname = os.getenv('DB_NAME', 'erp_system')

    env = os.environ.copy()
    env['PGPASSWORD'] = os.getenv('DB_PASSWORD', '')

    cmd = [_find_pg_dump(), '-h', host, '-p', port, '-U', user, '-d', dbname,
           '-F', 'c', '-Z', '6', '-f', str(dump_path)]
    print(f'  执行: pg_dump -h {host} -p {port} -U {user} -d {dbname} -F c -Z 6')
    proc = subprocess.run(cmd, capture_output=True, env=env)
    if proc.returncode != 0:
        raise RuntimeError(f'pg_dump 失败: {proc.stderr.decode("utf-8", "replace")[:500]}')
    if not dump_path.exists() or dump_path.stat().st_size == 0:
        raise RuntimeError('pg_dump 产物为空')

    digest = hashlib.sha256(dump_path.read_bytes()).hexdigest()

    # 归档完整性校验：pg_restore --list 能列出目录项即视为归档结构完好
    pg_restore = _find_pg_restore()
    if pg_restore:
        chk = subprocess.run([pg_restore, '--list', str(dump_path)], capture_output=True, env=env)
        if chk.returncode != 0:
            raise RuntimeError('备份归档校验失败: ' + chk.stderr.decode('utf-8', 'replace')[:300])
        entries = len(chk.stdout.decode('utf-8', 'replace').splitlines())
        print(f'  归档校验通过（{entries} 个目录项）')

    size_mb = dump_path.stat().st_size / 1048576
    print(f'  备份文件 : {dump_path}')
    print(f'  大小     : {size_mb:.1f} MB')
    print(f'  sha256   : {digest}')
    return {'file': str(dump_path), 'size_bytes': dump_path.stat().st_size, 'sha256': digest}


def take_keep_snapshot(db: Session) -> dict:
    print('\n' + '=' * 78)
    print('  [2/6] 保留数据完整性快照（用户管理 / 客户管理 / 运行配置）')
    print('=' * 78)
    snap = {}
    for table in KEEP_TABLES:
        snap[table] = _snapshot(db, table)
        item = snap[table]
        print(f'  {table:<24} {item["rows"]:>8} 行   md5={item["md5"][:16]}')
    return snap


def purge(db: Session) -> dict:
    """单事务清除。

    先按 CLEAR_TABLES 的预设顺序删除；若某表仍被未删除的子表引用（外键冲突），
    该表退回到队列末尾重试（每表一个 SAVEPOINT，冲突不影响外层事务）。
    全部删除完成后再提交，保证整体原子性。
    """
    print('\n' + '=' * 78)
    print('  [3/6] 清除业务数据（单事务，外键冲突自动重排队）')
    print('=' * 78)
    deleted: dict[str, int] = {}
    # 结束前置只读事务，确保下面能开启独立写事务
    db.commit()
    with db.begin():
        pending = list(CLEAR_TABLES)
        while pending:
            remaining: list[str] = []
            for table in pending:
                try:
                    with db.begin_nested():
                        res = db.execute(text(f'DELETE FROM {_q(table)}'))
                    deleted[table] = res.rowcount or 0
                    print(f'  {table:<36} {deleted[table]:>8} 行已删除')
                except IntegrityError:
                    remaining.append(table)
            if len(remaining) == len(pending):
                raise RuntimeError(f'外键依赖无法满足，以下表无法删除: {remaining}')
            pending = remaining
    print(f'\n  合计删除 {sum(deleted.values())} 行')
    return deleted


def refresh_derived() -> dict:
    print('\n' + '=' * 78)
    print('  [4/6] 刷新物化视图 + 清理 Redis 缓存')
    print('=' * 78)
    out = {'views': {}, 'redis_keys': 0}
    with _engine().begin() as conn:
        for view in MATERIALIZED_VIEWS:
            try:
                conn.execute(text(f'REFRESH MATERIALIZED VIEW {_q(view)}'))
                out['views'][view] = 'ok'
                print(f'  OK   REFRESH {view}')
            except Exception as e:  # noqa: BLE001
                out['views'][view] = f'fail: {str(e)[:80]}'
                print(f'  WARN REFRESH {view} 失败: {str(e)[:80]}')

    try:
        import redis

        client = redis.Redis(
            host=settings.REDIS_HOST, port=settings.REDIS_PORT, db=settings.REDIS_DB,
            password=settings.REDIS_PASSWORD or None, decode_responses=True,
        )
        client.ping()
        for pattern in REDIS_KEY_PATTERNS:
            keys = list(client.scan_iter(pattern))
            if keys:
                out['redis_keys'] += client.delete(*keys)
        client.close()
        print(f'  OK   Redis 缓存已清理（{out["redis_keys"]} 个键）')
    except Exception as e:  # noqa: BLE001
        out['redis_error'] = str(e)[:200]
        print(f'  WARN Redis 不可用，跳过缓存清理: {str(e)[:120]}')
    return out


def verify_cleared(db: Session) -> dict:
    print('\n' + '=' * 78)
    print('  [5/6] 复核已清除数据（全部必须为 0 行）')
    print('=' * 78)
    failed = {}
    for table in CLEAR_TABLES:
        n = _count(db, table)
        if n != 0:
            failed[table] = n
            print(f'  FAIL {table:<36} 仍剩 {n} 行')
    if failed:
        print(f'\n  存在 {len(failed)} 张表未清空')
    else:
        print(f'  全部 {len(CLEAR_TABLES)} 张表均为 0 行')
    return failed


def verify_kept(db: Session, before: dict) -> dict:
    print('\n' + '=' * 78)
    print('  [6/6] 复核保留数据（行数 + 内容 MD5 必须与快照一致）')
    print('=' * 78)
    bad = {}
    for table in KEEP_TABLES:
        after = _snapshot(db, table)
        exp = before[table]
        ok = after['rows'] == exp['rows'] and after['md5'] == exp['md5']
        if not ok:
            bad[table] = {'before': exp, 'after': after}
        print(f'  {"OK  " if ok else "FAIL"} {table:<24} {after["rows"]:>8} 行')
    if bad:
        print('\n  以下保留表发生变化（不应发生）:')
        for name, diff in bad.items():
            print(f'    {name}: {diff}')
    else:
        print(f'\n  保留数据完整：{len(KEEP_TABLES)} 张表行数与内容指纹全部一致')
    return bad


def show_scope(db: Session) -> None:
    print('\n' + '=' * 78)
    print('  清除范围预览（本表仅统计，不修改任何数据）')
    print('=' * 78)
    total = 0
    for table in CLEAR_TABLES:
        n = _count(db, table)
        total += n
        print(f'  {table:<36} {n:>8} 行')
    print(f'\n  待清除合计 {total} 行（{len(CLEAR_TABLES)} 张表）')

    print('\n  保留数据（不会被清除）:')
    for table in KEEP_TABLES:
        print(f'  {table:<36} {_count(db, table):>8} 行')


def main() -> int:
    parser = argparse.ArgumentParser(description='上线前模拟数据选择性清除')
    parser.add_argument('--dry-run', action='store_true', help='只预览清除范围')
    parser.add_argument('--execute', action='store_true', help='执行备份+清除+复核')
    parser.add_argument('--yes', action='store_true', help='跳过二次确认')
    parser.add_argument('--backup-dir', default=str(ROOT / 'backups' / 'pre-launch-purge'),
                        help='备份与报告输出目录')
    args = parser.parse_args()

    if not args.dry_run and not args.execute:
        parser.print_help()
        print('\n请指定 --dry-run（预览）或 --execute（执行）')
        return 1

    print('=' * 78)
    print('  ERP 上线前模拟数据清除工具')
    print('=' * 78)
    print(f'  数据库: {settings.DATABASE_URL.split("@")[-1]}')
    print(f'  待清除: {len(CLEAR_TABLES)} 张表')
    print(f'  保留  : {"、".join(KEEP_TABLES)}')

    engine = _engine()
    backup_dir = Path(args.backup_dir)

    with Session(engine) as db:
        show_scope(db)
        if args.dry_run:
            print('\n（dry-run 结束，未修改任何数据）')
            return 0

        if not args.yes:
            answer = input('\n将先备份全库，再清空上述数据（不可逆）。输入 CONFIRM 继续: ')
            if answer.strip() != 'CONFIRM':
                print('已取消')
                return 1

        backup_info = backup_database(backup_dir)
        before = take_keep_snapshot(db)
        deleted = purge(db)
        derived = refresh_derived()
        cleared_fail = verify_cleared(db)
        kept_fail = verify_kept(db, before)

    report = {
        'executed_at': datetime.now().isoformat(),
        'database': settings.DATABASE_URL.split('@')[-1],
        'backup': backup_info,
        'keep_snapshot': before,
        'deleted_rows': deleted,
        'derived': derived,
        'cleared_remaining': cleared_fail,
        'kept_changed': kept_fail,
    }
    report_path = backup_dir / f'purge_report_{datetime.now().strftime("%Y%m%d_%H%M%S")}.json'
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')

    print('\n' + '=' * 78)
    ok = not cleared_fail and not kept_fail
    if ok:
        print('  执行结果：成功 — 待清除数据已全部移除，保留数据完整一致')
    else:
        print('  执行结果：异常 — 请查看上方 FAIL 明细')
    print(f'  报告: {report_path}')
    print('=' * 78)
    return 0 if ok else 2


if __name__ == '__main__':
    sys.exit(main())
