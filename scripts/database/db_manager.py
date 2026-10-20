"""
ERP系统数据库管理工具 v3.0

功能:
1. 数据库备份（PostgreSQL pg_dump / MySQL mysqldump）
2. 备份验证（含校验和、行数统计、内容完整性检查）
3. 数据库恢复（PostgreSQL psql / MySQL mysql）
4. 备份文件管理（列表、删除、清理过期）
5. 增量备份管理

使用方法:
    python scripts/database/db_manager.py backup
    python scripts/database/db_manager.py verify --file <backup_file>
    python scripts/database/db_manager.py restore --file <backup_file>
    python scripts/database/db_manager.py list
    python scripts/database/db_manager.py cleanup --keep 7   # 仅保留最近7天
"""

import argparse
import gzip
import hashlib
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
# scripts/ 下的 _prod_write_guard（本文件位于 scripts/database/）
sys.path.insert(0, str(Path(__file__).parent.parent))
# scripts/database/ 下的 restore_core（审计 F1-7：恢复实现的唯一来源）
sys.path.insert(0, str(Path(__file__).parent))

import restore_core

BACKUP_DIR = PROJECT_ROOT / 'backups'
DAILY_DIR = BACKUP_DIR / 'daily'
WEEKLY_DIR = BACKUP_DIR / 'weekly'
MONTHLY_DIR = BACKUP_DIR / 'monthly'
MANUAL_DIR = BACKUP_DIR / 'manual'

RECOVERY_LOG_DIR = BACKUP_DIR / 'recovery_logs'


def _human_size(size: int) -> str:
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if size < 1024.0:
            return f"{size:.2f} {unit}"
        size /= 1024.0
    return f"{size:.2f} PB"


