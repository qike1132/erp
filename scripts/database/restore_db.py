import gzip
import json
import os
import subprocess
import sys
import zipfile
from datetime import datetime
from pathlib import Path

DB_HOST = os.getenv('DB_HOST', 'localhost')
DB_PORT = os.getenv('DB_PORT', '5432')
DB_USER = os.getenv('DB_USER', 'erp_app')
DB_PASSWORD = os.getenv('DB_PASSWORD', '')
DB_NAME = os.getenv('DB_NAME', 'erp_system')

PRE_RESTORE_DIR = Path(__file__).resolve().parents[2] / 'backups' / 'pre_restore'

env = os.environ.copy()
env['PGPASSWORD'] = DB_PASSWORD


def terminate_connections():
    try:
        subprocess.run(
            ['psql', '-h', DB_HOST, '-p', DB_PORT, '-U', DB_USER, '-d', 'postgres',
             '-c', f"SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                   f"WHERE datname = '{DB_NAME}' AND pid <> pg_backend_pid();"],
            env=env, capture_output=True, timeout=30
        )
    except (subprocess.TimeoutExpired, FileNotFoundError) as e:
        print(f'警告: 终止现有连接时出错: {e}')


def drop_and_recreate_db():
    try:
        subprocess.run(
            ['psql', '-h', DB_HOST, '-p', DB_PORT, '-U', DB_USER, '-d', 'postgres',
             '-c', f'DROP DATABASE IF EXISTS "{DB_NAME}" WITH (FORCE);'],
            env=env, capture_output=True, check=True, timeout=30
        )
    except subprocess.CalledProcessError:
        subprocess.run(
            ['psql', '-h', DB_HOST, '-p', DB_PORT, '-U', DB_USER, '-d', 'postgres',
             '-c', f'DROP DATABASE IF EXISTS "{DB_NAME}";'],
            env=env, capture_output=True, check=True, timeout=30
        )
    subprocess.run(
        ['psql', '-h', DB_HOST, '-p', DB_PORT, '-U', DB_USER, '-d', 'postgres',
         '-c', f'CREATE DATABASE "{DB_NAME}" OWNER "{DB_USER}";'],
        env=env, capture_output=True, check=True, timeout=30
    )


def create_pre_restore_backup() -> Path:
    """DROP DATABASE 之前唯一的回退手段；失败必须中止恢复（对齐 db_manager 模式）。"""
    PRE_RESTORE_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    out = PRE_RESTORE_DIR / f'restore_db_pre_{stamp}.dump'
    try:
        result = subprocess.run(
            ['pg_dump', '-h', DB_HOST, '-p', DB_PORT, '-U', DB_USER,
             '-d', DB_NAME, '-Fc', '-f', str(out)],
            env=env, capture_output=True, timeout=3600,
        )
    except FileNotFoundError as e:
        raise RuntimeError('pg_dump 命令未找到，请确保 PostgreSQL 客户端工具在 PATH 中') from e
    except subprocess.TimeoutExpired as e:
        raise RuntimeError('pg_dump 执行超时（超过 3600 秒）') from e
    if result.returncode != 0:
        detail = result.stderr.decode(errors='replace')[:500] if result.stderr else ''
        raise RuntimeError(f'pg_dump 失败: {detail}')
    if not out.exists() or out.stat().st_size == 0:
        raise RuntimeError('pg_dump 产物为空，恢复前备份不可用')
    return out


# ⚠️ 三处 psql 一律 ON_ERROR_STOP=1：该选项为 0 时 **SQL 错误不会让 psql 返回非零退出码**，
# 于是下方 `if result.returncode != 0` 判不出失败 → 走到 `print('数据库恢复成功!')`。
# （同仓 db_manager.py 的注释已证实：脚本错误仅在 ON_ERROR_STOP=1 时才置退出码。）
def restore_from_sql(sql_file):
    print(f'正在从 SQL 文件恢复: {sql_file}')
    with open(sql_file, 'rb') as f:
        result = subprocess.run(
            ['psql', '-h', DB_HOST, '-p', DB_PORT, '-U', DB_USER, '-d', DB_NAME,
             '-v', 'ON_ERROR_STOP=1'],
            stdin=f, capture_output=True, env=env, timeout=600
        )
    return result


def restore_from_sql_gz(gz_file):
    print(f'正在从压缩 SQL 文件恢复: {gz_file}')
    with gzip.open(gz_file, 'rb') as f:
        sql_data = f.read()
    result = subprocess.run(
        ['psql', '-h', DB_HOST, '-p', DB_PORT, '-U', DB_USER, '-d', DB_NAME,
         '-v', 'ON_ERROR_STOP=1'],
        input=sql_data, capture_output=True, env=env, timeout=600
    )
    return result


def restore_from_zip(zip_file):
    print(f'正在从 ZIP 备份文件恢复: {zip_file}')
    with zipfile.ZipFile(zip_file, 'r') as zf:
        names = zf.namelist()
        if 'database/dump.sql.gz' in names:
            print('检测到 gzip 压缩的 SQL 导出')
            dump_gz = zf.read('database/dump.sql.gz')
            sql_data = gzip.decompress(dump_gz)
        elif 'database/dump.json' in names:
            print('检测到 JSON 格式导出（不支持通过命令行恢复，请使用 Web 界面）')
            sys.exit(1)
        else:
            print('错误: ZIP 文件中未找到数据库导出')
            sys.exit(1)
        if 'manifest.json' in names:
            manifest = json.loads(zf.read('manifest.json'))
            print(f"备份版本: {manifest.get('version', '?')}")
            print(f"备份时间: {manifest.get('exported_at', '?')}")
            print(f"备份人: {manifest.get('exported_by', '?')}")
            print(f"数据表数: {manifest.get('table_count', '?')}")
            print(f"总记录数: {manifest.get('total_rows', '?')}")
    result = subprocess.run(
        ['psql', '-h', DB_HOST, '-p', DB_PORT, '-U', DB_USER, '-d', DB_NAME,
         '-v', 'ON_ERROR_STOP=1'],
        input=sql_data, capture_output=True, env=env, timeout=600
    )
    return result


def main() -> None:
    if not DB_NAME.isidentifier():
        print(f'错误: 数据库名称无效: {DB_NAME!r}')
        sys.exit(1)

    if not DB_PASSWORD:
        print('错误: 请设置环境变量 DB_PASSWORD')
        print('用法: set DB_PASSWORD=your_password && python restore_db.py [--allow-missing-pre-restore-backup] <备份文件路径>')
        sys.exit(1)

    cli_args = [a for a in sys.argv[1:] if not a.startswith('--')]
    allow_missing_backup = '--allow-missing-pre-restore-backup' in sys.argv[1:]
    backup_file = cli_args[0] if cli_args else ''
    if not backup_file or not os.path.exists(backup_file):
        print('错误: 请指定有效的备份文件路径')
        print('用法: python restore_db.py [--allow-missing-pre-restore-backup] <备份文件路径>')
        print('支持格式: .sql, .sql.gz, .zip')
        sys.exit(1)
    backup_path = Path(backup_file)

    print('警告: 即将恢复数据库，这将覆盖当前所有数据！')
    confirm = input('确认继续? (yes/no): ')
    if confirm.lower() not in ('yes', 'y'):
        print('已取消恢复操作')
        sys.exit(0)

    print('正在创建恢复前备份...')
    try:
        pre_backup = create_pre_restore_backup()
        print(f'恢复前备份完成: {pre_backup}')
    except Exception as e:  # defensive: 备份失败必须在这里统一判生死
        if allow_missing_backup:
            print(f'警告: 恢复前备份失败，但 --allow-missing-pre-restore-backup 已指定，继续恢复: {e}')
        else:
            print(f'错误: 恢复前备份失败，已中止恢复以避免数据丢失: {e}')
            sys.exit(1)

    print('终止现有数据库连接...')
    terminate_connections()

    print('重建数据库...')
    try:
        drop_and_recreate_db()
    except subprocess.CalledProcessError as e:
        print(f'数据库重建失败: {e.stderr.decode(errors="replace") if e.stderr else str(e)}')
        sys.exit(1)

    suffix = backup_path.suffix.lower()
    if suffix == '.sql':
        result = restore_from_sql(backup_file)
    elif suffix == '.gz':
        result = restore_from_sql_gz(backup_file)
    elif suffix == '.zip':
        result = restore_from_zip(backup_file)
    else:
        print(f'错误: 不支持的文件类型: {suffix}')
        sys.exit(1)

    stderr_text = result.stderr.decode(errors='replace') if result.stderr else ''
    error_lines = [l for l in stderr_text.split('\n') if 'ERROR' in l and 'already exists' not in l.lower()]
    if result.returncode != 0 or error_lines:
        print(f'恢复失败（psql 退出码={result.returncode}，错误行数={len(error_lines)}），数据库可能不完整:')
        for line in error_lines[:10]:
            print(f'  {line.strip()}')
        if not error_lines and stderr_text.strip():
            print(f'  {stderr_text.strip()[:500]}')
        sys.exit(1)

    print('数据库恢复成功!')


if __name__ == '__main__':
    main()
