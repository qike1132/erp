"""
备份清理服务 - 优化版本

提供智能备份清理功能：
1. 基于存储空间使用率
2. 基于备份重要性（手动备份优先保留）
3. 基于恢复测试结果（损坏备份优先删除）
4. 生成清理报告和通知
"""

import asyncio
import json
import logging
import shutil
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

import psutil
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from fastapi_app.core.database import get_async_db_context
from fastapi_app.services.backup_alert_service import alert_service
from fastapi_app.services.backup_health_check_service import health_check_service
from fastapi_app.services.backup_service import BACKUP_DIR, cleanup_old_backups as original_cleanup
from fastapi_app.shared_models.backup_record import BackupRecord

logger = logging.getLogger(__name__)


def _backup_created_time(f: Path) -> datetime:
    """获取备份文件的真实创建时间。

    优先读取伴随的 ``.meta`` 文件中的 ``created_at``（加密备份的 mtime 可能被刷新）；
    无 meta 时回退到文件系统 mtime。
    """
    meta_path = f.parent / (f.name + '.meta')
    if meta_path.exists():
        try:
            meta = json.loads(meta_path.read_text(encoding='utf-8'))
            created_at = meta.get('created_at')
            if created_at:
                return datetime.strptime(created_at, '%Y-%m-%d %H:%M:%S')
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            pass
    return datetime.fromtimestamp(f.stat().st_mtime)