class DatabaseManager:
    """数据库管理器（PostgreSQL 优先，兼容 MySQL）"""

    def __init__(self):
        self.db_type = self._detect_db_type()
        self.timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        self.backup_dirs = [
            DAILY_DIR, WEEKLY_DIR, MONTHLY_DIR, MANUAL_DIR
        ]
        for dir_path in self.backup_dirs:
            dir_path.mkdir(parents=True, exist_ok=True)
        RECOVERY_LOG_DIR.mkdir(parents=True, exist_ok=True)
        self.load_env()

    def _detect_db_type(self) -> str:
        db_type = os.getenv('DB_TYPE', '').lower()
        if db_type in ('postgresql', 'postgres', 'pgsql', 'pg'):
            return 'postgresql'
        if db_type in ('mysql', 'mariadb'):
            return 'mysql'
        port = os.getenv('DB_PORT', '')
        if port == '5432':
            return 'postgresql'
        if port == '3306':
            return 'mysql'
        return 'postgresql'

    def load_env(self):
        try:
            from dotenv import load_dotenv
            load_dotenv()
        except ImportError:
            pass

    def log(self, message: str, level: str = 'INFO'):
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        log_line = f"[{timestamp}] [{level}] {message}"
        print(log_line)

        log_file = BACKUP_DIR / 'db_manager.log'
        try:
            with open(log_file, 'a', encoding='utf-8') as f:
                f.write(log_line + '\n')
        except Exception as e:
            print(f"[WARN] 无法写入日志文件: {e}")

    # ============================================================
    # Config Helpers
    # ============================================================

    def get_db_config(self) -> dict[str, str]:
        return {
            'host': os.getenv('DB_HOST', 'localhost'),
            'port': os.getenv('DB_PORT', '5432' if self.db_type == 'postgresql' else '3306'),
            'user': os.getenv('DB_USER', 'erp_app'),
            'password': os.getenv('DB_PASSWORD', ''),
            'database': os.getenv('DB_NAME', 'erp_system'),
        }

    # ============================================================
    # Checksum Helpers
    # ============================================================

    def calculate_checksum(self, file_path: Path) -> str:
        sha256_hash = hashlib.sha256()
        with open(file_path, 'rb') as f:
            for chunk in iter(lambda: f.read(65536), b''):
                sha256_hash.update(chunk)
        return sha256_hash.hexdigest()

    def compress_file(self, file_path: Path) -> Path:
        compressed_path = Path(str(file_path) + '.gz')
        with open(file_path, 'rb') as f_in, gzip.open(compressed_path, 'wb') as f_out:
            shutil.copyfileobj(f_in, f_out)
        return compressed_path

    def decompress_file(self, file_path: Path) -> Path:
        if not str(file_path).endswith('.gz'):
            return file_path
        decompressed_path = Path(str(file_path)[:-3])
        with gzip.open(file_path, 'rb') as f_in, open(decompressed_path, 'wb') as f_out:
            shutil.copyfileobj(f_in, f_out)
        return decompressed_path

    # ============================================================
    # Backup
    # ============================================================

    def backup_postgresql(self, backup_dir: Path, compress: bool = True) -> tuple[bool, str, Path | None]:
        config = self.get_db_config()
        backup_file = backup_dir / f'erp_system_backup_{self.timestamp}.sql'

        env = os.environ.copy()
        env['PGPASSWORD'] = config['password']

        cmd = [
            'pg_dump',
            '-h', config['host'],
            '-p', config['port'],
            '-U', config['user'],
            '--no-owner',
            '--no-privileges',
            config['database'],
        ]

        self.log(f"执行 pg_dump: {' '.join(cmd[:-1])} ****")

        try:
            with open(backup_file, 'wb') as f:
                result = subprocess.run(
                    cmd, stdout=f, stderr=subprocess.PIPE, env=env, timeout=3600
                )

            if result.returncode == 0:
                file_size = backup_file.stat().st_size
                self.log(f"PostgreSQL 数据库已导出: {backup_file} ({_human_size(file_size)})")

                if compress and file_size > 1024:
                    compressed_file = self.compress_file(backup_file)
                    backup_file.unlink()
                    backup_file = compressed_file
                    self.log(f"备份文件已压缩: {backup_file} ({_human_size(backup_file.stat().st_size)})")

                return True, f"PostgreSQL 备份成功: {backup_file.name}", backup_file
            else:
                stderr_text = result.stderr.decode('utf-8', errors='replace')
                return False, f"pg_dump 失败: {stderr_text}", None

        except FileNotFoundError:
            return False, "pg_dump 命令未找到，请确保 PostgreSQL 客户端工具已安装并在 PATH 中", None
        except subprocess.TimeoutExpired:
            return False, "pg_dump 执行超时（超过 3600 秒）", None
        except Exception as e:
            return False, f"PostgreSQL 备份失败: {e!s}", None

    def backup_mysql(self, backup_dir: Path, compress: bool = True) -> tuple[bool, str, Path | None]:
        config = self.get_db_config()
        backup_file = backup_dir / f'erp_system_backup_{self.timestamp}.sql'

        cmd = [
            'mysqldump',
            f'-h{config["host"]}',
            f'-P{config["port"]}',
            f'-u{config["user"]}',
        ]
        if config['password']:
            cmd.append(f'-p{config["password"]}')
        cmd.extend([
            '--single-transaction', '--routines', '--triggers',
            '--skip-lock-tables', config['database'],
        ])

        try:
            with open(backup_file, 'wb') as f:
                result = subprocess.run(
                    cmd, stdout=f, stderr=subprocess.PIPE, timeout=3600
                )

            if result.returncode == 0:
                self.log(f"MySQL 数据库已导出: {backup_file}")

                if compress:
                    compressed_file = self.compress_file(backup_file)
                    backup_file.unlink()
                    backup_file = compressed_file
                    self.log(f"备份文件已压缩: {backup_file}")

                return True, f"MySQL 备份成功: {backup_file}", backup_file
            else:
                stderr_text = result.stderr.decode('utf-8', errors='replace')
                return False, f"mysqldump 失败: {stderr_text}", None
        except FileNotFoundError:
            return False, "mysqldump 命令未找到，请确保 MySQL 已安装", None
        except Exception as e:
            return False, f"MySQL 备份失败: {e!s}", None

    def backup(self, backup_type: str = 'manual', compress: bool = True) -> tuple[bool, str]:
        self.log("=" * 60)
        self.log(f"开始数据库备份 - 类型: {backup_type} | 数据库: {self.db_type}")
        self.log("=" * 60)

        backup_dir_map = {
            'daily': DAILY_DIR,
            'weekly': WEEKLY_DIR,
            'monthly': MONTHLY_DIR,
            'manual': MANUAL_DIR,
        }
        backup_dir = backup_dir_map.get(backup_type, MANUAL_DIR)

        if self.db_type == 'postgresql':
            success, message, _ = self.backup_postgresql(backup_dir, compress)
        else:
            success, message, _ = self.backup_mysql(backup_dir, compress)

        if success:
            self.log("=" * 60)
            self.log("备份完成")
            self.log("=" * 60)
        else:
            self.log(message, 'ERROR')

        return success, message

    # ============================================================
    # Verify
    # ============================================================

    def verify_sql_file(self, backup_file: Path) -> tuple[bool, str, dict]:
        info = {'size': backup_file.stat().st_size, 'tables': []}

        with open(backup_file, encoding='utf-8', errors='ignore') as f:
            content = f.read(100000)

        has_create = 'CREATE TABLE' in content or 'CREATE DATABASE' in content
        has_insert = 'INSERT INTO' in content or 'COPY' in content

        if not has_create and not has_insert:
            return False, "备份文件不包含有效的数据库语句", info

        if info['size'] < 100:
            return False, f"备份文件过小 ({info['size']} 字节)", info

        # Count tables by scanning CREATE TABLE statements
        table_count = content.count('CREATE TABLE') + content.count('CREATE TABLE IF NOT EXISTS')
        info['tables'].append(f"检测到约 {table_count} 个表定义")

        checksum = self.calculate_checksum(backup_file)
        info['sha256'] = checksum

        return True, f"SQL 备份文件验证通过 ({_human_size(info['size'])}, SHA256: {checksum[:16]}...)", info

    def verify(self, backup_file: str) -> tuple[bool, str, dict]:
        file_path = Path(backup_file)
        if not file_path.exists():
            return False, f"备份文件不存在: {backup_file}", {}

        self.log(f"验证备份文件: {file_path}")

        original_path = file_path
        if str(file_path).endswith('.gz'):
            self.log("解压中...")
            file_path = self.decompress_file(file_path)

        try:
            if str(file_path).endswith('.sql'):
                success, message, info = self.verify_sql_file(file_path)
            elif str(file_path).endswith('.zip'):
                success, message, info = self._verify_zip_backup(file_path)
            else:
                success, message, info = False, f"无法识别的备份文件类型: {file_path}", {}
        finally:
            if original_path != file_path and file_path.exists():
                file_path.unlink()

        return success, message, info

    def _verify_zip_backup(self, file_path: Path) -> tuple[bool, str, dict]:
        import zipfile
        try:
            with zipfile.ZipFile(file_path, 'r') as zf:
                names = zf.namelist()
                info = {
                    'size': file_path.stat().st_size,
                    'files': names,
                    'has_manifest': 'manifest.json' in names,
                    'has_database': any(n.startswith('database/') for n in names),
                    'has_filestore': any(n.startswith('filestore/') for n in names),
                }
                if 'manifest.json' in names:
                    manifest = json.loads(zf.read('manifest.json'))
                    info['manifest'] = {
                        'version': manifest.get('version'),
                        'type': manifest.get('type', 'unknown'),
                        'exported_at': manifest.get('exported_at'),
                        'exported_by': manifest.get('exported_by'),
                        'table_count': manifest.get('table_count'),
                        'total_rows': manifest.get('total_rows'),
                    }
                checksum = self.calculate_checksum(file_path)
                info['sha256'] = checksum
                return True, f"ZIP 备份验证通过 (类型: {info['manifest'].get('type', 'unknown')})", info
        except Exception as e:
            return False, f"ZIP 备份验证失败: {e}", {}

    # ============================================================
    # Restore
    # ============================================================

    def restore_postgresql(self, backup_file: Path, *, require_consent: bool = True) -> tuple[bool, str]:
        """PostgreSQL 恢复 —— 实现收敛在 restore_core（审计 F1-7）。

        恢复前备份 fail-closed、psql ON_ERROR_STOP=1、恢复后落地校验、
        写生产库授权，全部由 restore_core 统一负责；本方法只做适配与汇报。
        """
        outcome = restore_core.restore_from_file(
            Path(backup_file),
            config=self.get_db_config(),
            require_consent=require_consent,
            log=self.log,
        )
        return outcome.ok, outcome.message

    def restore_mysql(self, backup_file: Path) -> tuple[bool, str]:
        config = self.get_db_config()

        # Pre-restore backup
        # 失败必须中止恢复 —— 与 PostgreSQL 路径同口径（此前这里丢弃了返回值，
        # 备份失败也照样往下恢复，等于没有回退手段）。
        self.log("正在创建恢复前备份...")
        pre_backup_dir = BACKUP_DIR / 'pre_restore'
        pre_backup_dir.mkdir(parents=True, exist_ok=True)
        backup_ok, backup_msg, _ = self.backup_mysql(pre_backup_dir, compress=False)
        if not backup_ok:
            return False, f"恢复前备份失败，已中止恢复以避免数据丢失: {backup_msg}"

        self.log("恢复 MySQL 数据库中...")
        cmd = ['mysql', f'-h{config["host"]}', f'-P{config["port"]}', f'-u{config["user"]}']
        if config['password']:
            cmd.append(f'-p{config["password"]}')
        cmd.append(config['database'])

        try:
            with open(backup_file, encoding='utf-8') as f:
                result = subprocess.run(
                    cmd, stdin=f, capture_output=True, text=True, timeout=600
                )
            if result.returncode == 0:
                return True, "MySQL 数据库恢复完成"
            else:
                return False, f"MySQL 恢复失败: {result.stderr}"
        except FileNotFoundError:
            return False, "mysql 命令未找到，请确保 MySQL 已安装"
        except Exception as e:
            return False, f"MySQL 恢复失败: {e!s}"

    def restore(self, backup_file: str, *, require_consent: bool = True) -> tuple[bool, str]:
        file_path = Path(backup_file)
        if not file_path.exists():
            return False, f"备份文件不存在: {backup_file}"

        self.log("=" * 60)
        self.log("警告: 即将恢复数据库，这将覆盖当前数据！")
        self.log(f"数据库类型: {self.db_type}")
        self.log("=" * 60)

        original_path = file_path
        if self.db_type == 'postgresql':
            # 审计 F1-7：PostgreSQL 恢复收敛到 restore_core —— 备份格式解析与
            # 恢复序列（恢复前备份 / DROP+CREATE / psql / 落地校验）同源，
            # 与 restore_db.py 走的是同一份实现。
            try:
                success, message = self.restore_postgresql(file_path, require_consent=require_consent)
            except (restore_core.UnsupportedBackupFormatError, restore_core.RestoreError) as e:
                success, message = False, f"无法识别的备份文件类型: {e}"
        else:
            if str(file_path).endswith('.gz'):
                self.log("解压备份文件...")
                file_path = self.decompress_file(file_path)
            try:
                if str(file_path).endswith('.sql'):
                    success, message = self.restore_mysql(file_path)
                else:
                    success, message = False, f"无法识别的备份文件类型: {file_path}"
            finally:
                if original_path != file_path and file_path.exists():
                    file_path.unlink()

        # Log recovery event
        self._log_recovery_event(file_path.name if file_path.exists() else original_path.name, success, message)

        if success:
            self.log("=" * 60)
            self.log("恢复完成")
            self.log("=" * 60)
        else:
            self.log(message, 'ERROR')

        return success, message

    def _log_recovery_event(self, filename: str, success: bool, message: str):
        log_entry = {
            'timestamp': datetime.now().isoformat(),
            'backup_file': filename,
            'db_type': self.db_type,
            'success': success,
            'message': message,
        }
        log_file = RECOVERY_LOG_DIR / f'recovery_{self.timestamp}.json'
        try:
            with open(log_file, 'w', encoding='utf-8') as f:
                json.dump(log_entry, f, indent=2, ensure_ascii=False)
        except Exception:  # noqa: S110  # defensive: 恢复日志写入失败不影响恢复主流程
            pass

    # ============================================================
    # List / Cleanup
    # ============================================================

    def list_backups(self) -> list[dict[str, Any]]:
        backups = []
        for backup_dir in self.backup_dirs:
            if not backup_dir.exists():
                continue
            for file_path in backup_dir.iterdir():
                if file_path.is_file() and not file_path.name.startswith('manifest_'):
                    if file_path.name.endswith(('.sql', '.sql.gz', '.zip', '.json')):
                        stat = file_path.stat()
                        backups.append({
                            'path': str(file_path),
                            'name': file_path.name,
                            'directory': backup_dir.name,
                            'size': stat.st_size,
                            'size_human': _human_size(stat.st_size),
                            'created': datetime.fromtimestamp(stat.st_ctime).isoformat(),
                            'modified': datetime.fromtimestamp(stat.st_mtime).isoformat(),
                        })
        backups.sort(key=lambda x: x['modified'], reverse=True)
        return backups

    def print_backups(self):
        backups = self.list_backups()
        if not backups:
            self.log("没有找到备份文件")
            return

        self.log("=" * 110)
        header = f"{'#':<4} {'文件名':<45} {'目录':<10} {'大小':<12} {'修改时间':<20}"
        self.log(header)
        self.log("=" * 110)

        for i, b in enumerate(backups, 1):
            modified = datetime.fromisoformat(b['modified']).strftime('%Y-%m-%d %H:%M')
            self.log(
                f"{i:<4} {b['name']:<45} {b['directory']:<10} "
                f"{b['size_human']:<12} {modified:<20}"
            )

        total_size = sum(b['size'] for b in backups)
        self.log("=" * 110)
        self.log(f"共 {len(backups)} 个备份文件，总大小 {_human_size(total_size)}")

    def cleanup(self, keep_days: int = 7, dry_run: bool = False):
        cutoff = datetime.now() - timedelta(days=keep_days)
        deleted = []
        total_freed = 0

        for backup in self.list_backups():
            modified = datetime.fromisoformat(backup['modified'])
            if modified < cutoff:
                if dry_run:
                    self.log(f"[DRY RUN] 将删除: {backup['name']} ({backup['size_human']})")
                else:
                    try:
                        Path(backup['path']).unlink()
                        deleted.append(backup['name'])
                        total_freed += backup['size']
                        self.log(f"已删除: {backup['name']} ({backup['size_human']})")
                    except Exception as e:
                        self.log(f"删除失败 {backup['name']}: {e}", 'ERROR')

        if dry_run:
            self.log(f"[DRY RUN] 将删除 {len(deleted)} 个文件")
        else:
            self.log(f"清理完成: 删除 {len(deleted)} 个文件，释放 {_human_size(total_freed)}")


