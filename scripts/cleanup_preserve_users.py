"""
数据清理脚本 - 保留用户管理数据，清除其他所有数据（已弃用）

保留: user, permission, user_permission
清除: 所有其他数据库表、Redis缓存、日志文件、临时文件、文件缓存

⚠️ 2026-10-17 审计 P1-35：CLEAR_TABLES_ORDERED 与 ORM metadata 漂移（漏板房 7 张、
湖北外发 5 张、notification / numbering_counter 等），而 verify() 只校验自己的清单，
仍会打印「其他数据已彻底清除」。上线清库请改用 ``scripts/purge_simulated_data.py``
（pg_dump 备份 + 保留表指纹复核 + 真 dry-run + 写护栏）。确需运行本脚本须显式加
``--allow-deprecated-clear``。

（`device_token` / `product_packaging` 是 ORM 已删除的历史表，已由迁移
 pg_standalone_054 删除，本脚本不再引用。）
"""
import shutil
import sys
from pathlib import Path

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

import contextlib

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from fastapi_app.core.config import settings

KEEP_TABLES = {'user', 'permission', 'user_permission'}

CLEAR_TABLES_ORDERED = [
    'material_registration_item',
    'material_registration',
    'purchase_order_item',
    'purchase_order',
    'purchase_plan_details',
    'shipment_records',
    'purchase_plans',
    'supplier',
    'order_status_log',
    'order_batch_audit_log',
    'order_sync_record',
    'sync_retry_queue',
    'order_sync_config',
    'stock_return',
    'stock_out',
    'stock_in',
    'inventory_log',
    'approval_log',
    'approval_request',
    '"order"',
    # product_packaging 已删（迁移 pg_standalone_054）
    'product_accessory',
    'product_material',
    'product_fabric',
    'product',
    'packaging_record',
    'craft_work',
    'daily_production_record',
    'production_plan_log',
    'production_plan',
    'case_movement',
    '"case"',
    'customer_access_log',
    'customer',
    'staging_stock_out',
    'staging_stock_in',
    'staging_order',
    'staging_purchase_plan',
    'modification_log',
    'saved_query',
    'backup_record',
    'app_version',
]


def get_engine():
    return create_engine(settings.DATABASE_URL)


def count_table(db, table_name):
    try:
        return db.execute(text(f'SELECT COUNT(*) FROM {table_name}')).scalar()
    except Exception:
        return -1


def clear_database(db: Session):
    print('\n' + '=' * 70)
    print('  [1/4] 清理数据库表')
    print('=' * 70)

    total_deleted = 0
    failed_tables = []
    for table in CLEAR_TABLES_ORDERED:
        try:
            result = db.execute(text(f'DELETE FROM {table}'))
            deleted = result.rowcount
            db.commit()
            total_deleted += deleted
            print(f'  OK   {table:<40} {deleted:>8} rows deleted')
        except Exception as e:
            db.rollback()
            failed_tables.append(table)
            print(f'  ERR  {table:<40} {str(e)[:60]}')

    if failed_tables:
        print('\n  重试失败的表 (TRUNCATE CASCADE)...')
        for table in failed_tables:
            try:
                db.execute(text(f'TRUNCATE TABLE {table} CASCADE'))
                db.commit()
                print(f'  OK   {table:<40} truncated (cascade)')
            except Exception as e2:
                db.rollback()
                print(f'  FAIL {table:<40} {str(e2)[:60]}')

    print(f'\n  数据库清理完成: 共删除 {total_deleted} 行')

    print('\n  保留的用户管理数据:')
    for table in KEEP_TABLES:
        count = count_table(db, table)
        print(f'  KEEP  {table:<40} {count:>8} rows')

    return total_deleted


def clear_redis():
    print('\n' + '=' * 70)
    print('  [2/4] 清理 Redis 缓存')
    print('=' * 70)

    patterns = [
        'orders:*', 'inventory:*', 'stockins:*', 'products:*',
        'customers:*', 'search:*', 'stockouts:*', 'material:*',
        'dashboard:*', 'pp:monthly:*', 'erp:cache_invalidation',
    ]

    total_deleted = 0
    try:
        import redis
        redis_client = redis.Redis(
            host=settings.REDIS_HOST,
            port=settings.REDIS_PORT,
            db=settings.REDIS_DB,
            password=settings.REDIS_PASSWORD or None,
            decode_responses=True,
        )
        redis_client.ping()
        for pattern in patterns:
            keys = list(redis_client.scan_iter(pattern))
            if keys:
                deleted = redis_client.delete(*keys)
                total_deleted += deleted
                print(f'  OK   {pattern:<40} {deleted:>8} keys deleted')
            else:
                print(f'  -    {pattern:<40}        0 keys (empty)')
        redis_client.close()
    except Exception as e:
        print(f'  WARN Redis 不可用，跳过缓存清理: {e}')

    print(f'\n  Redis 缓存清理完成: 共删除 {total_deleted} 个键')
    return total_deleted


