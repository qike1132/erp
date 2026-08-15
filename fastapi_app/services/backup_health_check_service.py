"""
备份健康检查监控服务

提供备份系统健康检查功能：
1. 备份目录可用空间检查
2. 最近备份时间检查
3. 备份文件完整性检查
4. 恢复测试功能
5. 健康报告生成和存储
"""

import json
import logging
import tempfile
import zipfile
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

import psutil
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from fastapi_app.core.database import get_async_db_context
from fastapi_app.services.backup_alert_service import alert_service
from fastapi_app.services.backup_service import BACKUP_DIR, ensure_backup_dir
from fastapi_app.shared_models.backup_record import BackupRecord

logger = logging.getLogger(__name__)


class BackupHealthCheckService:
    """备份健康检查服务类"""
    
    def __init__(self):
        self.health_config = self._load_health_config()
        
    def _load_health_config(self) -> Dict[str, Any]:
        """加载健康检查配置"""
        import os
        
        return {
            # 磁盘空间阈值（百分比）
            'disk_space_threshold': float(os.environ.get('BACKUP_DISK_SPACE_THRESHOLD', '10.0')),
            
            # 备份时间阈值（小时）
            'backup_age_threshold': int(os.environ.get('BACKUP_AGE_THRESHOLD', '24')),
            
            # 完整性检查采样率（百分比）
            'integrity_sample_rate': float(os.environ.get('BACKUP_INTEGRITY_SAMPLE_RATE', '10.0')),
            
            # 恢复测试频率（天）
            'recovery_test_frequency': int(os.environ.get('BACKUP_RECOVERY_TEST_FREQUENCY', '7')),
            
            # 健康检查间隔（分钟）
            'health_check_interval': int(os.environ.get('BACKUP_HEALTH_CHECK_INTERVAL', '60')),
            
            # 报告保留天数
            'report_retention_days': int(os.environ.get('BACKUP_REPORT_RETENTION_DAYS', '30')),
        }
    
    async def perform_health_check(self) -> Dict[str, Any]:
        """
        执行全面的健康检查
        
        Returns:
            Dict[str, Any]: 健康检查结果
        """
        logger.info("开始执行备份健康检查...")
        
        results = {
            'check_time': datetime.now().isoformat(),
            'overall_status': 'healthy',
            'checks': {},
            'issues': [],
            'recommendations': []
        }
        
        try:
            # 1. 检查磁盘空间
            disk_check = await self._check_disk_space()
            results['checks']['disk_space'] = disk_check
            if not disk_check['healthy']:
                results['overall_status'] = 'warning'
                results['issues'].append(disk_check['issue'])
            
            # 2. 检查最近备份时间
            backup_age_check = await self._check_backup_age()
            results['checks']['backup_age'] = backup_age_check
            if not backup_age_check['healthy']:
                results['overall_status'] = 'warning'
                results['issues'].append(backup_age_check['issue'])
            
            # 3. 检查备份文件完整性
            integrity_check = await self._check_backup_integrity()
            results['checks']['backup_integrity'] = integrity_check
            if not integrity_check['healthy']:
                results['overall_status'] = 'error'
                results['issues'].extend(integrity_check['issues'])
            
            # 4. 检查备份记录
            records_check = await self._check_backup_records()
            results['checks']['backup_records'] = records_check
            if not records_check['healthy']:
                results['overall_status'] = 'error'
                results['issues'].extend(records_check['issues'])
            
            # 5. 检查系统资源
            system_check = await self._check_system_resources()
            results['checks']['system_resources'] = system_check
            if not system_check['healthy']:
                results['overall_status'] = 'warning'
                results['issues'].extend(system_check['issues'])
            
            # 生成建议
            results['recommendations'] = self._generate_recommendations(results)
            
            # 记录健康检查结果
            await self._store_health_report(results)
            
            # 如果有问题，发送告警
            if results['issues']:
                await self._alert_on_issues(results)
            
            logger.info(f"健康检查完成，状态: {results['overall_status']}")
            return results
            
        except Exception as e:  # defensive: health check must report failure but not crash
            logger.error(f"健康检查执行失败: {e}")
            error_result = {
                'check_time': datetime.now().isoformat(),
                'overall_status': 'error',
                'error': str(e),
                'checks': {}
            }
            
            # 发送错误告警
            await alert_service.send_alert(
                task_name='health_check',
                error=f"健康检查执行失败: {str(e)}",
                task_type='health_check',
                severity='error'
            )
            
            return error_result
    
    async def _check_disk_space(self) -> Dict[str, Any]:
        """检查磁盘空间"""
        try:
            ensure_backup_dir()
            backup_path = BACKUP_DIR.resolve()
            
            # 获取磁盘使用情况
            disk_usage = psutil.disk_usage(str(backup_path))
            
            free_gb = disk_usage.free / (1024 ** 3)
            total_gb = disk_usage.total / (1024 ** 3)
            used_percent = disk_usage.percent
            free_percent = 100 - used_percent
            
            threshold = self.health_config['disk_space_threshold']
            healthy = free_percent >= threshold
            
            result = {
                'healthy': healthy,
                'path': str(backup_path),
                'total_gb': round(total_gb, 2),
                'used_gb': round(disk_usage.used / (1024 ** 3), 2),
                'free_gb': round(free_gb, 2),
                'used_percent': round(used_percent, 2),
                'free_percent': round(free_percent, 2),
                'threshold_percent': threshold,
            }
            
            if not healthy:
                result['issue'] = f"磁盘空间不足: 可用空间 {free_percent:.1f}% 低于阈值 {threshold}%"
                logger.warning(result['issue'])
            
            return result
            
        except OSError as e:
            logger.error(f"磁盘空间检查失败: {e}")
            return {
                'healthy': False,
                'error': str(e),
                'issue': f"磁盘空间检查失败: {str(e)}"
            }
    
    async def _check_backup_age(self) -> Dict[str, Any]:
        """检查最近备份时间"""
        try:
            ensure_backup_dir()
            
            # 查找最新的备份文件
            backup_files = []
            for ext in ['.zip', '.tar.gz', '.tar']:
                backup_files.extend(BACKUP_DIR.glob(f'*{ext}'))
            
            if not backup_files:
                return {
                    'healthy': False,
                    'latest_backup': None,
                    'age_hours': None,
                    'threshold_hours': self.health_config['backup_age_threshold'],
                    'issue': '未找到备份文件'
                }
            
            # 按修改时间排序
            latest_file = max(backup_files, key=lambda f: f.stat().st_mtime)
            file_mtime = datetime.fromtimestamp(latest_file.stat().st_mtime)
            age_hours = (datetime.now() - file_mtime).total_seconds() / 3600
            
            threshold = self.health_config['backup_age_threshold']
            healthy = age_hours <= threshold
            
            result = {
                'healthy': healthy,
                'latest_backup': latest_file.name,
                'latest_backup_time': file_mtime.isoformat(),
                'age_hours': round(age_hours, 2),
                'threshold_hours': threshold,
                'file_size_mb': round(latest_file.stat().st_size / (1024 ** 2), 2)
            }
            
            if not healthy:
                result['issue'] = f"备份文件过旧: 最新备份 {age_hours:.1f} 小时前，超过阈值 {threshold} 小时"
                logger.warning(result['issue'])
            
            return result
            
        except OSError as e:
            logger.error(f"备份时间检查失败: {e}")
            return {
                'healthy': False,
                'error': str(e),
                'issue': f"备份时间检查失败: {str(e)}"
            }
    
    async def _check_backup_integrity(self) -> Dict[str, Any]:
        """检查备份文件完整性"""
        try:
            ensure_backup_dir()
            
            # 查找所有备份文件
            backup_files = []
            for ext in ['.zip']:  # 目前只检查zip格式
                backup_files.extend(BACKUP_DIR.glob(f'*{ext}'))
            
            if not backup_files:
                return {
                    'healthy': False,
                    'checked_files': 0,
                    'passed_files': 0,
                    'failed_files': 0,
                    'issues': ['未找到备份文件'],
                    'details': []
                }
            
            # 采样检查
            sample_rate = self.health_config['integrity_sample_rate'] / 100.0
            files_to_check = []
            
            if len(backup_files) <= 5:
                # 文件少，全部检查
                files_to_check = backup_files
            else:
                # 按时间排序，检查最新的和随机的
                sorted_files = sorted(backup_files, key=lambda f: f.stat().st_mtime, reverse=True)
                # 总是检查最新的3个
                files_to_check = sorted_files[:3]
                # 随机采样
                import random
                remaining_files = sorted_files[3:]
                sample_count = max(1, int(len(remaining_files) * sample_rate))
                files_to_check.extend(random.sample(remaining_files, min(sample_count, len(remaining_files))))
            
            results = {
                'healthy': True,
                'checked_files': len(files_to_check),
                'passed_files': 0,
                'failed_files': 0,
                'issues': [],
                'details': []
            }
            
            for file_path in files_to_check:
                file_result = await self._check_single_backup_integrity(file_path)
                results['details'].append(file_result)
                
                if file_result['healthy']:
                    results['passed_files'] += 1
                else:
                    results['failed_files'] += 1
                    results['healthy'] = False
                    results['issues'].append(f"{file_path.name}: {file_result.get('issue', '完整性检查失败')}")
            
            return results
            
        except OSError as e:
            logger.error(f"备份完整性检查失败: {e}")
            return {
                'healthy': False,
                'error': str(e),
                'issues': [f"备份完整性检查失败: {str(e)}"],
                'details': []
            }
    
    async def _check_single_backup_integrity(self, file_path: Path) -> Dict[str, Any]:
        """检查单个备份文件的完整性"""
        try:
            # 检查文件是否存在且可读
            if not file_path.exists():
                return {
                    'filename': file_path.name,
                    'healthy': False,
                    'issue': '文件不存在'
                }
            
            if not file_path.is_file():
                return {
                    'filename': file_path.name,
                    'healthy': False,
                    'issue': '不是文件'
                }
            
            # 检查文件大小
            file_size = file_path.stat().st_size
            if file_size == 0:
                return {
                    'filename': file_path.name,
                    'healthy': False,
                    'issue': '文件大小为0'
                }
            
            # 检查zip文件完整性
            if file_path.suffix.lower() == '.zip':
                try:
                    with zipfile.ZipFile(file_path, 'r') as zip_file:
                        # 测试zip文件是否可以打开
                        test_result = zip_file.testzip()
                        if test_result is not None:
                            return {
                                'filename': file_path.name,
                                'healthy': False,
                                'issue': f'ZIP文件损坏: {test_result}'
                            }
                        
                        # 检查必要的文件（metadata.json 是可选的）
                        required_files = ['manifest.json']
                        missing_files = []
                        for req_file in required_files:
                            if req_file not in zip_file.namelist():
                                missing_files.append(req_file)
                        
                        if missing_files:
                            return {
                                'filename': file_path.name,
                                'healthy': False,
                                'issue': f'缺少必要文件: {", ".join(missing_files)}'
                            }
                        
                        # 检查manifest.json
                        try:
                            manifest_data = json.loads(zip_file.read('manifest.json').decode('utf-8'))
                            if 'version' not in manifest_data:
                                return {
                                    'filename': file_path.name,
                                    'healthy': False,
                                    'issue': 'manifest.json缺少version字段'
                                }
                        except (json.JSONDecodeError, KeyError) as e:
                            return {
                                'filename': file_path.name,
                                'healthy': False,
                                'issue': f'manifest.json解析失败: {str(e)}'
                            }
                
                except (zipfile.BadZipFile, OSError) as e:
                    return {
                        'filename': file_path.name,
                        'healthy': False,
                        'issue': f'ZIP文件损坏: {str(e)}'
                    }
            
            return {
                'filename': file_path.name,
                'healthy': True,
                'file_size_mb': round(file_size / (1024 ** 2), 2),
                'last_modified': datetime.fromtimestamp(file_path.stat().st_mtime).isoformat()
            }
            
        except OSError as e:
            return {
                'filename': file_path.name,
                'healthy': False,
                'issue': f'完整性检查异常: {str(e)}'
            }
    
    async def _check_backup_records(self) -> Dict[str, Any]:
        """检查备份记录"""
        try:
            async with get_async_db_context() as db:
                # 查询最近24小时的备份记录
                cutoff_time = datetime.now() - timedelta(hours=24)
                
                # 成功备份统计
                success_stmt = (
                    select(BackupRecord)
                    .where(BackupRecord.status == 'success')
                    .where(BackupRecord.created_at >= cutoff_time)
                )
                success_result = await db.execute(success_stmt)
                success_records = success_result.scalars().all()
                
                # 失败备份统计
                failed_stmt = (
                    select(BackupRecord)
                    .where(BackupRecord.status == 'failed')
                    .where(BackupRecord.created_at >= cutoff_time)
                )
                failed_result = await db.execute(failed_stmt)
                failed_records = failed_result.scalars().all()
                
                # 按类型统计
                type_stats = {}
                for record in success_records + failed_records:
                    backup_type = record.type or 'unknown'
                    if backup_type not in type_stats:
                        type_stats[backup_type] = {'success': 0, 'failed': 0}
                    
                    if record.status == 'success':
                        type_stats[backup_type]['success'] += 1
                    else:
                        type_stats[backup_type]['failed'] += 1
                
                total_success = len(success_records)
                total_failed = len(failed_records)
                total_records = total_success + total_failed
                
                success_rate = (total_success / total_records * 100) if total_records > 0 else 0
                
                healthy = total_failed == 0 and total_success > 0
                
                result = {
                    'healthy': healthy,
                    'total_records': total_records,
                    'success_count': total_success,
                    'failed_count': total_failed,
                    'success_rate': round(success_rate, 2),
                    'type_stats': type_stats,
                    'issues': []
                }
                
                if total_failed > 0:
                    result['issues'].append(f"最近24小时有 {total_failed} 次备份失败")
                
                if total_success == 0:
                    result['issues'].append("最近24小时没有成功备份")
                
                return result
                
        except SQLAlchemyError as e:
            logger.error(f"备份记录检查失败: {e}")
            return {
                'healthy': False,
                'error': str(e),
                'issues': [f"备份记录检查失败: {str(e)}"]
            }
    
    async def _check_system_resources(self) -> Dict[str, Any]:
        """检查系统资源"""
        try:
            issues = []
            
            # 检查CPU使用率
            cpu_percent = psutil.cpu_percent(interval=1)
            cpu_healthy = cpu_percent < 90
            
            # 检查内存使用率
            memory = psutil.virtual_memory()
            memory_percent = memory.percent
            memory_healthy = memory_percent < 90
            
            # 检查磁盘IO
            disk_io = psutil.disk_io_counters()
            disk_busy = disk_io.busy_time if hasattr(disk_io, 'busy_time') else 0
            
            result = {
                'healthy': cpu_healthy and memory_healthy,
                'cpu_percent': round(cpu_percent, 2),
                'memory_percent': round(memory_percent, 2),
                'memory_available_gb': round(memory.available / (1024 ** 3), 2),
                'disk_busy_time': disk_busy,
                'issues': issues
            }
            
            if not cpu_healthy:
                result['issues'].append(f"CPU使用率过高: {cpu_percent:.1f}%")
            
            if not memory_healthy:
                result['issues'].append(f"内存使用率过高: {memory_percent:.1f}%")
            
            return result
            
        except OSError as e:
            logger.error(f"系统资源检查失败: {e}")
            return {
                'healthy': False,
                'error': str(e),
                'issues': [f"系统资源检查失败: {str(e)}"]
            }
    
    def _generate_recommendations(self, results: Dict[str, Any]) -> List[str]:
        """根据检查结果生成建议"""
        recommendations = []
        
        # 磁盘空间建议
        disk_check = results['checks'].get('disk_space', {})
        if not disk_check.get('healthy', True):
            free_percent = disk_check.get('free_percent', 0)
            threshold = disk_check.get('threshold_percent', 10)
            recommendations.append(f"磁盘空间不足 ({free_percent:.1f}% 可用)，建议清理旧备份或增加存储空间（阈值: {threshold}%）")
        
        # 备份时间建议
        age_check = results['checks'].get('backup_age', {})
        if not age_check.get('healthy', True):
            age_hours = age_check.get('age_hours', 0)
            threshold = age_check.get('threshold_hours', 24)
            recommendations.append(f"备份文件过旧 ({age_hours:.1f} 小时)，建议检查备份任务是否正常运行（阈值: {threshold} 小时）")
        
        # 完整性检查建议
        integrity_check = results['checks'].get('backup_integrity', {})
        if not integrity_check.get('healthy', True):
            failed_count = integrity_check.get('failed_files', 0)
            recommendations.append(f"发现 {failed_count} 个备份文件完整性检查失败，建议修复或删除损坏的备份文件")
        
        # 备份记录建议
        records_check = results['checks'].get('backup_records', {})
        if not records_check.get('healthy', True):
            failed_count = records_check.get('failed_count', 0)
            success_rate = records_check.get('success_rate', 0)
            recommendations.append(f"备份成功率较低 ({success_rate:.1f}%)，最近24小时有 {failed_count} 次失败，建议检查备份配置和日志")
        
        # 系统资源建议
        system_check = results['checks'].get('system_resources', {})
        if not system_check.get('healthy', True):
            cpu_percent = system_check.get('cpu_percent', 0)
            memory_percent = system_check.get('memory_percent', 0)
            recommendations.append(f"系统资源紧张 (CPU: {cpu_percent:.1f}%, 内存: {memory_percent:.1f}%)，建议优化备份时间或增加系统资源")
        
        # 如果没有问题，添加正面反馈
        if not recommendations and results['overall_status'] == 'healthy':
            recommendations.append("所有健康检查项正常，备份系统运行良好")
        
        return recommendations
    
    async def _store_health_report(self, results: Dict[str, Any]) -> None:
        """存储健康检查报告"""
        try:
            # 创建报告目录
            report_dir = BACKUP_DIR / 'health_reports'
            report_dir.mkdir(parents=True, exist_ok=True)
            
            # 生成报告文件名
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            report_file = report_dir / f'health_report_{timestamp}.json'
            
            # 保存报告
            with open(report_file, 'w', encoding='utf-8') as f:
                json.dump(results, f, ensure_ascii=False, indent=2)
            
            logger.info(f"健康检查报告已保存: {report_file}")
            
            # 清理旧报告
            await self._cleanup_old_reports(report_dir)
            
        except OSError as e:
            logger.error(f"存储健康检查报告失败: {e}")
    
    async def _cleanup_old_reports(self, report_dir: Path) -> None:
        """清理旧的健康检查报告"""
        try:
            retention_days = self.health_config['report_retention_days']
            cutoff_date = datetime.now() - timedelta(days=retention_days)
            
            report_files = list(report_dir.glob('health_report_*.json'))
            deleted_count = 0
            
            for report_file in report_files:
                try:
                    # 从文件名解析日期
                    filename = report_file.stem
                    date_str = filename.replace('health_report_', '')
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
                logger.info(f"清理了 {deleted_count} 个旧的健康检查报告")
                
        except OSError as e:
            logger.error(f"清理健康检查报告失败: {e}")
    
    async def _alert_on_issues(self, results: Dict[str, Any]) -> None:
        """根据问题发送告警"""
        try:
            issues = results.get('issues', [])
            if not issues:
                return
            
            # 根据问题严重程度确定告警级别
            severity = 'warning'
            if results['overall_status'] == 'error':
                severity = 'error'
            
            # 发送告警
            await alert_service.send_alert(
                task_name='health_check',
                error=f"健康检查发现 {len(issues)} 个问题: {'; '.join(issues[:3])}",
                task_type='health_check',
                severity=severity,
                additional_info={
                    'overall_status': results['overall_status'],
                    'issue_count': len(issues),
                    'issues': issues[:5],  # 只发送前5个问题
                    'check_time': results['check_time']
                }
            )
            
        except Exception as e:  # defensive: health check alert failure must not propagate
            logger.error(f"发送健康检查告警失败: {e}")
    
    async def perform_recovery_test(self, backup_file: Optional[str] = None) -> Dict[str, Any]:
        """
        执行恢复测试
        
        Args:
            backup_file: 指定要测试的备份文件，如果为None则使用最新备份
            
        Returns:
            Dict[str, Any]: 恢复测试结果
        """
        logger.info("开始执行恢复测试...")
        
        try:
            ensure_backup_dir()
            
            # 确定要测试的备份文件
            if backup_file:
                test_file = BACKUP_DIR / backup_file
                if not test_file.exists():
                    return {
                        'success': False,
                        'error': f"指定的备份文件不存在: {backup_file}"
                    }
            else:
                # 使用最新的备份文件
                backup_files = list(BACKUP_DIR.glob('*.zip'))
                if not backup_files:
                    return {
                        'success': False,
                        'error': "没有找到备份文件进行恢复测试"
                    }
                test_file = max(backup_files, key=lambda f: f.stat().st_mtime)
            
            # 创建临时目录进行恢复测试
            with tempfile.TemporaryDirectory() as temp_dir:
                temp_path = Path(temp_dir)
                
                # 解压备份文件
                try:
                    with zipfile.ZipFile(test_file, 'r') as zip_ref:
                        zip_ref.extractall(temp_path)
                    
                    # 检查必要的文件（metadata.json 是可选的）
                    required_files = ['manifest.json']
                    for req_file in required_files:
                        if not (temp_path / req_file).exists():
                            return {
                                'success': False,
                                'error': f"备份文件缺少必要文件: {req_file}",
                                'tested_file': test_file.name
                            }
                    
                    # 验证manifest.json
                    manifest_path = temp_path / 'manifest.json'
                    with open(manifest_path, 'r', encoding='utf-8') as f:
                        manifest = json.load(f)
                    
                    # metadata.json 是可选的
                    metadata = {}
                    metadata_path = temp_path / 'metadata.json'
                    if metadata_path.exists():
                        with open(metadata_path, 'r', encoding='utf-8') as f:
                            metadata = json.load(f)
                    
                    # 检查数据文件
                    data_files = list(temp_path.glob('*.json'))
                    data_files = [f for f in data_files if f.name not in ['manifest.json', 'metadata.json']]
                    
                    result = {
                        'success': True,
                        'tested_file': test_file.name,
                        'file_size_mb': round(test_file.stat().st_size / (1024 ** 2), 2),
                        'manifest_version': manifest.get('version'),
                        'backup_time': metadata.get('backup_time'),
                        'table_count': manifest.get('table_count'),
                        'total_rows': manifest.get('total_rows'),
                        'data_files_count': len(data_files),
                        'extracted_size_mb': round(self._get_directory_size(temp_path) / (1024 ** 2), 2),
                        'test_time': datetime.now().isoformat()
                    }
                    
                    logger.info(f"恢复测试成功: {test_file.name}")
                    return result
                    
                except (zipfile.BadZipFile, OSError, json.JSONDecodeError) as e:
                    return {
                        'success': False,
                        'error': f"备份文件损坏或格式错误: {str(e)}",
                        'tested_file': test_file.name
                    }
                    
        except Exception as e:  # defensive: recovery test failure must be reported gracefully
            logger.error(f"恢复测试失败: {e}")
            return {
                'success': False,
                'error': f"恢复测试执行失败: {str(e)}"
            }
    
    def _get_directory_size(self, directory: Path) -> int:
        """计算目录大小"""
        total_size = 0
        for file_path in directory.rglob('*'):
            if file_path.is_file():
                total_size += file_path.stat().st_size
        return total_size
    
    async def get_health_history(self, days: int = 7) -> List[Dict[str, Any]]:
        """获取健康检查历史记录"""
        try:
            report_dir = BACKUP_DIR / 'health_reports'
            if not report_dir.exists():
                return []
            
            cutoff_date = datetime.now() - timedelta(days=days)
            reports = []
            
            for report_file in report_dir.glob('health_report_*.json'):
                try:
                    # 从文件名解析日期
                    filename = report_file.stem
                    date_str = filename.replace('health_report_', '')
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
            reports.sort(key=lambda x: x.get('check_time', ''), reverse=True)
            return reports
            
        except OSError as e:
            logger.error(f"获取健康检查历史失败: {e}")
            return []


# 全局健康检查服务实例
health_check_service = BackupHealthCheckService()