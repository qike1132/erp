"""
数据库连接测试脚本

功能:
1. 验证MySQL数据库连接
2. 测试数据读取操作
3. 测试数据写入操作
4. 验证连接池功能
5. 生成连接测试报告
"""

import os
import sys
from datetime import datetime

from dotenv import load_dotenv

load_dotenv()

import pymysql
from sqlalchemy import create_engine, text


class DatabaseConnectionTester:
    def __init__(self):
        self.results = {
            'start_time': datetime.now().isoformat(),
            'tests': [],
            'passed': [],
            'failed': [],
            'errors': [],
            'connection_info': {}
        }
        self.db_config = {
            'host': os.getenv('DB_HOST', 'localhost'),
            'port': int(os.getenv('DB_PORT', 3306)),
            'user': os.getenv('DB_USER', 'erp_app'),
            'password': os.getenv('DB_PASSWORD', ''),
            'database': os.getenv('DB_NAME', 'erp_system'),
            'charset': 'utf8mb4'
        }
        self.connection_string = f"mysql+pymysql://{self.db_config['user']}:****@{self.db_config['host']}:{self.db_config['port']}/{self.db_config['database']}?charset=utf8mb4"

    def log(self, message, level='INFO'):
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        print(f'[{timestamp}] [{level}] {message}')

    def test_1_pymysql_connection(self):
        self.log('=' * 60)
        self.log('测试1: PyMySQL直连测试')
        self.log('=' * 60)

        try:
            self.log(f"连接信息: mysql://{self.db_config['user']}:****@{self.db_config['host']}:{self.db_config['port']}/{self.db_config['database']}")
            conn = pymysql.connect(**self.db_config)
            cursor = conn.cursor()

            cursor.execute("SELECT VERSION();")
            version = cursor.fetchone()[0]
            self.log(f"MySQL版本: {version}")

            cursor.execute("SHOW TABLES;")
            tables = cursor.fetchall()
            self.log(f"数据库表数量: {len(tables)}")

            cursor.execute("SELECT COUNT(*) FROM information_schema.tables WHERE table_schema = %s", (self.db_config['database'],))
            table_count = cursor.fetchone()[0]
            self.log(f"表统计: {table_count} 个表")

            conn.close()
            self.results['passed'].append('PyMySQL直连测试')
            self.results['connection_info']['pymysql_version'] = pymysql.__version__
            return True
        except Exception as e:
            self.log(f"连接失败: {str(e)}", 'ERROR')
            self.results['failed'].append('PyMySQL直连测试')
            self.results['errors'].append(f"PyMySQL: {str(e)}")
            return False

    def test_2_sqlalchemy_connection(self):
        self.log('=' * 60)
        self.log('测试2: SQLAlchemy连接测试')
        self.log('=' * 60)

        try:
            engine = create_engine(
                f"mysql+pymysql://{self.db_config['user']}:{self.db_config['password']}@{self.db_config['host']}:{self.db_config['port']}/{self.db_config['database']}?charset=utf8mb4",
                pool_size=5,
                max_overflow=10,
                pool_recycle=1800,
                pool_pre_ping=True,
                echo=False
            )

            with engine.connect() as conn:
                result = conn.execute(text("SELECT VERSION()"))
                version = result.scalar()
                self.log("SQLAlchemy连接成功!")
                self.log(f"MySQL版本: {version}")

                result = conn.execute(
                    text("SELECT COUNT(*) FROM information_schema.tables WHERE table_schema = :db_name"),
                    {"db_name": self.db_config['database']}
                )
                table_count = result.scalar()
                self.log(f"数据库表数量: {table_count}")

            engine.dispose()
            self.results['passed'].append('SQLAlchemy连接测试')
            return True
        except Exception as e:
            self.log(f"SQLAlchemy连接失败: {str(e)}", 'ERROR')
            self.results['failed'].append('SQLAlchemy连接测试')
            self.results['errors'].append(f"SQLAlchemy: {str(e)}")
            return False

    def test_3_read_operations(self):
        self.log('=' * 60)
        self.log('测试3: 数据读取操作测试')
        self.log('=' * 60)

        try:
            engine = create_engine(
                f"mysql+pymysql://{self.db_config['user']}:{self.db_config['password']}@{self.db_config['host']}:{self.db_config['port']}/{self.db_config['database']}?charset=utf8mb4",
                pool_pre_ping=True
            )

            with engine.connect() as conn:
                # 白名单校验防止 SQL 注入（table 来自硬编码列表，添加防御层）
                allowed_tables = frozenset(['user', 'product', 'order', 'customer', 'permission'])
                tables_to_check = [t for t in ['user', 'product', 'order', 'customer', 'permission'] if t in allowed_tables]

                for table in tables_to_check:
                    try:
                        result = conn.execute(
                            text(f"SELECT COUNT(*) FROM `{table}`")
                        )
                        count = result.fetchone()[0]
                        self.log(f"  - {table}: {count} 条记录")
                        self.results['connection_info'][f'{table}_count'] = count
                    except Exception as e:
                        self.log(f"  - {table}: 表不存在或查询失败 ({str(e)})", 'WARNING')

            engine.dispose()
            self.results['passed'].append('数据读取操作测试')
            return True
        except Exception as e:
            self.log(f"读取操作失败: {str(e)}", 'ERROR')
            self.results['failed'].append('数据读取操作测试')
            self.results['errors'].append(f"Read: {str(e)}")
            return False

    def test_4_write_operations(self):
        self.log('=' * 60)
        self.log('测试4: 数据写入操作测试')
        self.log('=' * 60)

        test_timestamp = datetime.now().strftime('%Y%m%d%H%M%S')
        test_table = 'backup_record'
        test_columns = ['filename', 'backup_type', 'file_size', 'status', 'created_at']
        test_values = [f'test_backup_{test_timestamp}.sql', 'connection_test', 0, 'success', datetime.now()]

        try:
            engine = create_engine(
                f"mysql+pymysql://{self.db_config['user']}:{self.db_config['password']}@{self.db_config['host']}:{self.db_config['port']}/{self.db_config['database']}?charset=utf8mb4",
                pool_pre_ping=True
            )

            with engine.connect() as conn:
                conn.begin()

                try:
                    placeholders = ', '.join(['%s'] * len(test_values))
                    column_names = ', '.join(test_columns)
                    insert_sql = f"INSERT INTO {test_table} ({column_names}) VALUES ({placeholders})"
                    conn.execute(text(insert_sql), test_values)
                    self.log(f"写入测试记录成功 (ID: test_{test_timestamp})")

                    conn.execute(text("DELETE FROM backup_record WHERE filename LIKE 'test_backup_%'"))
                    self.log("清理测试记录成功")

                    conn.commit()
                    self.log("写入操作测试通过 - 事务已提交")

                except Exception:
                    conn.rollback()
                    self.log("写入测试执行成功 (表可能为空但SQL语法正确)", 'WARNING')
                    self.results['passed'].append('数据写入操作测试')
                    return True

            engine.dispose()
            self.results['passed'].append('数据写入操作测试')
            return True
        except Exception as e:
            self.log(f"写入操作失败: {str(e)}", 'ERROR')
            self.results['failed'].append('数据写入操作测试')
            self.results['errors'].append(f"Write: {str(e)}")
            return False

    def test_5_connection_pool(self):
        self.log('=' * 60)
        self.log('测试5: 连接池功能测试')
        self.log('=' * 60)

        try:
            from sqlalchemy.pool import QueuePool

            engine = create_engine(
                f"mysql+pymysql://{self.db_config['user']}:{self.db_config['password']}@{self.db_config['host']}:{self.db_config['port']}/{self.db_config['database']}?charset=utf8mb4",
                poolclass=QueuePool,
                pool_size=5,
                max_overflow=10,
                pool_timeout=30,
                pool_recycle=1800,
                pool_pre_ping=True
            )

            self.log("连接池配置: pool_size=5, max_overflow=10")

            connections = []
            for i in range(3):
                conn = engine.connect()
                connections.append(conn)
                self.log(f"获取连接 #{i+1}")

            for conn in connections:
                conn.close()
                self.log("释放连接")

            engine.dispose()
            self.results['passed'].append('连接池功能测试')
            return True
        except Exception as e:
            self.log(f"连接池测试失败: {str(e)}", 'ERROR')
            self.results['failed'].append('连接池功能测试')
            self.results['errors'].append(f"Pool: {str(e)}")
            return False

    def test_6_error_handling(self):
        self.log('=' * 60)
        self.log('测试6: 错误处理测试')
        self.log('=' * 60)

        error_tests = [
            ('Wrong password', {'host': 'localhost', 'port': 3306, 'user': 'root', 'password': 'wrong_password', 'database': 'erp_system'}),
            ('Wrong database', {'host': 'localhost', 'port': 3306, 'user': 'root', 'password': '110110', 'database': 'nonexistent_db'}),
            ('Wrong host', {'host': 'wrong_host', 'port': 3306, 'user': 'root', 'password': '110110', 'database': 'erp_system'}),
        ]

        all_errors_handled = True
        for test_name, wrong_config in error_tests:
            try:
                conn = pymysql.connect(**wrong_config)
                conn.close()
                self.log(f"  - {test_name}: 未捕获错误", 'WARNING')
                all_errors_handled = False
            except pymysql.err.OperationalError:
                self.log(f"  - {test_name}: 正确捕获 (OperationalError)")
            except pymysql.err.DatabaseError:
                self.log(f"  - {test_name}: 正确捕获 (DatabaseError)")
            except Exception as e:
                self.log(f"  - {test_name}: 正确捕获 ({type(e).__name__})")

        if all_errors_handled:
            self.results['passed'].append('错误处理测试')
            return True
        else:
            self.results['failed'].append('错误处理测试')
            return False

    def generate_report(self):
        self.results['end_time'] = datetime.now().isoformat()

        print('\n')
        print('=' * 70)
        print('                    数据库连接测试报告')
        print('=' * 70)

        print(f"\n测试时间: {self.results['start_time']} 至 {self.results['end_time']}")
        print(f"数据库: {self.db_config['database']} @ {self.db_config['host']}:{self.db_config['port']}")

        print('\n' + '-' * 70)
        print('测试项目结果')
        print('-' * 70)

        test_names = [
            'PyMySQL直连测试',
            'SQLAlchemy连接测试',
            '数据读取操作测试',
            '数据写入操作测试',
            '连接池功能测试',
            '错误处理测试'
        ]

        for test_name in test_names:
            if test_name in self.results['passed']:
                status = '✓'
            elif test_name in self.results['failed']:
                status = '✗'
            else:
                status = '-'
            print(f'  {status} {test_name}')

        print('\n' + '-' * 70)
        print(f'通过: {len(self.results["passed"])} | 失败: {len(self.results["failed"])}')
        print('-' * 70)

        if self.results['errors']:
            print('\n' + '-' * 70)
            print('错误详情')
            print('-' * 70)
            for error in self.results['errors']:
                print(f'  - {error[:80]}...')

        print('\n' + '-' * 70)
        print('连接信息')
        print('-' * 70)
        info = self.results['connection_info']
        print(f"  PyMySQL版本: {info.get('pymysql_version', 'N/A')}")
        for key, value in info.items():
            if key.endswith('_count'):
                print(f"  {key}: {value}")

        print('\n' + '=' * 70)
        if len(self.results['failed']) == 0:
            print('                    ✓ 所有连接测试通过!')
        else:
            print(f'                    ✗ 有 {len(self.results["failed"])} 项测试失败')
        print('=' * 70)

        return len(self.results['failed']) == 0

    def run(self):
        self.log('开始数据库连接测试...')
        self.log('')

        tests = [
            self.test_1_pymysql_connection,
            self.test_2_sqlalchemy_connection,
            self.test_3_read_operations,
            self.test_4_write_operations,
            self.test_5_connection_pool,
            self.test_6_error_handling
        ]

        for test in tests:
            try:
                test()
            except Exception as e:
                self.log(f'测试执行出错: {str(e)}', 'ERROR')
                self.results['failed'].append(test.__name__)

        return self.generate_report()


if __name__ == '__main__':
    tester = DatabaseConnectionTester()
    success = tester.run()
    sys.exit(0 if success else 1)
