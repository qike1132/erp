import os
import subprocess

MYSQL_PATH = r'C:\Program Files\MySQL\MySQL Server 8.4\bin\mysql.exe'
DB_USER = 'root'
DB_PASSWORD = '110110'
DB_NAME = 'erp_system'
BACKUP_FILE = r'd:\erp_system\backups\manual\erp_system_backup_20260416_091519.sql'

print('正在恢复数据库...')

with open(BACKUP_FILE, 'rb') as f:
    result = subprocess.run(
        [MYSQL_PATH, f'-u{DB_USER}', f'-p{DB_PASSWORD}', DB_NAME],
        stdin=f,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE
    )

if result.returncode == 0:
    print('数据库恢复成功!')
else:
    stderr = result.stderr.decode('utf-8', errors='replace')
    print(f'恢复失败: {stderr}')
