"""验证MySQL备份文件完整性"""
import os
import sys


def verify_backup(backup_file: str):
    """验证指定的MySQL备份文件"""
    if not backup_file:
        print("用法: python verify_backup.py <备份文件路径>")
        sys.exit(1)

    if not os.path.exists(backup_file):
        print(f"错误: 备份文件不存在: {backup_file}")
        sys.exit(1)

    print(f'验证MySQL备份文件: {backup_file}')

    file_size = os.path.getsize(backup_file)
    print(f'文件大小: {file_size:,} 字节')

    # 仅读取前10KB用于验证，避免大文件耗尽内存
    with open(backup_file, encoding='utf-8', errors='ignore') as f:
        header = f.read(10240)

    table_count = header.count('CREATE TABLE')
    print(f'CREATE TABLE 语句数量(前10KB): {table_count}')

    insert_count = header.count('INSERT INTO')
    print(f'INSERT INTO 语句数量(前10KB): {insert_count}')

    print('\n检查关键表是否存在:')
    key_tables = ['user', 'product', 'order', 'customer']
    for table in key_tables:
        if f'`{table}`' in header or f"'{table}'" in header:
            print(f'  ✓ {table}')
        else:
            print(f'  ✗ {table} (未在头部找到)')

    print('\nMySQL备份文件验证完成!')


if __name__ == '__main__':
    path = sys.argv[1] if len(sys.argv) > 1 else ''
    verify_backup(path)