def clear_logs():
    print('\n' + '=' * 70)
    print('  [3/4] 清理日志文件')
    print('=' * 70)

    # ⚠️ 绝不包含 backups/：本函数会 rglob 后逐个 unlink，而 backups/server 下是
    # **真实生产备份与 pre_restore 还原点**——正是重置数据前最该保留的东西。
    # （2026-10-02 P6 审计发现原先含 `project_root / 'backups'`，会在“保留用户清数据”
    #  时把唯一可回滚的备份一起抹掉。）
    log_dirs = [
        project_root / 'logs',
    ]

    total_files = 0
    skipped_files = 0

    for log_dir in log_dirs:
        if not log_dir.exists():
            print(f'  -    {log_dir.relative_to(project_root):<50} (not exists)')
            continue
        files = [f for f in log_dir.rglob('*') if f.is_file()]
        file_count = 0
        for f in files:
            try:
                f.unlink()
                total_files += 1
                file_count += 1
            except OSError:
                skipped_files += 1
                file_count += 1
        for d in sorted(log_dir.rglob('*'), reverse=True):
            if d.is_dir():
                with contextlib.suppress(OSError):
                    d.rmdir()
        if file_count > 0:
            print(f'  OK   {log_dir.relative_to(project_root)!s:<50} {file_count:>5} files')
        else:
            print(f'  -    {log_dir.relative_to(project_root)!s:<50}     0 files (empty)')

    if skipped_files:
        print(f'  (跳过 {skipped_files} 个被占用的文件)')
    print(f'\n  日志清理完成: 共删除 {total_files} 个文件')
    return total_files


def clear_temp_files():
    print('\n' + '=' * 70)
    print('  [4/4] 清理临时文件和文件缓存')
    print('=' * 70)

    temp_dirs = [
        project_root / 'cache',
    ]

    temp_patterns = [
        'temp_*', 'tmp_*',
    ]

    total_files = 0

    for td in temp_dirs:
        if not td.exists():
            print(f'  -    {td.relative_to(project_root)!s:<50} (not exists)')
            continue
        files = list(td.rglob('*'))
        file_count = sum(1 for f in files if f.is_file())
        if file_count > 0:
            shutil.rmtree(td)
            td.mkdir(parents=True, exist_ok=True)
            print(f'  OK   {td.relative_to(project_root)!s:<50} {file_count:>5} files cleared')
            total_files += file_count
        else:
            print(f'  -    {td.relative_to(project_root)!s:<50}     0 files (empty)')

    root_files = list(project_root.iterdir())
    for pattern in temp_patterns:
        matched = [f for f in root_files if f.is_file() and f.name.startswith(pattern.replace('*', ''))]
        for f in matched:
            try:
                f.unlink()
                total_files += 1
                print(f'  OK   {f.name:<50} deleted')
            except OSError as e:
                print(f'  ERR  {f.name:<50} {e}')

    print(f'\n  临时文件清理完成: 共删除 {total_files} 个文件')
    return total_files


def verify(db: Session):
    print('\n' + '=' * 70)
    print('  验证清理结果')
    print('=' * 70)

    all_ok = True

    print('\n  保留表（应有数据）:')
    for table in KEEP_TABLES:
        count = count_table(db, table)
        status = 'OK' if count > 0 else 'WARN(0 rows)'
        if count <= 0:
            all_ok = False
        print(f'  {status:<15} {table:<40} {count:>8} rows')

    print('\n  已清理表（应为0）:')
    for table in CLEAR_TABLES_ORDERED:
        count = count_table(db, table)
        status = 'OK' if count == 0 else 'FAIL'
        if count != 0:
            all_ok = False
        display_name = table.strip('"')
        print(f'  {status:<15} {display_name:<40} {count:>8} rows')

    return all_ok


def main():
    if '--allow-deprecated-clear' not in sys.argv:
        print('本脚本已弃用：表清单已与 ORM 漂移，verify() 只校验自身清单。')
        print('请改用 scripts/purge_simulated_data.py（备份+保留表复核+真 dry-run）。')
        print('确需运行请显式加 --allow-deprecated-clear。')
        sys.exit(2)

    print('=' * 70)
    print('  ERP 数据清理工具 - 保留用户管理数据')
    print('=' * 70)
    print(f'  保留: {", ".join(sorted(KEEP_TABLES))}')
    print('  清除: 其他所有数据库表、Redis缓存、日志、临时文件')

    engine = get_engine()

    with Session(engine) as db:
        clear_database(db)
        clear_redis()
        clear_logs()
        clear_temp_files()

        all_ok = verify(db)

        print('\n' + '=' * 70)
        if all_ok:
            print('  验证通过: 用户管理数据已保留，本脚本清单内数据已清除')
            print('  注意: 该清单已与 ORM 漂移，不能据此断定「其他数据已彻底清除」')
        else:
            print('  验证异常: 部分清理未达预期，请检查上方输出')
        print('=' * 70)


if __name__ == '__main__':
    from _prod_write_guard import require_prod_write_consent
    require_prod_write_consent('清除除用户/权限外的全部业务数据、日志与缓存')
    main()
