import os
import sqlite3

backup_file = r'd:\erp_system\backups\manual\erp_system_backup_20260416_091519.sql'

print(f'验证备份文件: {backup_file}')
print(f'文件大小: {os.path.getsize(backup_file):,} 字节')

with open(backup_file, 'r', encoding='utf-8', errors='ignore') as f:
    content = f.read()

lines = content.split('\n')
print(f'总行数: {len(lines):,}')

table_count = content.count('CREATE TABLE')
print(f'CREATE TABLE 语句数量: {table_count}')

insert_count = content.count('INSERT INTO')
print(f'INSERT INTO 语句数量: {insert_count}')

print('\n检查关键表是否存在:')
key_tables = ['user', 'product', 'order', 'customer']
for table in key_tables:
    if f'`{table}`' in content or f"'{table}'" in content:
        print(f'  ✓ {table}')
    else:
        print(f'  ✗ {table} (未找到)')

print('\n备份文件验证完成!')