def main():
    parser = argparse.ArgumentParser(
        description='ERP系统数据库管理工具 v3.0 (PostgreSQL / MySQL)',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python db_manager.py backup --type daily
  python db_manager.py verify --file backups/manual/erp_system_backup_20260501_120000.sql.gz
  python db_manager.py restore --file backups/manual/erp_system_backup_20260501_120000.sql.gz
  python db_manager.py list
  python db_manager.py cleanup --keep 7
        """,
    )
    subparsers = parser.add_subparsers(title='命令', dest='command')

    backup_parser = subparsers.add_parser('backup', help='备份数据库')
    backup_parser.add_argument(
        '--type', choices=['daily', 'weekly', 'monthly', 'manual'],
        default='manual', help='备份类型'
    )
    backup_parser.add_argument('--no-compress', action='store_true', help='不压缩备份文件')

    verify_parser = subparsers.add_parser('verify', help='验证备份文件')
    verify_parser.add_argument('--file', required=True, help='备份文件路径')

    restore_parser = subparsers.add_parser('restore', help='恢复数据库')
    restore_parser.add_argument('--file', required=True, help='备份文件路径')
    restore_parser.add_argument('--force', action='store_true', help='跳过确认直接恢复')

    subparsers.add_parser('list', help='列出所有备份文件')

    cleanup_parser = subparsers.add_parser('cleanup', help='清理过期备份文件')
    cleanup_parser.add_argument('--keep', type=int, default=7, help='保留最近 N 天的备份（默认 7）')
    cleanup_parser.add_argument('--dry-run', action='store_true', help='仅列出将删除的文件，不实际操作')

    args = parser.parse_args()
    manager = DatabaseManager()

    manager.log(f"数据库管理工具 v3.0 | 检测到数据库类型: {manager.db_type}")

    if args.command == 'backup':
        success, message = manager.backup(args.type, not args.no_compress)
        sys.exit(0 if success else 1)

    elif args.command == 'verify':
        success, message, info = manager.verify(args.file)
        verdict = '验证通过' if success else '验证失败'
        print(f"\n{verdict}: {message}")
        if info:
            print(f"详细信息: {json.dumps({k: v for k, v in info.items() if k != 'files'}, indent=2, ensure_ascii=False)}")
        sys.exit(0 if success else 1)

    elif args.command == 'restore':
        # F3-9：恢复会覆盖生产库，--force 只跳交互、不跳写护栏
        from _prod_write_guard import require_prod_write_consent
        require_prod_write_consent(
            f'数据库恢复（{args.file}）',
            hint='不可逆；请先确认已备份当前库',
        )
        if not args.force:
            confirm = input("\n警告: 这将覆盖当前数据库！确认继续? (yes/no): ")
            if confirm.lower() not in ('yes', 'y'):
                print("已取消恢复操作")
                sys.exit(0)
        success, message = manager.restore(args.file)
        print(f"\n{'恢复成功' if success else '恢复失败'}: {message}")
        sys.exit(0 if success else 1)

    elif args.command == 'list':
        manager.print_backups()

    elif args.command == 'cleanup':
        manager.cleanup(args.keep, args.dry_run)

    else:
        parser.print_help()


if __name__ == '__main__':
    main()
