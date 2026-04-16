"""
ERP系统数据库管理工具

功能:
1. 数据库备份（支持SQLite和MySQL）
2. 备份验证
3. 数据库恢复
4. 备份文件管理

使用方法:
    python scripts/database/db_manager.py backup
    python scripts/database/db_manager.py verify --file <backup_file>
    python scripts/database/db_manager.py restore --file <backup_file>
    python scripts/database/db_manager.py list
"""

import os
import sys
import shutil
import subprocess
import argparse
import json
import gzip
import hashlib
from datetime import datetime
from pathlib import Path
from typing import Optional, Tuple, Dict, Any

# 添加项目根目录到路径
PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

BACKUP_DIR = PROJECT_ROOT / 'backups'
DAILY_DIR = BACKUP_DIR / 'daily'
WEEKLY_DIR = BACKUP_DIR / 'weekly'
MONTHLY_DIR = BACKUP_DIR / 'monthly'
MANUAL_DIR = BACKUP_DIR / 'manual'


class DatabaseManager:
    """数据库管理器"""

    def __init__(self):
        self.backup_dirs = [DAILY_DIR, WEEKLY_DIR, MONTHLY_DIR, MANUAL_DIR]
        for dir_path in self.backup_dirs:
            dir_path.mkdir(parents=True, exist_ok=True)
        self.timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        self.load_env()

    def load_env(self):
        """加载环境变量"""
        try:
            from dotenv import load_dotenv
            load_dotenv()
        except ImportError:
            pass

    def log(self, message: str, level: str = 'INFO'):
        """记录日志"""
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        log_line = f"[{timestamp}] [{level}] {message}"
        print(log_line)

        log_file = BACKUP_DIR / 'db_manager.log'
        try:
            with open(log_file, 'a', encoding='utf-8') as f:
                f.write(log_line + '\n')
        except Exception as e:
            print(f"[WARN] 无法写入日志文件: {e}")

    def get_db_type(self) -> str:
        """获取数据库类型"""
        return os.getenv('DB_TYPE', 'sqlite')

    def get_sqlite_path(self) -> Path:
        """获取SQLite数据库路径"""
        return PROJECT_ROOT / 'erp.db'

    def get_mysql_config(self) -> Dict[str, str]:
        """获取MySQL配置"""
        return {
            'host': os.getenv('DB_HOST', 'localhost'),
            'port': os.getenv('DB_PORT', '3306'),
            'user': os.getenv('DB_USER', 'root'),
            'password': os.getenv('DB_PASSWORD', ''),
            'database': os.getenv('DB_NAME', 'erp_system')
        }

    def calculate_checksum(self, file_path: Path) -> str:
        """计算文件SHA-256校验和"""
        sha256_hash = hashlib.sha256()
        with open(file_path, 'rb') as f:
            for byte_block in iter(lambda: f.read(4096), b''):
                sha256_hash.update(byte_block)
        return sha256_hash.hexdigest()

    def compress_file(self, file_path: Path) -> Path:
        """压缩文件"""
        compressed_path = Path(str(file_path) + '.gz')
        with open(file_path, 'rb') as f_in:
            with gzip.open(compressed_path, 'wb') as f_out:
                shutil.copyfileobj(f_in, f_out)
        return compressed_path

    def decompress_file(self, file_path: Path) -> Path:
        """解压文件"""
        if not str(file_path).endswith('.gz'):
            return file_path

        decompressed_path = Path(str(file_path)[:-3])
        with gzip.open(file_path, 'rb') as f_in:
            with open(decompressed_path, 'wb') as f_out:
                shutil.copyfileobj(f_in, f_out)
        return decompressed_path

    def create_manifest(self, backup_path: Path, backup_type: str, original_path: Optional[Path] = None) -> Dict[str, Any]:
        """创建备份清单"""
        manifest = {
            'timestamp': self.timestamp,
            'backup_type': backup_type,
            'db_type': self.get_db_type(),
            'created_at': datetime.now().isoformat(),
            'files': []
        }

        if original_path and original_path.exists():
            manifest['original_size'] = original_path.stat().st_size

        for file_path in backup_path.parent.iterdir():
            if file_path.is_file() and self.timestamp in file_path.name:
                manifest['files'].append({
                    'name': file_path.name,
                    'size': file_path.stat().st_size,
                    'checksum': self.calculate_checksum(file_path)
                })

        manifest_file = backup_path.parent / f'manifest_{self.timestamp}.json'
        with open(manifest_file, 'w', encoding='utf-8') as f:
            json.dump(manifest, f, indent=2, ensure_ascii=False)

        return manifest

    def backup_sqlite(self, backup_dir: Path, compress: bool = True) -> Tuple[bool, str, Optional[Path]]:
        """备份SQLite数据库"""
        db_path = self.get_sqlite_path()

        if not db_path.exists():
            return False, "SQLite数据库文件不存在", None

        backup_file = backup_dir / f'erp_backup_{self.timestamp}.db'
        try:
            shutil.copy(db_path, backup_file)
            self.log(f"SQLite数据库已复制到: {backup_file}")

            if compress:
                compressed_file = self.compress_file(backup_file)
                backup_file.unlink()  # 删除未压缩文件
                backup_file = compressed_file
                self.log(f"备份文件已压缩: {backup_file}")

            self.create_manifest(backup_file, 'sqlite', db_path)
            return True, f"SQLite备份成功: {backup_file}", backup_file
        except Exception as e:
            return False, f"SQLite备份失败: {str(e)}", None

    def backup_mysql(self, backup_dir: Path, compress: bool = True) -> Tuple[bool, str, Optional[Path]]:
        """备份MySQL数据库"""
        config = self.get_mysql_config()
        backup_file = backup_dir / f'erp_system_backup_{self.timestamp}.sql'

        cmd = [
            'mysqldump',
            f'-h{config["host"]}',
            f'-P{config["port"]}',
            f'-u{config["user"]}',
        ]
        if config['password']:
            cmd.append(f'-p{config["password"]}')
        cmd.extend(['--single-transaction', '--routines', '--triggers', config['database']])

        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
            if result.returncode == 0:
                with open(backup_file, 'w', encoding='utf-8') as f:
                    f.write(result.stdout)
                self.log(f"MySQL数据库已导出到: {backup_file}")

                if compress:
                    compressed_file = self.compress_file(backup_file)
                    backup_file.unlink()
                    backup_file = compressed_file
                    self.log(f"备份文件已压缩: {backup_file}")

                self.create_manifest(backup_file, 'mysql')
                return True, f"MySQL备份成功: {backup_file}", backup_file
            else:
                return False, f"MySQL备份失败: {result.stderr}", None
        except FileNotFoundError:
            return False, "mysqldump命令未找到，请确保MySQL已安装并添加到PATH", None
        except subprocess.TimeoutExpired:
            return False, "MySQL备份超时", None
        except Exception as e:
            return False, f"MySQL备份失败: {str(e)}", None

    def backup(self, backup_type: str = 'manual', compress: bool = True) -> Tuple[bool, str]:
        """执行数据库备份"""
        self.log("=" * 60)
        self.log(f"开始数据库备份 - 类型: {backup_type}")
        self.log("=" * 60)

        # 确定备份目录
        backup_dir_map = {
            'daily': DAILY_DIR,
            'weekly': WEEKLY_DIR,
            'monthly': MONTHLY_DIR,
            'manual': MANUAL_DIR
        }
        backup_dir = backup_dir_map.get(backup_type, MANUAL_DIR)

        db_type = self.get_db_type()

        if db_type == 'sqlite':
            success, message, _ = self.backup_sqlite(backup_dir, compress)
        elif db_type == 'mysql':
            success, message, _ = self.backup_mysql(backup_dir, compress)
        else:
            success, message = False, f"不支持的数据库类型: {db_type}"

        if success:
            self.log("=" * 60)
            self.log("备份完成")
            self.log("=" * 60)
        else:
            self.log(message, 'ERROR')

        return success, message

    def verify_sqlite(self, backup_file: Path) -> Tuple[bool, str]:
        """验证SQLite备份"""
        try:
            import sqlite3
            conn = sqlite3.connect(str(backup_file))
            cursor = conn.cursor()

            # 检查是否有表
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
            tables = cursor.fetchall()

            if not tables:
                conn.close()
                return False, "备份文件中没有找到任何表"

            # 检查关键表是否存在
            expected_tables = ['user', 'product', 'order', 'customer']
            found_tables = [t[0] for t in tables]
            missing_tables = [t for t in expected_tables if t not in found_tables]

            if missing_tables:
                self.log(f"警告: 缺少预期的表: {missing_tables}", 'WARNING')

            # 获取记录数统计
            stats = {}
            for table in found_tables:
                try:
                    cursor.execute(f"SELECT COUNT(*) FROM `{table}`;")
                    count = cursor.fetchone()[0]
                    stats[table] = count
                except Exception:
                    pass

            conn.close()

            self.log(f"验证成功 - 找到 {len(tables)} 个表")
            for table, count in sorted(stats.items(), key=lambda x: x[1], reverse=True)[:10]:
                self.log(f"  - {table}: {count} 条记录")

            return True, f"SQLite备份验证成功，包含 {len(tables)} 个表"
        except Exception as e:
            return False, f"SQLite备份验证失败: {str(e)}"

    def verify_mysql(self, backup_file: Path) -> Tuple[bool, str]:
        """验证MySQL备份（基本检查）"""
        try:
            # 检查文件是否可读且包含基本SQL语句
            with open(backup_file, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read(10000)  # 读取前10KB

            if 'CREATE TABLE' not in content and 'CREATE DATABASE' not in content:
                return False, "备份文件似乎不包含有效的SQL语句"

            # 检查文件大小
            file_size = backup_file.stat().st_size
            if file_size < 100:
                return False, f"备份文件过小 ({file_size} 字节)"

            self.log(f"MySQL备份文件大小: {file_size:,} 字节")
            return True, "MySQL备份文件基本检查通过"
        except Exception as e:
            return False, f"MySQL备份验证失败: {str(e)}"

    def verify(self, backup_file: str) -> Tuple[bool, str]:
        """验证备份文件"""
        file_path = Path(backup_file)

        if not file_path.exists():
            return False, f"备份文件不存在: {backup_file}"

        self.log(f"开始验证备份文件: {file_path}")

        # 解压（如果需要）
        original_path = file_path
        if str(file_path).endswith('.gz'):
            self.log("检测到压缩文件，正在解压...")
            file_path = self.decompress_file(file_path)

        # 根据文件扩展名判断数据库类型
        if str(file_path).endswith('.db'):
            success, message = self.verify_sqlite(file_path)
        elif str(file_path).endswith('.sql'):
            success, message = self.verify_mysql(file_path)
        else:
            success, message = False, f"无法识别的备份文件类型: {file_path}"

        # 清理临时解压文件
        if original_path != file_path and file_path.exists():
            file_path.unlink()

        return success, message

    def restore_sqlite(self, backup_file: Path) -> Tuple[bool, str]:
        """恢复SQLite数据库"""
        db_path = self.get_sqlite_path()

        # 先备份当前数据库
        if db_path.exists():
            pre_restore_backup = BACKUP_DIR / f'erp_pre_restore_{self.timestamp}.db'
            shutil.copy(db_path, pre_restore_backup)
            self.log(f"已备份当前数据库到: {pre_restore_backup}")

        try:
            shutil.copy(backup_file, db_path)
            self.log(f"已将备份文件复制到: {db_path}")

            # 验证恢复结果
            success, message = self.verify_sqlite(db_path)
            if success:
                return True, "SQLite数据库恢复成功"
            else:
                return False, f"恢复验证失败: {message}"
        except Exception as e:
            return False, f"SQLite恢复失败: {str(e)}"

    def restore_mysql(self, backup_file: Path) -> Tuple[bool, str]:
        """恢复MySQL数据库"""
        config = self.get_mysql_config()

        # 先备份当前数据库
        self.log("正在备份当前MySQL数据库...")
        pre_restore_backup = BACKUP_DIR / f'erp_system_pre_restore_{self.timestamp}.sql'
        cmd = [
            'mysqldump',
            f'-h{config["host"]}',
            f'-P{config["port"]}',
            f'-u{config["user"]}',
        ]
        if config['password']:
            cmd.append(f'-p{config["password"]}')
        cmd.extend(['--single-transaction', config['database']])

        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
            if result.returncode == 0:
                with open(pre_restore_backup, 'w', encoding='utf-8') as f:
                    f.write(result.stdout)
                self.log(f"已备份当前数据库到: {pre_restore_backup}")
        except Exception as e:
            self.log(f"预恢复备份失败: {e}", 'WARNING')

        # 恢复备份
        self.log("正在恢复MySQL数据库...")
        cmd = [
            'mysql',
            f'-h{config["host"]}',
            f'-P{config["port"]}',
            f'-u{config["user"]}',
        ]
        if config['password']:
            cmd.append(f'-p{config["password"]}')
        cmd.append(config['database'])

        try:
            with open(backup_file, 'r', encoding='utf-8') as f:
                result = subprocess.run(cmd, stdin=f, capture_output=True, text=True, timeout=600)

            if result.returncode == 0:
                return True, "MySQL数据库恢复成功"
            else:
                return False, f"MySQL恢复失败: {result.stderr}"
        except FileNotFoundError:
            return False, "mysql命令未找到，请确保MySQL已安装并添加到PATH", None
        except Exception as e:
            return False, f"MySQL恢复失败: {str(e)}"

    def restore(self, backup_file: str) -> Tuple[bool, str]:
        """恢复数据库"""
        file_path = Path(backup_file)

        if not file_path.exists():
            return False, f"备份文件不存在: {backup_file}"

        self.log("=" * 60)
        self.log("警告: 即将恢复数据库，这将覆盖当前数据！")
        self.log("=" * 60)

        # 解压（如果需要）
        original_path = file_path
        if str(file_path).endswith('.gz'):
            self.log("检测到压缩文件，正在解压...")
            file_path = self.decompress_file(file_path)

        # 根据文件扩展名判断数据库类型
        if str(file_path).endswith('.db'):
            success, message = self.restore_sqlite(file_path)
        elif str(file_path).endswith('.sql'):
            success, message = self.restore_mysql(file_path)
        else:
            success, message = False, f"无法识别的备份文件类型: {file_path}"

        # 清理临时解压文件
        if original_path != file_path and file_path.exists():
            file_path.unlink()

        if success:
            self.log("=" * 60)
            self.log("恢复完成")
            self.log("=" * 60)
        else:
            self.log(message, 'ERROR')

        return success, message

    def list_backups(self) -> list:
        """列出所有备份"""
        backups = []

        for backup_dir in self.backup_dirs:
            if not backup_dir.exists():
                continue

            for file_path in backup_dir.iterdir():
                if file_path.is_file() and not file_path.name.startswith('manifest_'):
                    if file_path.name.endswith(('.db', '.sql', '.db.gz', '.sql.gz')):
                        stat = file_path.stat()
                        backups.append({
                            'path': str(file_path),
                            'name': file_path.name,
                            'directory': backup_dir.name,
                            'size': stat.st_size,
                            'size_human': self._human_size(stat.st_size),
                            'created': datetime.fromtimestamp(stat.st_ctime).isoformat(),
                            'modified': datetime.fromtimestamp(stat.st_mtime).isoformat()
                        })

        backups.sort(key=lambda x: x['modified'], reverse=True)
        return backups

    def _human_size(self, size: int) -> str:
        """人类可读的文件大小"""
        for unit in ['B', 'KB', 'MB', 'GB']:
            if size < 1024.0:
                return f"{size:.2f} {unit}"
            size /= 1024.0
        return f"{size:.2f} TB"

    def print_backups(self):
        """打印备份列表"""
        backups = self.list_backups()

        if not backups:
            self.log("没有找到备份文件")
            return

        self.log("=" * 100)
        self.log(f"{'':<4} {'文件名':<40} {'目录':<10} {'大小':<10} {'修改时间':<20}")
        self.log("=" * 100)

        for i, backup in enumerate(backups, 1):
            modified = datetime.fromisoformat(backup['modified']).strftime('%Y-%m-%d %H:%M')
            self.log(
                f"{i:<4} {backup['name']:<40} {backup['directory']:<10} "
                f"{backup['size_human']:<10} {modified:<20}"
            )

        self.log("=" * 100)
        self.log(f"共找到 {len(backups)} 个备份文件")


def main():
    parser = argparse.ArgumentParser(description='ERP系统数据库管理工具')
    subparsers = parser.add_subparsers(title='命令', dest='command')

    # 备份命令
    backup_parser = subparsers.add_parser('backup', help='备份数据库')
    backup_parser.add_argument('--type', choices=['daily', 'weekly', 'monthly', 'manual'],
                              default='manual', help='备份类型')
    backup_parser.add_argument('--no-compress', action='store_true', help='不压缩备份文件')

    # 验证命令
    verify_parser = subparsers.add_parser('verify', help='验证备份文件')
    verify_parser.add_argument('--file', required=True, help='备份文件路径')

    # 恢复命令
    restore_parser = subparsers.add_parser('restore', help='恢复数据库')
    restore_parser.add_argument('--file', required=True, help='备份文件路径')
    restore_parser.add_argument('--force', action='store_true', help='强制恢复（不确认）')

    # 列表命令
    subparsers.add_parser('list', help='列出所有备份')

    args = parser.parse_args()
    manager = DatabaseManager()

    if args.command == 'backup':
        success, message = manager.backup(args.type, not args.no_compress)
        sys.exit(0 if success else 1)
    elif args.command == 'verify':
        success, message = manager.verify(args.file)
        print(f"\n{'验证成功' if success else '验证失败'}: {message}")
        sys.exit(0 if success else 1)
    elif args.command == 'restore':
        if not args.force:
            confirm = input("\n警告: 这将覆盖当前数据库！确认继续? (yes/no): ")
            if confirm.lower() not in ['yes', 'y']:
                print("已取消恢复操作")
                sys.exit(0)
        success, message = manager.restore(args.file)
        print(f"\n{'恢复成功' if success else '恢复失败'}: {message}")
        sys.exit(0 if success else 1)
    elif args.command == 'list':
        manager.print_backups()
    else:
        parser.print_help()


if __name__ == '__main__':
    main()
