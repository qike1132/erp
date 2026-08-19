import gzip
import os
import subprocess
import sys
import zipfile
from pathlib import Path

DB_HOST = os.getenv('DB_HOST', 'localhost')
DB_PORT = os.getenv('DB_PORT', '5432')
DB_USER = os.getenv('DB_USER', 'erp_app')
DB_PASSWORD = os.getenv('DB_PASSWORD', '')
DB_NAME = os.getenv('DB_NAME', 'erp_system')
BACKUP_FILE = sys.argv[1] if len(sys.argv) > 1 else ''

if not DB_NAME.isidentifier():
    print(f'错误: 数据库名称无效: {DB_NAME!r}')
    sys.exit(1)

if not DB_PASSWORD:
    print('错误: 请设置环境变量 DB_PASSWORD')
    print('用法: set DB_PASSWORD=your_password && python restore_db.py <备份文件路径>')
    sys.exit(1)

if not BACKUP_FILE or not os.path.exists(BACKUP_FILE):
    print('错误: 请指定有效的备份文件路径')
    print('用法: python restore_db.py <备份文件路径>')
    print('支持格式: .sql, .sql.gz, .zip')
    sys.exit(1)

backup_path = Path(BACKUP_FILE)
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


def restore_from_sql(sql_file):
    print(f'正在从 SQL 文件恢复: {sql_file}')
    with open(sql_file, 'rb') as f:
        result = subprocess.run(
            ['psql', '-h', DB_HOST, '-p', DB_PORT, '-U', DB_USER, '-d', DB_NAME,
             '-v', 'ON_ERROR_STOP=0'],
            stdin=f, capture_output=True, env=env, timeout=600
        )
    return result


def restore_from_sql_gz(gz_file):
    print(f'正在从压缩 SQL 文件恢复: {gz_file}')
    with gzip.open(gz_file, 'rb') as f:
        sql_data = f.read()
    result = subprocess.run(
        ['psql', '-h', DB_HOST, '-p', DB_PORT, '-U', DB_USER, '-d', DB_NAME,
         '-v', 'ON_ERROR_STOP=0'],
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
            import json
            manifest = json.loads(zf.read('manifest.json'))
            print(f"备份版本: {manifest.get('version', '?')}")
            print(f"备份时间: {manifest.get('exported_at', '?')}")
            print(f"备份人: {manifest.get('exported_by', '?')}")
            print(f"数据表数: {manifest.get('table_count', '?')}")
            print(f"总记录数: {manifest.get('total_rows', '?')}")
    result = subprocess.run(
        ['psql', '-h', DB_HOST, '-p', DB_PORT, '-U', DB_USER, '-d', DB_NAME,
         '-v', 'ON_ERROR_STOP=0'],
        input=sql_data, capture_output=True, env=env, timeout=600
    )
    return result


print('警告: 即将恢复数据库，这将覆盖当前所有数据！')
confirm = input('确认继续? (yes/no): ')
if confirm.lower() not in ('yes', 'y'):
    print('已取消恢复操作')
    sys.exit(0)

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
    result = restore_from_sql(BACKUP_FILE)
elif suffix == '.gz':
    result = restore_from_sql_gz(BACKUP_FILE)
elif suffix == '.zip':
    result = restore_from_zip(BACKUP_FILE)
else:
    print(f'错误: 不支持的文件类型: {suffix}')
    sys.exit(1)

stderr_text = result.stderr.decode(errors='replace') if result.stderr else ''
if result.returncode != 0:
    error_lines = [l for l in stderr_text.split('\n') if 'ERROR' in l and 'already exists' not in l.lower()]
    if error_lines:
        print(f'恢复完成，但有 {len(error_lines)} 个错误:')
        for line in error_lines[:10]:
            print(f'  {line.strip()}')
    else:
        print('恢复完成（有非关键警告）')
else:
    print('数据库恢复成功!')
