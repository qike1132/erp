import os
import re

backup_file = r'd:\erp_system\backups\manual\erp_system_backup_20260416_091519.sql'

print('=' * 60)
print('备份文件分析')
print('=' * 60)

with open(backup_file, 'r', encoding='utf-8', errors='ignore') as f:
    content = f.read()

table_pattern = r'CREATE TABLE `?(\w+)`?'
tables = re.findall(table_pattern, content)

print(f'备份文件中的表 ({len(tables)} 个):')
for i, table in enumerate(sorted(tables), 1):
    print(f'  {i:2}. {table}')

print('\n' + '=' * 60)
print('数据统计')
print('=' * 60)

insert_count = content.count('INSERT INTO')
print(f'INSERT INTO 语句数量: {insert_count}')

lines = content.split('\n')
print(f'总行数: {len(lines):,}')

file_size = os.path.getsize(backup_file)
print(f'文件大小: {file_size:,} 字节 ({file_size/1024:.2f} KB)')
