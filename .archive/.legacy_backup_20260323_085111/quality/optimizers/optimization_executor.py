"""
优化执行器
实现安全的代码优化执行机制,包含备份、执行、验证、回滚功能
"""
import os
import shutil
import json
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Any, Optional


class BackupManager:
    """备份管理器"""
    
    def __init__(self, project_path: str):
        self.project_path = Path(project_path)
        self.backup_dir = self.project_path / '.optimization_backups'
        self.backup_dir.mkdir(exist_ok=True)
    
    def create_backup(self, backup_name: str = None) -> str:
        """创建备份"""
        if not backup_name:
            backup_name = f"backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        
        backup_path = self.backup_dir / backup_name
        backup_path.mkdir(exist_ok=True)
        
        # 备份关键文件
        key_files = [
            'app.py',
            'requirements.txt',
            'pytest.ini'
        ]
        
        backed_up_files = []
        for file in key_files:
            source = self.project_path / file
            if source.exists():
                dest = backup_path / file
                shutil.copy2(source, dest)
                backed_up_files.append(file)
        
        # 备份utils目录
        utils_dir = self.project_path / 'utils'
        if utils_dir.exists():
            dest_utils = backup_path / 'utils'
            if dest_utils.exists():
                shutil.rmtree(dest_utils)
            shutil.copytree(utils_dir, dest_utils)
            backed_up_files.append('utils/')
        
        # 记录备份信息
        backup_info = {
            'name': backup_name,
            'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'files': backed_up_files
        }
        
        info_file = backup_path / 'backup_info.json'
        with open(info_file, 'w', encoding='utf-8') as f:
            json.dump(backup_info, f, ensure_ascii=False, indent=2)
        
        print(f"[OK] 备份创建成功: {backup_name}")
        print(f"   备份文件: {len(backed_up_files)} 个")
        
        return backup_name
    
    def list_backups(self) -> List[Dict[str, Any]]:
        """列出所有备份"""
        backups = []
        
        for backup_path in self.backup_dir.iterdir():
            if backup_path.is_dir():
                info_file = backup_path / 'backup_info.json'
                if info_file.exists():
                    with open(info_file, 'r', encoding='utf-8') as f:
                        backup_info = json.load(f)
                    backups.append(backup_info)
        
        # 按时间排序
        backups.sort(key=lambda x: x['timestamp'], reverse=True)
        
        return backups
    
    def restore_backup(self, backup_name: str) -> bool:
        """恢复备份"""
        backup_path = self.backup_dir / backup_name
        
        if not backup_path.exists():
            print(f"[ERROR] 备份不存在: {backup_name}")
            return False
        
        try:
            # 恢复文件
            for item in backup_path.iterdir():
                if item.name == 'backup_info.json':
                    continue
                
                if item.is_file():
                    dest = self.project_path / item.name
                    shutil.copy2(item, dest)
                elif item.is_dir():
                    dest = self.project_path / item.name
                    if dest.exists():
                        shutil.rmtree(dest)
                    shutil.copytree(item, dest)
            
            print(f"[OK] 备份恢复成功: {backup_name}")
            return True
            
        except Exception as e:
            print(f"[ERROR] 备份恢复失败: {e}")
            return False


class ChangeLogger:
    """变更日志记录器"""
    
    def __init__(self, project_path: str):
        self.project_path = Path(project_path)
        self.log_file = self.project_path / '.optimization_backups' / 'change_log.json'
        self.log_file.parent.mkdir(exist_ok=True)
        
        # 加载现有日志
        if self.log_file.exists():
            with open(self.log_file, 'r', encoding='utf-8') as f:
                self.logs = json.load(f)
        else:
            self.logs = []
    
    def log_change(self, change_type: str, description: str, 
                   files_affected: List[str], success: bool = True):
        """记录变更"""
        entry = {
            'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'type': change_type,
            'description': description,
            'files_affected': files_affected,
            'success': success
        }
        
        self.logs.append(entry)
        
        # 保存日志
        with open(self.log_file, 'w', encoding='utf-8') as f:
            json.dump(self.logs, f, ensure_ascii=False, indent=2)
        
        print(f"[LOG] 变更已记录: {change_type}")
    
    def get_logs(self, limit: int = 10) -> List[Dict[str, Any]]:
        """获取变更日志"""
        return self.logs[-limit:]


class OptimizationExecutor:
    """优化执行器"""
    
    def __init__(self, project_path: str):
        self.project_path = Path(project_path)
        self.backup_manager = BackupManager(project_path)
        self.change_logger = ChangeLogger(project_path)
        self.current_backup = None
    
    def execute_optimization(self, optimization_func, description: str) -> bool:
        """执行优化"""
        print("\n" + "=" * 60)
        print(f"执行优化: {description}")
        print("=" * 60)
        
        # 1. 创建备份
        print("\n步骤1: 创建备份...")
        self.current_backup = self.backup_manager.create_backup()
        
        # 2. 执行优化
        print("\n步骤2: 执行优化...")
        try:
            files_affected = optimization_func()
            success = True
            print("[OK] 优化执行成功")
        except Exception as e:
            print(f"[ERROR] 优化执行失败: {e}")
            files_affected = []
            success = False
        
        # 3. 验证优化
        if success:
            print("\n步骤3: 验证优化...")
            validation_result = self._validate_optimization()
            
            if not validation_result:
                print("[ERROR] 验证失败,执行回滚...")
                self.rollback()
                success = False
            else:
                print("[OK] 验证通过")
        
        # 4. 记录变更
        print("\n步骤4: 记录变更...")
        self.change_logger.log_change(
            change_type='optimization',
            description=description,
            files_affected=files_affected,
            success=success
        )
        
        return success
    
    def _validate_optimization(self) -> bool:
        """验证优化结果"""
        import subprocess
        
        try:
            # 运行测试验证
            result = subprocess.run(
                ['python', '-m', 'pytest', 'tests/', '-v', '--tb=no', '-q'],
                cwd=str(self.project_path),
                capture_output=True,
                text=True,
                timeout=60
            )
            
            # 检查测试是否通过
            if 'passed' in result.stdout:
                # 提取通过率
                lines = result.stdout.split('\n')
                for line in lines:
                    if 'passed' in line:
                        print(f"   测试结果: {line.strip()}")
                        return True
            
            return False
            
        except Exception as e:
            print(f"   验证异常: {e}")
            return False
    
    def rollback(self) -> bool:
        """回滚到上一个备份"""
        if not self.current_backup:
            print("[ERROR] 没有可回滚的备份")
            return False
        
        print(f"\n回滚到备份: {self.current_backup}")
        return self.backup_manager.restore_backup(self.current_backup)
    
    def get_status(self) -> Dict[str, Any]:
        """获取优化状态"""
        backups = self.backup_manager.list_backups()
        recent_logs = self.change_logger.get_logs(5)
        
        return {
            'total_backups': len(backups),
            'recent_backups': backups[:3],
            'recent_changes': recent_logs
        }


if __name__ == '__main__':
    # 示例用法
    project_path = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    executor = OptimizationExecutor(project_path)
    
    # 查看状态
    status = executor.get_status()
    print("\n优化执行器状态:")
    print(f"备份总数: {status['total_backups']}")
    print(f"最近变更: {len(status['recent_changes'])} 条")
