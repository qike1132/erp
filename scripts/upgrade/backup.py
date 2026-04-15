"""
ERP系统依赖库升级备份脚本

功能:
1. 备份虚拟环境
2. 备份数据库
3. 备份配置文件
4. 备份代码快照

使用方法:
    python scripts/upgrade/backup.py --full
    python scripts/upgrade/backup.py --db-only
    python scripts/upgrade/backup.py --config-only
"""

import os
import sys
import shutil
import subprocess
import argparse
import json
import tarfile
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.parent
BACKUP_DIR = PROJECT_ROOT / 'backups' / 'upgrade'


class BackupManager:
    """备份管理器"""
    
    def __init__(self):
        self.backup_dir = BACKUP_DIR
        self.backup_dir.mkdir(parents=True, exist_ok=True)
        self.timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        
    def log(self, message: str, level: str = 'INFO'):
        """记录日志"""
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        log_line = f"[{timestamp}] [{level}] {message}"
        print(log_line)
        
        log_file = self.backup_dir / 'backup.log'
        with open(log_file, 'a', encoding='utf-8') as f:
            f.write(log_line + '\n')
    
    def backup_requirements(self, backup_path: Path):
        """备份依赖列表"""
        self.log("备份依赖列表...")
        
        req_file = PROJECT_ROOT / 'requirements.txt'
        if req_file.exists():
            shutil.copy(req_file, backup_path / 'requirements.txt')
        
        result = subprocess.run(
            [sys.executable, '-m', 'pip', 'freeze'],
            capture_output=True,
            text=True,
            cwd=PROJECT_ROOT
        )
        with open(backup_path / 'pip_freeze.txt', 'w', encoding='utf-8') as f:
            f.write(result.stdout)
        
        result = subprocess.run(
            [sys.executable, '-m', 'pip', 'list', '--format=json'],
            capture_output=True,
            text=True,
            cwd=PROJECT_ROOT
        )
        with open(backup_path / 'pip_list.json', 'w', encoding='utf-8') as f:
            f.write(result.stdout)
        
        self.log("依赖列表备份完成")
    
    def backup_config(self, backup_path: Path):
        """备份配置文件"""
        self.log("备份配置文件...")
        
        env_file = PROJECT_ROOT / '.env'
        if env_file.exists():
            shutil.copy(env_file, backup_path / '.env')
        
        env_dev = PROJECT_ROOT / '.env.development'
        if env_dev.exists():
            shutil.copy(env_dev, backup_path / '.env.development')
        
        env_prod = PROJECT_ROOT / '.env.production'
        if env_prod.exists():
            shutil.copy(env_prod, backup_path / '.env.production')
        
        config_dir = PROJECT_ROOT / 'config'
        if config_dir.exists():
            shutil.copytree(config_dir, backup_path / 'config')
        
        self.log("配置文件备份完成")
    
    def backup_database(self, backup_path: Path):
        """备份数据库"""
        self.log("备份数据库...")
        
        db_type = os.getenv('DB_TYPE', 'sqlite')
        
        if db_type == 'mysql':
            db_host = os.getenv('DB_HOST', 'localhost')
            db_port = os.getenv('DB_PORT', '3306')
            db_user = os.getenv('DB_USER', 'root')
            db_password = os.getenv('DB_PASSWORD', '')
            db_name = os.getenv('DB_NAME', 'erp_system')
            
            dump_file = backup_path / f'{db_name}.sql'
            
            cmd = [
                'mysqldump',
                f'-h{db_host}',
                f'-P{db_port}',
                f'-u{db_user}',
            ]
            if db_password:
                cmd.append(f'-p{db_password}')
            cmd.extend(['--single-transaction', '--routines', '--triggers', db_name])
            
            try:
                result = subprocess.run(cmd, capture_output=True, text=True)
                if result.returncode == 0:
                    with open(dump_file, 'w', encoding='utf-8') as f:
                        f.write(result.stdout)
                    self.log(f"MySQL数据库备份完成: {dump_file}")
                else:
                    self.log(f"MySQL备份失败: {result.stderr}", 'ERROR')
            except FileNotFoundError:
                self.log("mysqldump命令未找到，跳过MySQL备份", 'WARNING')
        else:
            db_file = PROJECT_ROOT / 'erp.db'
            if db_file.exists():
                shutil.copy(db_file, backup_path / 'erp.db')
                self.log(f"SQLite数据库备份完成")
            else:
                self.log("SQLite数据库文件不存在", 'WARNING')
    
    def backup_venv(self, backup_path: Path):
        """备份虚拟环境"""
        self.log("备份虚拟环境...")
        
        venv_dir = PROJECT_ROOT / 'venv'
        if not venv_dir.exists():
            venv_dir = PROJECT_ROOT / '.venv'
        
        if venv_dir.exists():
            venv_archive = backup_path / 'venv.tar.gz'
            try:
                with tarfile.open(venv_archive, 'w:gz') as tar:
                    tar.add(venv_dir, arcname='venv')
                self.log(f"虚拟环境备份完成: {venv_archive}")
            except Exception as e:
                self.log(f"虚拟环境备份失败: {e}", 'ERROR')
        else:
            self.log("虚拟环境目录不存在", 'WARNING')
    
    def backup_code(self, backup_path: Path):
        """备份代码快照"""
        self.log("创建代码快照...")
        
        try:
            result = subprocess.run(
                ['git', 'rev-parse', 'HEAD'],
                capture_output=True,
                text=True,
                cwd=PROJECT_ROOT
            )
            commit_hash = result.stdout.strip() if result.returncode == 0 else 'unknown'
            
            result = subprocess.run(
                ['git', 'status', '--porcelain'],
                capture_output=True,
                text=True,
                cwd=PROJECT_ROOT
            )
            has_changes = bool(result.stdout.strip())
            
            git_info = {
                'commit_hash': commit_hash,
                'has_uncommitted_changes': has_changes,
                'branch': 'unknown'
            }
            
            result = subprocess.run(
                ['git', 'branch', '--show-current'],
                capture_output=True,
                text=True,
                cwd=PROJECT_ROOT
            )
            if result.returncode == 0:
                git_info['branch'] = result.stdout.strip()
            
            with open(backup_path / 'git_info.json', 'w', encoding='utf-8') as f:
                json.dump(git_info, f, indent=2)
            
            if has_changes:
                result = subprocess.run(
                    ['git', 'diff'],
                    capture_output=True,
                    text=True,
                    cwd=PROJECT_ROOT
                )
                with open(backup_path / 'uncommitted_changes.patch', 'w', encoding='utf-8') as f:
                    f.write(result.stdout)
            
            self.log("代码快照创建完成")
            
        except Exception as e:
            self.log(f"代码快照创建失败: {e}", 'WARNING')
    
    def create_manifest(self, backup_path: Path, backup_type: str):
        """创建备份清单"""
        manifest = {
            'timestamp': self.timestamp,
            'backup_type': backup_type,
            'python_version': sys.version,
            'platform': sys.platform,
            'project_root': str(PROJECT_ROOT),
            'backup_path': str(backup_path),
            'created_at': datetime.now().isoformat(),
            'files': []
        }
        
        for file_path in backup_path.iterdir():
            if file_path.is_file():
                manifest['files'].append({
                    'name': file_path.name,
                    'size': file_path.stat().st_size
                })
        
        with open(backup_path / 'manifest.json', 'w', encoding='utf-8') as f:
            json.dump(manifest, f, indent=2, ensure_ascii=False)
        
        self.log("备份清单创建完成")
    
    def full_backup(self):
        """完整备份"""
        self.log("=" * 50)
        self.log("开始完整备份...")
        self.log("=" * 50)
        
        backup_path = self.backup_dir / f'backup_{self.timestamp}'
        backup_path.mkdir(parents=True, exist_ok=True)
        
        self.backup_requirements(backup_path)
        self.backup_config(backup_path)
        self.backup_database(backup_path)
        self.backup_venv(backup_path)
        self.backup_code(backup_path)
        self.create_manifest(backup_path, 'full')
        
        self.log("=" * 50)
        self.log(f"完整备份完成: {backup_path}")
        self.log("=" * 50)
        
        return str(backup_path)
    
    def db_backup(self):
        """仅备份数据库"""
        self.log("开始数据库备份...")
        
        backup_path = self.backup_dir / f'db_backup_{self.timestamp}'
        backup_path.mkdir(parents=True, exist_ok=True)
        
        self.backup_database(backup_path)
        self.create_manifest(backup_path, 'database')
        
        self.log(f"数据库备份完成: {backup_path}")
        return str(backup_path)
    
    def config_backup(self):
        """仅备份配置"""
        self.log("开始配置备份...")
        
        backup_path = self.backup_dir / f'config_backup_{self.timestamp}'
        backup_path.mkdir(parents=True, exist_ok=True)
        
        self.backup_config(backup_path)
        self.create_manifest(backup_path, 'config')
        
        self.log(f"配置备份完成: {backup_path}")
        return str(backup_path)
    
    def list_backups(self):
        """列出所有备份"""
        self.log("可用备份列表:")
        self.log("-" * 60)
        
        backups = []
        for backup_path in self.backup_dir.iterdir():
            if backup_path.is_dir() and backup_path.name.startswith(('backup_', 'db_backup_', 'config_backup_')):
                manifest_file = backup_path / 'manifest.json'
                if manifest_file.exists():
                    with open(manifest_file, 'r', encoding='utf-8') as f:
                        manifest = json.load(f)
                    backups.append({
                        'path': str(backup_path),
                        'timestamp': manifest.get('timestamp', 'unknown'),
                        'type': manifest.get('backup_type', 'unknown'),
                        'created_at': manifest.get('created_at', 'unknown')
                    })
        
        backups.sort(key=lambda x: x['timestamp'], reverse=True)
        
        for i, backup in enumerate(backups, 1):
            self.log(f"{i}. [{backup['type']}] {backup['timestamp']} - {backup['path']}")
        
        return backups


def main():
    parser = argparse.ArgumentParser(description='ERP系统备份工具')
    parser.add_argument(
        '--full',
        action='store_true',
        help='执行完整备份'
    )
    parser.add_argument(
        '--db-only',
        action='store_true',
        help='仅备份数据库'
    )
    parser.add_argument(
        '--config-only',
        action='store_true',
        help='仅备份配置'
    )
    parser.add_argument(
        '--list',
        action='store_true',
        help='列出所有备份'
    )
    
    args = parser.parse_args()
    
    manager = BackupManager()
    
    if args.full:
        manager.full_backup()
    elif args.db_only:
        manager.db_backup()
    elif args.config_only:
        manager.config_backup()
    elif args.list:
        manager.list_backups()
    else:
        parser.print_help()


if __name__ == '__main__':
    main()
