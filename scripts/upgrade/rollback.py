"""
ERP系统依赖库升级回滚脚本

功能:
1. 备份当前环境
2. 回滚到指定版本
3. 恢复数据库
4. 验证服务状态

使用方法:
    python scripts/upgrade/rollback.py --action backup
    python scripts/upgrade/rollback.py --action rollback --version v1.0.0
    python scripts/upgrade/rollback.py --action verify
"""

import os
import sys
import shutil
import subprocess
import argparse
import json
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.parent
BACKUP_DIR = PROJECT_ROOT / 'backups' / 'upgrade'
LOG_FILE = BACKUP_DIR / 'rollback.log'


class RollbackManager:
    """回滚管理器"""
    
    def __init__(self):
        self.backup_dir = BACKUP_DIR
        self.backup_dir.mkdir(parents=True, exist_ok=True)
        self.log_file = LOG_FILE
        
    def log(self, message: str, level: str = 'INFO'):
        """记录日志"""
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        log_line = f"[{timestamp}] [{level}] {message}"
        print(log_line)
        with open(self.log_file, 'a', encoding='utf-8') as f:
            f.write(log_line + '\n')
    
    def backup_environment(self):
        """备份当前环境"""
        self.log("开始备份当前环境...")
        
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        backup_path = self.backup_dir / f'backup_{timestamp}'
        backup_path.mkdir(parents=True, exist_ok=True)
        
        try:
            self.log("备份requirements.txt...")
            req_file = PROJECT_ROOT / 'requirements.txt'
            if req_file.exists():
                shutil.copy(req_file, backup_path / 'requirements.txt')
            
            self.log("备份虚拟环境列表...")
            result = subprocess.run(
                [sys.executable, '-m', 'pip', 'freeze'],
                capture_output=True,
                text=True,
                cwd=PROJECT_ROOT
            )
            with open(backup_path / 'pip_freeze.txt', 'w', encoding='utf-8') as f:
                f.write(result.stdout)
            
            self.log("备份配置文件...")
            env_file = PROJECT_ROOT / '.env'
            if env_file.exists():
                shutil.copy(env_file, backup_path / '.env')
            
            config_dir = PROJECT_ROOT / 'config'
            if config_dir.exists():
                shutil.copytree(config_dir, backup_path / 'config')
            
            self.log("备份数据库...")
            db_file = PROJECT_ROOT / 'erp.db'
            if db_file.exists():
                shutil.copy(db_file, backup_path / 'erp.db')
            
            manifest = {
                'timestamp': timestamp,
                'python_version': sys.version,
                'platform': sys.platform,
                'backup_path': str(backup_path)
            }
            with open(backup_path / 'manifest.json', 'w', encoding='utf-8') as f:
                json.dump(manifest, f, indent=2, ensure_ascii=False)
            
            self.log(f"备份完成: {backup_path}", 'SUCCESS')
            return str(backup_path)
            
        except Exception as e:
            self.log(f"备份失败: {e}", 'ERROR')
            raise
    
    def list_backups(self):
        """列出所有备份"""
        self.log("列出所有备份...")
        
        backups = []
        for backup_path in self.backup_dir.iterdir():
            if backup_path.is_dir() and backup_path.name.startswith('backup_'):
                manifest_file = backup_path / 'manifest.json'
                if manifest_file.exists():
                    with open(manifest_file, 'r', encoding='utf-8') as f:
                        manifest = json.load(f)
                    backups.append({
                        'path': str(backup_path),
                        'timestamp': manifest.get('timestamp', 'unknown'),
                        'python_version': manifest.get('python_version', 'unknown')
                    })
        
        backups.sort(key=lambda x: x['timestamp'], reverse=True)
        
        print("\n可用备份列表:")
        print("-" * 60)
        for i, backup in enumerate(backups, 1):
            print(f"{i}. {backup['timestamp']} - {backup['path']}")
        
        return backups
    
    def rollback(self, backup_path: str = None, version: str = None):
        """回滚到指定版本"""
        self.log("开始回滚...")
        
        if backup_path is None:
            backups = self.list_backups()
            if not backups:
                self.log("没有可用的备份", 'ERROR')
                return False
            backup_path = backups[0]['path']
        
        backup_path = Path(backup_path)
        if not backup_path.exists():
            self.log(f"备份路径不存在: {backup_path}", 'ERROR')
            return False
        
        try:
            self.log(f"从 {backup_path} 恢复...")
            
            self.log("恢复requirements.txt...")
            req_backup = backup_path / 'requirements.txt'
            if req_backup.exists():
                shutil.copy(req_backup, PROJECT_ROOT / 'requirements.txt')
            
            self.log("恢复配置文件...")
            env_backup = backup_path / '.env'
            if env_backup.exists():
                shutil.copy(env_backup, PROJECT_ROOT / '.env')
            
            self.log("恢复数据库...")
            db_backup = backup_path / 'erp.db'
            if db_backup.exists():
                shutil.copy(db_backup, PROJECT_ROOT / 'erp.db')
            
            self.log("重新安装依赖...")
            subprocess.run(
                [sys.executable, '-m', 'pip', 'install', '-r', 
                 str(PROJECT_ROOT / 'requirements.txt')],
                cwd=PROJECT_ROOT
            )
            
            if version:
                self.log(f"切换到Git版本: {version}")
                subprocess.run(
                    ['git', 'checkout', version],
                    cwd=PROJECT_ROOT
                )
            
            self.log("回滚完成", 'SUCCESS')
            return True
            
        except Exception as e:
            self.log(f"回滚失败: {e}", 'ERROR')
            return False
    
    def verify_service(self):
        """验证服务状态"""
        self.log("验证服务状态...")
        
        checks = []
        
        try:
            self.log("检查Python环境...")
            result = subprocess.run(
                [sys.executable, '-c', 'import flask; print(flask.__version__)'],
                capture_output=True,
                text=True
            )
            if result.returncode == 0:
                checks.append(('Flask导入', True, result.stdout.strip()))
            else:
                checks.append(('Flask导入', False, result.stderr))
        except Exception as e:
            checks.append(('Flask导入', False, str(e)))
        
        try:
            self.log("检查数据库连接...")
            sys.path.insert(0, str(PROJECT_ROOT))
            from app import db, create_app
            app = create_app()
            with app.app_context():
                db.session.execute(db.text('SELECT 1'))
            checks.append(('数据库连接', True, 'OK'))
        except Exception as e:
            checks.append(('数据库连接', False, str(e)))
        
        try:
            self.log("检查新库导入...")
            imports = ['phonenumbers', 'chardet', 'pypinyin', 'arrow', 'bleach']
            for lib in imports:
                __import__(lib)
            checks.append(('新库导入', True, 'OK'))
        except Exception as e:
            checks.append(('新库导入', False, str(e)))
        
        print("\n验证结果:")
        print("-" * 60)
        all_passed = True
        for name, passed, message in checks:
            status = "✓ 通过" if passed else "✗ 失败"
            print(f"{name}: {status} - {message}")
            if not passed:
                all_passed = False
        
        if all_passed:
            self.log("所有验证通过", 'SUCCESS')
        else:
            self.log("存在验证失败项", 'WARNING')
        
        return all_passed
    
    def emergency_rollback(self):
        """紧急回滚"""
        self.log("执行紧急回滚...", 'WARNING')
        
        try:
            self.log("停止服务...")
            if sys.platform == 'win32':
                subprocess.run(['taskkill', '/F', '/IM', 'python.exe'], 
                             capture_output=True)
            else:
                subprocess.run(['pkill', '-f', 'python.*run.py'], 
                             capture_output=True)
            
            self.log("切换到main分支...")
            subprocess.run(['git', 'checkout', 'main'], cwd=PROJECT_ROOT)
            subprocess.run(['git', 'pull', 'origin', 'main'], cwd=PROJECT_ROOT)
            
            self.log("恢复虚拟环境...")
            subprocess.run(
                [sys.executable, '-m', 'pip', 'install', '-r', 
                 str(PROJECT_ROOT / 'requirements.txt')],
                cwd=PROJECT_ROOT
            )
            
            self.log("重启服务...")
            subprocess.Popen(
                [sys.executable, 'run.py'],
                cwd=PROJECT_ROOT,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE
            )
            
            self.log("紧急回滚完成", 'SUCCESS')
            return True
            
        except Exception as e:
            self.log(f"紧急回滚失败: {e}", 'ERROR')
            return False


def main():
    parser = argparse.ArgumentParser(description='ERP系统依赖库升级回滚工具')
    parser.add_argument(
        '--action',
        choices=['backup', 'rollback', 'verify', 'list', 'emergency'],
        required=True,
        help='执行的操作'
    )
    parser.add_argument(
        '--backup-path',
        help='备份路径'
    )
    parser.add_argument(
        '--version',
        help='Git版本标签'
    )
    
    args = parser.parse_args()
    
    manager = RollbackManager()
    
    if args.action == 'backup':
        manager.backup_environment()
    elif args.action == 'rollback':
        manager.rollback(args.backup_path, args.version)
    elif args.action == 'verify':
        manager.verify_service()
    elif args.action == 'list':
        manager.list_backups()
    elif args.action == 'emergency':
        manager.emergency_rollback()


if __name__ == '__main__':
    main()
