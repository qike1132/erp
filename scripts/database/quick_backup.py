import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

db_host = 'localhost'
db_port = '3306'
db_user = os.getenv('DB_USER', 'erp_app')
db_password = os.getenv('DB_PASSWORD', '')
db_name = os.getenv('DB_NAME', 'erp_system')

if not db_password:
    print('错误: 请设置环境变量 DB_PASSWORD')
    sys.exit(1)

backup_dir = Path('d:/erp_system/backups/manual')
backup_dir.mkdir(parents=True, exist_ok=True)

timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
backup_file = backup_dir / f'erp_system_backup_{timestamp}.sql'

mysqldump_path = r'C:\Program Files\MySQL\MySQL Server 8.4\bin\mysqldump.exe'

cmd = [
    mysqldump_path,
    f'-h{db_host}',
    f'-P{db_port}',
    f'-u{db_user}',
    f'-p{db_password}',
    '--single-transaction',
    '--routines',
    '--triggers',
    '--hex-blob',
    db_name
]

print(f'正在备份MySQL数据库: {db_name}')
print(f'备份文件: {backup_file}')

result = subprocess.run(cmd, capture_output=True)

if result.returncode == 0:
    with open(backup_file, 'wb') as f:
        f.write(result.stdout)
    file_size = backup_file.stat().st_size
    print('备份成功!')
    print(f'文件: {backup_file}')
    print(f'大小: {file_size:,} 字节')
else:
    stderr_text = result.stderr.decode('utf-8', errors='replace')
    print(f'备份失败: {stderr_text}')
