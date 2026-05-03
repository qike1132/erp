import os
import subprocess
import sys

MYSQL_PATH = r'C:\Program Files\MySQL\MySQL Server 8.4\bin\mysql.exe'
DB_USER = os.getenv('DB_USER', 'erp_app')
DB_PASSWORD = os.getenv('DB_PASSWORD', '')
DB_NAME = os.getenv('DB_NAME', 'erp_system')
BACKUP_FILE = sys.argv[1] if len(sys.argv) > 1 else ''

if not DB_PASSWORD:
    print('错误: 请设置环境变量 DB_PASSWORD')
    print('用法: set DB_PASSWORD=your_password && python restore_db.py [备份文件路径]')
    sys.exit(1)

if not BACKUP_FILE or not os.path.exists(BACKUP_FILE):
    print('错误: 请指定有效的备份文件路径')
    print('用法: python restore_db.py <备份文件路径>')
    sys.exit(1)

print('正在恢复数据库...')

with open(BACKUP_FILE, 'rb') as f:
    result = subprocess.run(
        [MYSQL_PATH, f'-u{DB_USER}', f'-p{DB_PASSWORD}', DB_NAME],
        stdin=f,
        capture_output=True
    )

if result.returncode == 0:
    print('数据库恢复成功!')
else:
    stderr = result.stderr.decode('utf-8', errors='replace')
    print(f'恢复失败: {stderr}')
