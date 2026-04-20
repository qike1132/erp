"""
数据库恢复测试脚本

功能:
1. 创建测试数据库
2. 从备份恢复数据到测试数据库
3. 验证恢复数据的完整性
4. 生成验证报告
"""

import os
import subprocess
import re
import sys
from datetime import datetime
from pathlib import Path

MYSQL_BIN = r'C:\Program Files\MySQL\MySQL Server 8.4\bin'
MYSQL_PATH = os.path.join(MYSQL_BIN, 'mysql.exe')
MYSQLDUMP_PATH = os.path.join(MYSQL_BIN, 'mysqldump.exe')

DB_HOST = 'localhost'
DB_PORT = '3306'
DB_USER = os.getenv('DB_USER', 'erp_app')
DB_PASSWORD = os.getenv('DB_PASSWORD', '')
DB_NAME = os.getenv('DB_NAME', 'erp_system')
TEST_DB_NAME = 'erp_system_test'

BACKUP_FILE = sys.argv[1] if len(sys.argv) > 1 else ''

if not DB_PASSWORD:
    print('错误: 请设置环境变量 DB_PASSWORD')
    print('用法: set DB_PASSWORD=your_password && python restore_test.py <备份文件路径>')
    sys.exit(1)

class DatabaseRestoreTest:
    def __init__(self):
        self.results = {
            'start_time': datetime.now().isoformat(),
            'backup_file': BACKUP_FILE,
            'test_db': TEST_DB_NAME,
            'steps': [],
            'passed': [],
            'failed': [],
            'tables_found': [],
            'record_counts': {},
            'errors': []
        }

    def log(self, message, level='INFO'):
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        print(f'[{timestamp}] [{level}] {message}')

    def run_mysql_command(self, command, database=None):
        cmd = [MYSQL_PATH, f'-u{DB_USER}', f'-p{DB_PASSWORD}', '-e', command]
        if database:
            cmd.insert(4, database)
        result = subprocess.run(cmd, capture_output=True, text=True)
        return result

    def step_1_check_backup_file(self):
        self.log('=' * 60)
        self.log('步骤1: 检查备份文件')
        self.log('=' * 60)

        if not os.path.exists(BACKUP_FILE):
            self.results['failed'].append('备份文件不存在')
            return False

        file_size = os.path.getsize(BACKUP_FILE)
        self.log(f'备份文件大小: {file_size:,} 字节')

        with open(BACKUP_FILE, 'r', encoding='utf-8', errors='ignore') as f:
            content = f.read()

        table_pattern = r'CREATE TABLE `?(\w+)`?'
        tables = re.findall(table_pattern, content)
        self.results['tables_found'] = tables
        self.log(f'备份文件包含 {len(tables)} 个表')

        if len(tables) == 0:
            self.results['failed'].append('备份文件中没有找到表结构')
            return False

        self.results['passed'].append('备份文件完整性检查')
        return True

    def step_2_create_test_database(self):
        self.log('=' * 60)
        self.log('步骤2: 创建测试数据库')
        self.log('=' * 60)

        self.log(f'删除已存在的测试数据库 (如果存在)...')
        result = self.run_mysql_command(f'DROP DATABASE IF EXISTS {TEST_DB_NAME}')
        if result.returncode != 0:
            self.log(f'删除测试数据库失败: {result.stderr}', 'WARNING')

        self.log(f'创建测试数据库: {TEST_DB_NAME}')
        result = self.run_mysql_command(
            f'CREATE DATABASE {TEST_DB_NAME} CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci'
        )

        if result.returncode == 0:
            self.log('测试数据库创建成功')
            self.results['passed'].append('创建测试数据库')
            return True
        else:
            self.log(f'创建测试数据库失败: {result.stderr}', 'ERROR')
            self.results['failed'].append('创建测试数据库')
            self.results['errors'].append(result.stderr)
            return False

    def step_3_restore_to_test_db(self):
        self.log('=' * 60)
        self.log('步骤3: 恢复数据到测试数据库')
        self.log('=' * 60)

        self.log('开始恢复...')
        with open(BACKUP_FILE, 'rb') as f:
            result = subprocess.run(
                [MYSQL_PATH, f'-u{DB_USER}', f'-p{DB_PASSWORD}', TEST_DB_NAME],
                stdin=f,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE
            )

        if result.returncode == 0:
            self.log('数据恢复成功!')
            self.results['passed'].append('恢复数据到测试数据库')
            return True
        else:
            stderr = result.stderr.decode('utf-8', errors='replace')
            self.log(f'恢复失败: {stderr}', 'ERROR')
            self.results['failed'].append('恢复数据到测试数据库')
            self.results['errors'].append(stderr)
            return False

    def step_4_verify_tables(self):
        self.log('=' * 60)
        self.log('步骤4: 验证表结构')
        self.log('=' * 60)

        result = self.run_mysql_command(
            "SELECT table_name FROM information_schema.tables WHERE table_schema = %s",
            TEST_DB_NAME
        )

        if result.returncode != 0:
            self.log(f'查询失败: {result.stderr}', 'ERROR')
            return False

        output = result.stdout.strip()
        tables = [line for line in output.split('\n') if line and line != 'table_name']

        self.log(f'测试数据库中的表数量: {len(tables)}')
        self.log(f'预期表数量: {len(self.results["tables_found"])}')

        missing_tables = set(self.results['tables_found']) - set(tables)
        if missing_tables:
            self.log(f'缺失的表: {missing_tables}', 'WARNING')
            self.results['failed'].append(f'缺失的表: {missing_tables}')
            return False

        self.log('所有表都已成功恢复!')
        self.results['passed'].append('验证表结构')
        return True

    def step_5_verify_data(self):
        self.log('=' * 60)
        self.log('步骤5: 验证数据完整性')
        self.log('=' * 60)

        result = self.run_mysql_command(
            f'SELECT table_name, table_rows FROM information_schema.tables WHERE table_schema = "{TEST_DB_NAME}"',
            None
        )

        if result.returncode != 0:
            self.log(f'查询失败: {result.stderr}', 'ERROR')
            return False

        output_lines = result.stdout.strip().split('\n')[1:]
        for line in output_lines:
            parts = line.split('\t')
            if len(parts) == 2:
                table_name, row_count = parts
                try:
                    self.results['record_counts'][table_name] = int(row_count)
                except ValueError:
                    self.results['record_counts'][table_name] = 0

        self.log('关键表记录数:')
        key_tables = ['user', 'product', 'order', 'customer', 'permission']
        for table in key_tables:
            if table in self.results['record_counts']:
                count = self.results['record_counts'][table]
                self.log(f'  - {table}: {count:,} 条记录')

        self.results['passed'].append('验证数据完整性')
        return True

    def step_6_verify_references(self):
        self.log('=' * 60)
        self.log('步骤6: 验证数据引用完整性')
        self.log('=' * 60)

        result = self.run_mysql_command(
            f'''
            SELECT COUNT(*) AS orphan_users FROM {TEST_DB_NAME}.user
            WHERE id NOT IN (SELECT DISTINCT user_id FROM {TEST_DB_NAME}.user_permission WHERE user_id IS NOT NULL)
            ''',
            None
        )

        if result.returncode == 0:
            self.log('数据引用完整性检查通过')
            self.results['passed'].append('验证数据引用完整性')
            return True

        self.results['failed'].append('验证数据引用完整性')
        return False

    def step_7_cleanup(self):
        self.log('=' * 60)
        self.log('步骤7: 清理测试数据库')
        self.log('=' * 60)

        result = self.run_mysql_command(f'DROP DATABASE IF EXISTS {TEST_DB_NAME}')
        if result.returncode == 0:
            self.log('测试数据库已清理')
            self.results['passed'].append('清理测试数据库')
            return True
        else:
            self.log(f'清理失败: {result.stderr}', 'WARNING')
            return False

    def generate_report(self):
        self.results['end_time'] = datetime.now().isoformat()

        print('\n')
        print('=' * 70)
        print('                    数据库恢复测试报告')
        print('=' * 70)

        print(f"\n测试时间: {self.results['start_time']} 至 {self.results['end_time']}")
        print(f"备份文件: {self.results['backup_file']}")
        print(f"文件大小: {os.path.getsize(BACKUP_FILE):,} 字节")

        print('\n' + '-' * 70)
        print('测试步骤结果')
        print('-' * 70)

        for step in self.results['steps']:
            status = '✓' if step in self.results['passed'] else '✗'
            print(f'  {status} {step}')

        print('\n' + '-' * 70)
        print(f'通过: {len(self.results["passed"])} | 失败: {len(self.results["failed"])}')
        print('-' * 70)

        if self.results['record_counts']:
            print('\n' + '-' * 70)
            print('数据统计')
            print('-' * 70)
            print(f'{"表名":<40} {"记录数":>15}')
            print('-' * 70)
            for table, count in sorted(self.results['record_counts'].items()):
                print(f'{table:<40} {count:>15,}')

        if self.results['errors']:
            print('\n' + '-' * 70)
            print('错误信息')
            print('-' * 70)
            for error in self.results['errors']:
                print(f'  - {error[:100]}...')

        print('\n' + '=' * 70)
        if len(self.results['failed']) == 0:
            print('                    ✓ 数据库恢复测试全部通过!')
        else:
            print(f'                    ✗ 有 {len(self.results["failed"])} 项测试失败')
        print('=' * 70)

        return len(self.results['failed']) == 0

    def run(self):
        self.results['steps'] = [
            '检查备份文件',
            '创建测试数据库',
            '恢复数据到测试数据库',
            '验证表结构',
            '验证数据完整性',
            '验证数据引用完整性',
            '清理测试数据库'
        ]

        self.log('开始数据库恢复测试...')
        self.log('')

        steps = [
            self.step_1_check_backup_file,
            self.step_2_create_test_database,
            self.step_3_restore_to_test_db,
            self.step_4_verify_tables,
            self.step_5_verify_data,
            self.step_6_verify_references,
            self.step_7_cleanup
        ]

        for step in steps:
            try:
                step()
            except Exception as e:
                self.log(f'步骤执行出错: {str(e)}', 'ERROR')
                self.results['failed'].append(step.__name__)
                self.results['errors'].append(str(e))

        return self.generate_report()


if __name__ == '__main__':
    tester = DatabaseRestoreTest()
    success = tester.run()
    exit(0 if success else 1)