class BackupCleanupService:
    """备份清理服务类"""
    
    def __init__(self):
        self.cleanup_config = self._load_cleanup_config()
        
    def _load_cleanup_config(self) -> Dict[str, Any]:
        """加载清理配置"""
        import os
        
        return {
            # 保留策略 - 时间（天）
            'retention_days': int(os.environ.get('BACKUP_RETENTION_DAYS', '30')),
            
            # 保留策略 - 数量
            'retention_count': int(os.environ.get('BACKUP_RETENTION_COUNT', '100')),
            
            # 存储空间阈值（百分比）
            'disk_space_threshold': float(os.environ.get('BACKUP_DISK_SPACE_THRESHOLD', '10.0')),
            
            # 智能清理设置
            'smart_cleanup_enabled': os.environ.get('BACKUP_SMART_CLEANUP', 'true').lower() == 'true',
            'keep_manual_backups': os.environ.get('BACKUP_KEEP_MANUAL', 'true').lower() == 'true',
            'keep_failed_backups': os.environ.get('BACKUP_KEEP_FAILED', 'false').lower() == 'true',
            'min_free_space_gb': float(os.environ.get('BACKUP_MIN_FREE_SPACE_GB', '10.0')),
            
            # 恢复测试设置
            'recovery_test_before_delete': os.environ.get('BACKUP_TEST_BEFORE_DELETE', 'false').lower() == 'true',
            'test_sample_rate': float(os.environ.get('BACKUP_TEST_SAMPLE_RATE', '10.0')),
            
            # 通知设置
            'notify_on_cleanup': os.environ.get('BACKUP_NOTIFY_CLEANUP', 'true').lower() == 'true',
            'cleanup_report_days': int(os.environ.get('BACKUP_CLEANUP_REPORT_DAYS', '7')),
        }
    
    async def smart_cleanup(self) -> Dict[str, Any]:
        """
        智能备份清理
        
        Returns:
            Dict[str, Any]: 清理结果
        """
        logger.info("开始智能备份清理...")
        
        try:
            # 检查磁盘空间
            disk_info = await self._check_disk_space()
            
            # 获取所有备份文件信息
            backup_files = await self._get_backup_files_info()
            
            if not backup_files:
                return {
                    'success': True,
                    'message': '没有找到备份文件',
                    'cleaned_files': [],
                    'kept_files': [],
                    'disk_info': disk_info
                }
            
            # 标记需要保留的文件
            files_to_keep = await self._mark_files_to_keep(backup_files, disk_info)
            
            # 标记需要删除的文件
            files_to_delete = await self._mark_files_to_delete(backup_files, files_to_keep, disk_info)
            
            # 执行删除
            cleanup_result = await self._execute_cleanup(files_to_delete)
            
            # 生成报告
            report = await self._generate_cleanup_report(
                backup_files, files_to_keep, files_to_delete, cleanup_result, disk_info
            )
            
            # 发送通知
            if self.cleanup_config['notify_on_cleanup'] and cleanup_result['deleted_count'] > 0:
                await self._send_cleanup_notification(report)
            
            logger.info(f"智能清理完成: 删除 {cleanup_result['deleted_count']} 个文件，保留 {len(files_to_keep)} 个文件")
            return report
            
        except Exception as e:  # defensive: cleanup task must report failure but not crash
            logger.error(f"智能备份清理失败: {e}")
            
            # 发送错误告警
            await alert_service.send_alert(
                task_name='smart_cleanup',
                error=f"智能备份清理失败: {str(e)}",
                task_type='cleanup',
                severity='error'
            )
            
            return {
                'success': False,
                'error': str(e),
                'message': '智能备份清理失败'
            }
    
    async def _check_disk_space(self) -> Dict[str, Any]:
        """检查磁盘空间"""
        try:
            ensure_backup_dir()
            backup_path = BACKUP_DIR.resolve()
            
            disk_usage = psutil.disk_usage(str(backup_path))
            
            free_gb = disk_usage.free / (1024 ** 3)
            total_gb = disk_usage.total / (1024 ** 3)
            used_percent = disk_usage.percent
            free_percent = 100 - used_percent
            
            threshold = self.cleanup_config['disk_space_threshold']
            min_free_gb = self.cleanup_config['min_free_space_gb']
            
            needs_cleanup = free_percent < threshold or free_gb < min_free_gb
            
            return {
                'path': str(backup_path),
                'total_gb': round(total_gb, 2),
                'used_gb': round(disk_usage.used / (1024 ** 3), 2),
                'free_gb': round(free_gb, 2),
                'used_percent': round(used_percent, 2),
                'free_percent': round(free_percent, 2),
                'threshold_percent': threshold,
                'min_free_gb': min_free_gb,
                'needs_cleanup': needs_cleanup,
                'cleanup_reason': '磁盘空间不足' if needs_cleanup else '磁盘空间充足'
            }
            
        except OSError as e:
            logger.error(f"检查磁盘空间失败: {e}")
            return {
                'error': str(e),
                'needs_cleanup': True,
                'cleanup_reason': f'磁盘空间检查失败: {str(e)}'
            }
    
    async def _get_backup_files_info(self) -> List[Dict[str, Any]]:
        """获取所有备份文件信息"""
        try:
            ensure_backup_dir()
            
            backup_files = []
            for file_path in BACKUP_DIR.iterdir():
                if not file_path.is_file():
                    continue
                
                # 只处理备份文件
                if not (file_path.name.startswith('erp_backup_') or 
                        file_path.name.startswith('erp_auto_') or 
                        file_path.name.startswith('erp_incremental_')) or \
                   not (file_path.name.endswith('.zip') or file_path.name.endswith('.json') or file_path.name.endswith('.zip.enc')):
                    continue
                
                file_info = {
                    'path': file_path,
                    'name': file_path.name,
                    'size_bytes': file_path.stat().st_size,
                    'size_mb': round(file_path.stat().st_size / (1024 ** 2), 2),
                    'mtime': _backup_created_time(file_path),
                    'is_incremental': 'incremental' in file_path.name,
                    'is_manual': file_path.name.startswith('erp_backup_'),
                    'is_auto': file_path.name.startswith('erp_auto_'),
                    'base_timestamp': None,
                    'importance_score': 0,
                    'health_status': 'unknown',
                    'recovery_test_passed': None
                }
                
                # 尝试读取manifest获取更多信息（加密备份 .enc 无法直接读取，跳过）
                if file_path.name.endswith('.zip') and not file_path.name.endswith('.zip.enc'):
                    try:
                        import zipfile
                        with zipfile.ZipFile(file_path, 'r') as zf:
                            if 'manifest.json' in zf.namelist():
                                manifest = json.loads(zf.read('manifest.json'))
                                file_info['base_timestamp'] = manifest.get('base_timestamp')
                                file_info['table_count'] = manifest.get('table_count')
                                file_info['total_rows'] = manifest.get('total_rows')
                                file_info['backup_type'] = manifest.get('backup_type', 'unknown')
                    except (zipfile.BadZipFile, OSError, json.JSONDecodeError):
                        file_info['health_status'] = 'corrupted'
                
                backup_files.append(file_info)
            
            # 按修改时间排序（最新的在前）
            backup_files.sort(key=lambda x: x['mtime'], reverse=True)
            
            return backup_files
            
        except OSError as e:
            logger.error(f"获取备份文件信息失败: {e}")
            return []
    
    async def _mark_files_to_keep(self, 
                                 backup_files: List[Dict[str, Any]], 
                                 disk_info: Dict[str, Any]) -> Set[str]:
        """标记需要保留的文件"""
        files_to_keep = set()
        
        try:
            # 1. 保留最新的N个文件（基于数量策略）
            retention_count = self.cleanup_config['retention_count']
            for file_info in backup_files[:retention_count]:
                files_to_keep.add(file_info['name'])
            
            # 2. 保留在保留时间内的文件
            retention_days = self.cleanup_config['retention_days']
            cutoff_date = datetime.now() - timedelta(days=retention_days)
            
            for file_info in backup_files:
                if file_info['mtime'] >= cutoff_date:
                    files_to_keep.add(file_info['name'])
            
            # 3. 保留手动备份（如果配置）
            if self.cleanup_config['keep_manual_backups']:
                for file_info in backup_files:
                    if file_info['is_manual']:
                        files_to_keep.add(file_info['name'])
            
            # 4. 保留重要的增量备份链
            await self._mark_incremental_chains(backup_files, files_to_keep)
            
            # 5. 计算文件重要性分数并保留高分文件
            await self._calculate_importance_scores(backup_files, files_to_keep, disk_info)
            
            # 6. 执行恢复测试（如果启用）并标记损坏文件为可删除
            if self.cleanup_config['recovery_test_before_delete']:
                await self._test_backup_files(backup_files, files_to_keep)
            
            return files_to_keep
            
        except Exception as e:  # defensive: keep all files when marking fails
            logger.error(f"标记保留文件失败: {e}")
            # 如果出错，保留所有文件
            return {file_info['name'] for file_info in backup_files}
    
    async def _mark_incremental_chains(self, 
                                     backup_files: List[Dict[str, Any]], 
                                     files_to_keep: Set[str]) -> None:
        """标记增量备份链"""
        try:
            # 找出所有全量备份
            full_backups = []
            for file_info in backup_files:
                if not file_info['is_incremental']:
                    full_backups.append(file_info)
            
            # 对于每个保留的全量备份，保留其增量备份链
            for full_backup in full_backups:
                if full_backup['name'] in files_to_keep:
                    full_timestamp = self._extract_timestamp(full_backup['name'])
                    if full_timestamp:
                        # 找到基于此全量备份的增量备份
                        for file_info in backup_files:
                            if (file_info['is_incremental'] and 
                                file_info['base_timestamp'] and 
                                file_info['base_timestamp'] <= full_timestamp):
                                files_to_keep.add(file_info['name'])
                                
        except Exception as e:  # defensive: incremental chain marking must not abort cleanup
            logger.error(f"标记增量备份链失败: {e}")
    
    def _extract_timestamp(self, filename: str) -> Optional[str]:
        """从文件名提取时间戳"""
        try:
            # 移除前缀和后缀
            ts_str = filename
            for prefix in ['erp_backup_', 'erp_auto_daily_', 'erp_incremental_']:
                ts_str = ts_str.replace(prefix, '')
            
            for suffix in ['.zip', '.json', '.enc']:
                ts_str = ts_str.replace(suffix, '')
            
            # 检查是否为有效时间戳格式 (YYYYMMDD_HHMMSS)
            if len(ts_str) == 15 and ts_str[8] == '_':
                return ts_str
            return None
        except (ValueError, IndexError, AttributeError):
            return None
    
    async def _calculate_importance_scores(self, 
                                         backup_files: List[Dict[str, Any]], 
                                         files_to_keep: Set[str],
                                         disk_info: Dict[str, Any]) -> None:
        """计算文件重要性分数"""
        try:
            # 根据磁盘空间需求调整保留策略
            free_percent = disk_info.get('free_percent', 100)
            free_gb = disk_info.get('free_gb', 0)
            
            # 如果磁盘空间充足，保留更多文件
            if free_percent >= 20 and free_gb >= 50:
                return  # 空间充足，保留所有标记的文件
            
            # 空间不足，需要更严格的筛选
            for file_info in backup_files:
                if file_info['name'] in files_to_keep:
                    score = 0
                    
                    # 手动备份得分更高
                    if file_info['is_manual']:
                        score += 10
                    
                    # 全量备份得分更高
                    if not file_info['is_incremental']:
                        score += 5
                    
                    # 较新的文件得分更高
                    file_age_days = (datetime.now() - file_info['mtime']).days
                    if file_age_days <= 7:
                        score += 8
                    elif file_age_days <= 30:
                        score += 5
                    elif file_age_days <= 90:
                        score += 2
                    
                    # 较大的文件得分较低（占用更多空间）
                    size_gb = file_info['size_bytes'] / (1024 ** 3)
                    if size_gb > 1:
                        score -= int(size_gb)  # 每GB减1分
                    
                    # 健康状态好的文件得分更高
                    if file_info['health_status'] == 'corrupted':
                        score -= 10
                    
                    file_info['importance_score'] = score
            
            # 按分数排序，保留高分文件
            sorted_files = sorted(backup_files, key=lambda x: x.get('importance_score', 0), reverse=True)
            
            # 根据可用空间决定保留数量
            available_space_gb = free_gb
            target_free_gb = self.cleanup_config['min_free_space_gb']
            space_to_free_gb = max(0, target_free_gb - available_space_gb)
            
            if space_to_free_gb > 0:
                # 需要释放空间，从低分文件开始删除
                total_size_freed = 0
                files_to_remove = set()
                
                for file_info in reversed(sorted_files):
                    if file_info['name'] in files_to_keep:
                        file_size_gb = file_info['size_bytes'] / (1024 ** 3)
                        total_size_freed += file_size_gb
                        files_to_remove.add(file_info['name'])
                        
                        if total_size_freed >= space_to_free_gb:
                            break
                
                # 从保留列表中移除
                files_to_keep.difference_update(files_to_remove)
                
        except Exception as e:  # defensive: scoring failure should not abort cleanup
            logger.error(f"计算重要性分数失败: {e}")
    
    async def _test_backup_files(self, 
                               backup_files: List[Dict[str, Any]], 
                               files_to_keep: Set[str]) -> None:
        """测试备份文件"""
        try:
            if not self.cleanup_config['recovery_test_before_delete']:
                return
            
            sample_rate = self.cleanup_config['test_sample_rate'] / 100.0
            
            for file_info in backup_files:
                # 只测试不在保留列表中的文件
                if file_info['name'] in files_to_keep:
                    continue
                
                # 抽样测试
                import random
                if random.random() > sample_rate:
                    continue
                
                # 执行恢复测试
                test_result = await health_check_service.perform_recovery_test(file_info['name'])
                
                if test_result.get('success', False):
                    file_info['recovery_test_passed'] = True
                    file_info['health_status'] = 'healthy'
                    # 测试通过的文件可以考虑保留
                    if test_result.get('table_count', 0) > 0:
                        files_to_keep.add(file_info['name'])
                else:
                    file_info['recovery_test_passed'] = False
                    file_info['health_status'] = 'corrupted'
                    # 测试失败的文件优先删除
                    if file_info['name'] in files_to_keep:
                        files_to_keep.remove(file_info['name'])
                    
        except Exception as e:  # defensive: recovery test failure should not abort cleanup
            logger.error(f"备份文件测试失败: {e}")
    
    async def _mark_files_to_delete(self, 
                                  backup_files: List[Dict[str, Any]], 
                                  files_to_keep: Set[str],
                                  disk_info: Dict[str, Any]) -> Set[str]:
        """标记需要删除的文件"""
        files_to_delete = set()
        
        try:
            # 标记所有不在保留列表中的文件为删除
            for file_info in backup_files:
                if file_info['name'] not in files_to_keep:
                    files_to_delete.add(file_info['name'])
            
            # 如果磁盘空间仍然不足，删除更多文件
            if disk_info.get('needs_cleanup', False):
                # 按重要性分数排序（从低到高）
                sorted_files = sorted(
                    [f for f in backup_files if f['name'] in files_to_keep],
                    key=lambda x: x.get('importance_score', 0)
                )
                
                available_space_gb = disk_info.get('free_gb', 0)
                target_free_gb = self.cleanup_config['min_free_space_gb']
                space_needed_gb = max(0, target_free_gb - available_space_gb)
                
                space_freed_gb = 0
                for file_info in sorted_files:
                    if space_freed_gb >= space_needed_gb:
                        break
                    
                    file_size_gb = file_info['size_bytes'] / (1024 ** 3)
                    files_to_delete.add(file_info['name'])
                    files_to_keep.remove(file_info['name'])
                    space_freed_gb += file_size_gb
            
            return files_to_delete
            
        except Exception as e:  # defensive: deletion marking failure should not abort cleanup
            logger.error(f"标记删除文件失败: {e}")
            return set()
    
    async def _execute_cleanup(self, files_to_delete: Set[str]) -> Dict[str, Any]:
        """执行清理操作"""
        deleted_files = []
        errors = []
        
        try:
            for filename in files_to_delete:
                filepath = BACKUP_DIR / filename
                if filepath.exists():
                    try:
                        filepath.unlink()
                        deleted_files.append(filename)
                        logger.info(f"删除备份文件: {filename}")
                        
                        # 同时删除对应的记录文件（如果有）
                        record_file = BACKUP_DIR / f"{filename}.record"
                        if record_file.exists():
                            record_file.unlink()
                            
                    except OSError as e:
                        errors.append(f"{filename}: {str(e)}")
                        logger.error(f"删除文件失败 {filename}: {e}")
        
            # 删除数据库记录
            deleted_records, db_delete_failed = await self._delete_backup_records(deleted_files)
            if db_delete_failed:
                # 磁盘文件已删但 DB 记录残留：记录孤立记录以便后续清理
                orphan_count = len(deleted_files) - deleted_records
                if orphan_count > 0:
                    errors.append(f"{orphan_count} 条备份记录数据库删除失败，存在孤立记录")
                    logger.warning(
                        "备份记录数据库删除失败，%d 条孤立记录（文件已删除）: %s",
                        orphan_count, deleted_files
                    )

            return {
                'deleted_count': len(deleted_files),
                'deleted_files': deleted_files,
                'deleted_records': deleted_records,
                'error_count': len(errors),
                'errors': errors,
                'success': len(errors) == 0
            }
            
        except Exception as e:  # defensive: cleanup execution must report failure gracefully
            logger.error(f"执行清理操作失败: {e}")
            return {
                'deleted_count': 0,
                'deleted_files': [],
                'deleted_records': 0,
                'error_count': 1,
                'errors': [str(e)],
                'success': False
            }
    
    async def _delete_backup_records(self, deleted_files: List[str]) -> tuple[int, bool]:
        """删除对应的备份记录

        Returns:
            (deleted_count, db_delete_failed)
            - deleted_count: 实际删除的记录数
            - db_delete_failed: 数据库删除是否失败（True 表示存在孤立记录）
        """
        try:
            if not deleted_files:
                return 0, False

            async with get_async_db_context() as db:
                # 批量删除：单条 DELETE ... WHERE filename IN (...)，避免 N+1
                from sqlalchemy import delete as sa_delete
                result = await db.execute(
                    sa_delete(BackupRecord).where(BackupRecord.filename.in_(deleted_files))
                )
                deleted_count = result.rowcount or 0

                if deleted_count > 0:
                    await db.commit()  # independent-transaction

                return deleted_count, False

        except SQLAlchemyError as e:
            logger.error(f"删除备份记录失败: {e}")
            return 0, True
    
    async def _generate_cleanup_report(self,
                                     backup_files: List[Dict[str, Any]],
                                     files_to_keep: Set[str],
                                     files_to_delete: Set[str],
                                     cleanup_result: Dict[str, Any],
                                     disk_info: Dict[str, Any]) -> Dict[str, Any]:
        """生成清理报告"""
        try:
            total_size_mb = sum(f['size_mb'] for f in backup_files)
            kept_size_mb = sum(f['size_mb'] for f in backup_files if f['name'] in files_to_keep)
            deleted_size_mb = sum(f['size_mb'] for f in backup_files if f['name'] in files_to_delete)
            
            # 统计文件类型
            file_types = {
                'manual': len([f for f in backup_files if f['is_manual']]),
                'auto': len([f for f in backup_files if f['is_auto']]),
                'incremental': len([f for f in backup_files if f['is_incremental']]),
                'full': len([f for f in backup_files if not f['is_incremental']]),
            }
            
            # 统计健康状态
            health_status = {}
            for file_info in backup_files:
                status = file_info.get('health_status', 'unknown')
                health_status[status] = health_status.get(status, 0) + 1
            
            report = {
                'timestamp': datetime.now().isoformat(),
                'success': cleanup_result['success'],
                'disk_info': disk_info,
                'summary': {
                    'total_files': len(backup_files),
                    'kept_files': len(files_to_keep),
                    'deleted_files': len(files_to_delete),
                    'total_size_mb': round(total_size_mb, 2),
                    'kept_size_mb': round(kept_size_mb, 2),
                    'deleted_size_mb': round(deleted_size_mb, 2),
                    'space_freed_percent': round((deleted_size_mb / total_size_mb * 100) if total_size_mb > 0 else 0, 2),
                },
                'file_types': file_types,
                'health_status': health_status,
                'cleanup_result': cleanup_result,
                'recommendations': self._generate_cleanup_recommendations(
                    backup_files, files_to_keep, files_to_delete, disk_info
                )
            }
            
            # 保存报告
            await self._save_cleanup_report(report)
            
            return report
            
        except Exception as e:  # defensive: report generation must not abort cleanup
            logger.error(f"生成清理报告失败: {e}")
            return {
                'timestamp': datetime.now().isoformat(),
                'success': False,
                'error': str(e),
                'message': '生成清理报告失败'
            }
    
    def _generate_cleanup_recommendations(self,
                                        backup_files: List[Dict[str, Any]],
                                        files_to_keep: Set[str],
                                        files_to_delete: Set[str],
                                        disk_info: Dict[str, Any]) -> List[str]:
        """生成清理建议"""
        recommendations = []
        
        # 磁盘空间建议
        free_percent = disk_info.get('free_percent', 100)
        free_gb = disk_info.get('free_gb', 0)
        min_free_gb = self.cleanup_config['min_free_space_gb']
        
        if free_percent < 10:
            recommendations.append(f"磁盘空间严重不足 ({free_percent:.1f}% 可用)，建议增加存储空间")
        elif free_gb < min_free_gb:
            recommendations.append(f"磁盘空间不足 ({free_gb:.1f}GB 可用)，建议清理更多备份或增加存储空间")
        
        # 备份文件数量建议
        total_files = len(backup_files)
        retention_count = self.cleanup_config['retention_count']
        
        if total_files > retention_count * 2:
            recommendations.append(f"备份文件数量过多 ({total_files} 个)，超过保留数量 ({retention_count}) 的两倍，建议调整保留策略")
        
        # 文件健康状态建议
        corrupted_files = [f for f in backup_files if f.get('health_status') == 'corrupted']
        if corrupted_files:
            recommendations.append(f"发现 {len(corrupted_files)} 个损坏的备份文件，建议检查备份过程")
        
        # 增量备份链建议
        incremental_files = [f for f in backup_files if f['is_incremental']]
        full_files = [f for f in backup_files if not f['is_incremental']]
        
        if incremental_files and not full_files:
            recommendations.append("只有增量备份没有全量备份，建议创建全量备份")
        elif len(incremental_files) > len(full_files) * 10:
            recommendations.append(f"增量备份数量 ({len(incremental_files)}) 远多于全量备份 ({len(full_files)})，建议调整备份策略")
        
        # 如果没有建议，添加正面反馈
        if not recommendations:
            recommendations.append("备份清理策略运行良好，无需额外操作")
        
        return recommendations
    
    async def _save_cleanup_report(self, report: Dict[str, Any]) -> None:
        """保存清理报告"""
        try:
            ensure_backup_dir()
            reports_dir = BACKUP_DIR / 'cleanup_reports'
            reports_dir.mkdir(parents=True, exist_ok=True)
            
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            report_file = reports_dir / f'cleanup_report_{timestamp}.json'
            
            with open(report_file, 'w', encoding='utf-8') as f:
                json.dump(report, f, ensure_ascii=False, indent=2)
            
            logger.info(f"清理报告已保存: {report_file}")
            
            # 清理旧报告
            await self._cleanup_old_reports(reports_dir)
            
        except OSError as e:
            logger.error(f"保存清理报告失败: {e}")
    
    async def _cleanup_old_reports(self, reports_dir: Path) -> None:
        """清理旧的清理报告"""
        try:
            retention_days = self.cleanup_config['cleanup_report_days']
            cutoff_date = datetime.now() - timedelta(days=retention_days)
            
            report_files = list(reports_dir.glob('cleanup_report_*.json'))
            deleted_count = 0
            
            for report_file in report_files:
                try:
                    # 从文件名解析日期
                    filename = report_file.stem
                    date_str = filename.replace('cleanup_report_', '')
                    file_date = datetime.strptime(date_str[:15], '%Y%m%d_%H%M%S')
                    
                    if file_date < cutoff_date:
                        report_file.unlink()
                        deleted_count += 1
                        
                except (ValueError, IndexError):
                    # 如果无法解析日期，使用文件修改时间
                    file_mtime = datetime.fromtimestamp(report_file.stat().st_mtime)
                    if file_mtime < cutoff_date:
                        report_file.unlink()
                        deleted_count += 1
            
            if deleted_count > 0:
                logger.info(f"清理了 {deleted_count} 个旧的清理报告")
                
        except OSError as e:
            logger.error(f"清理报告文件失败: {e}")
    
    async def _send_cleanup_notification(self, report: Dict[str, Any]) -> None:
        """发送清理通知"""
        try:
            summary = report.get('summary', {})
            deleted_count = summary.get('deleted_files', 0)
            deleted_size_mb = summary.get('deleted_size_mb', 0)
            
            if deleted_count == 0:
                return
            
            message = (
                f"备份清理完成\n"
                f"删除文件: {deleted_count} 个\n"
                f"释放空间: {deleted_size_mb:.2f} MB\n"
                f"保留文件: {summary.get('kept_files', 0)} 个\n"
                f"磁盘可用空间: {report.get('disk_info', {}).get('free_percent', 0):.1f}%"
            )
            
            await alert_service.send_alert(
                task_name='backup_cleanup',
                error=message,
                task_type='cleanup',
                severity='info',
                additional_info=report
            )
            
        except Exception as e:  # defensive: cleanup notification failure must not propagate
            logger.error(f"发送清理通知失败: {e}")
    
    async def get_cleanup_history(self, days: int = 7) -> List[Dict[str, Any]]:
        """获取清理历史记录"""
        try:
            reports_dir = BACKUP_DIR / 'cleanup_reports'
            if not reports_dir.exists():
                return []
            
            cutoff_date = datetime.now() - timedelta(days=days)
            reports = []
            
            for report_file in reports_dir.glob('cleanup_report_*.json'):
                try:
                    # 从文件名解析日期
                    filename = report_file.stem
                    date_str = filename.replace('cleanup_report_', '')
                    file_date = datetime.strptime(date_str[:15], '%Y%m%d_%H%M%S')
                    
                    if file_date >= cutoff_date:
                        with open(report_file, 'r', encoding='utf-8') as f:
                            report_data = json.load(f)
                            report_data['report_file'] = report_file.name
                            report_data['report_date'] = file_date.isoformat()
                            reports.append(report_data)
                            
                except (ValueError, IndexError, json.JSONDecodeError):
                    # 跳过无法解析的文件
                    continue
            
            # 按时间倒序排序
            reports.sort(key=lambda x: x.get('timestamp', ''), reverse=True)
            return reports
            
        except OSError as e:
            logger.error(f"获取清理历史失败: {e}")
            return []


# 全局清理服务实例
cleanup_service = BackupCleanupService()


def ensure_backup_dir():
    """确保备份目录存在"""
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)