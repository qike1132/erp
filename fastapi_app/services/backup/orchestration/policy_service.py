"""
备份策略管理服务

提供备份策略配置和管理功能：
1. 全量备份频率配置
2. 保留策略（时间、数量）
4. 加密设置
5. 策略应用和执行
"""

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, TypedDict

from sqlalchemy import delete, select
from sqlalchemy.exc import SQLAlchemyError

from fastapi_app.core.database import get_async_db_context
from fastapi_app.services.backup._constants import (
    BACKUP_DIR,
    RETENTION_DAYS_DEFAULT,
    retention_count,
    retention_days,
)
from fastapi_app.services.backup.metrics.alert_service import alert_service
from fastapi_app.shared_models.backup_record import BackupRecord

logger = logging.getLogger(__name__)


class _CheckResult(TypedDict):
    """单项策略检查结果（_perform_policy_checks 内部结构）。"""

    passed: bool
    message: str


class BackupPolicyService:
    """备份策略管理服务类"""

    def __init__(self):
        self.policy_config = self._load_policy_config()
        self.policy_file = BACKUP_DIR / 'backup_policy.json'

    def _load_policy_config(self) -> dict[str, Any]:
        """加载备份策略配置"""
        import os

        return {
            # 全量备份频率（cron表达式）
            'full_backup_cron': os.environ.get('BACKUP_FULL_CRON', '0 2 * * *'),  # 每天凌晨2点

            # 保留策略 - 时间（天）：env 单一真源 _constants.retention_days()（P0-2）
            'retention_days': retention_days(),

            # 保留策略 - 数量：env 单一真源 _constants.retention_count()（P0-2）
            'retention_count': retention_count(),

            # 加密设置
            'encryption_enabled': os.environ.get('BACKUP_ENCRYPTION_ENABLED', 'false').lower() == 'true',
            'encryption_algorithm': os.environ.get('BACKUP_ENCRYPTION_ALGORITHM', 'AES256'),
            'encryption_key_path': os.environ.get('BACKUP_ENCRYPTION_KEY_PATH', ''),

            # 压缩设置
            'compression_level': int(os.environ.get('BACKUP_COMPRESSION_LEVEL', '6')),

            # 存储位置
            'storage_location': os.environ.get('BACKUP_STORAGE_LOCATION', str(BACKUP_DIR)),

            # 备份前检查
            'pre_backup_check': os.environ.get('BACKUP_PRE_CHECK', 'true').lower() == 'true',

            # 备份后验证
            'post_backup_validation': os.environ.get('BACKUP_POST_VALIDATION', 'true').lower() == 'true',

            # 并行备份
            'parallel_backup': os.environ.get('BACKUP_PARALLEL', 'false').lower() == 'true',
            'max_parallel_jobs': int(os.environ.get('BACKUP_MAX_PARALLEL_JOBS', '2')),

            # 通知设置
            'notify_on_success': os.environ.get('BACKUP_NOTIFY_SUCCESS', 'false').lower() == 'true',
            'notify_on_failure': os.environ.get('BACKUP_NOTIFY_FAILURE', 'true').lower() == 'true',
            'notify_on_warning': os.environ.get('BACKUP_NOTIFY_WARNING', 'true').lower() == 'true',
        }

    async def get_current_policy(self) -> dict[str, Any]:
        """获取当前备份策略"""
        try:
            if self.policy_file.exists():
                with open(self.policy_file, encoding='utf-8') as f:
                    return json.load(f)
            else:
                # 返回默认策略
                return self._get_default_policy()
        except (OSError, ValueError) as e:
            logger.error(f"获取备份策略失败: {e}")
            return self._get_default_policy()

    def _get_default_policy(self) -> dict[str, Any]:
        """获取默认备份策略"""
        return {
            'policy_name': 'default',
            'description': '默认备份策略',
            'version': '1.0',
            'created_at': datetime.now().isoformat(),
            'updated_at': datetime.now().isoformat(),
            'full_backup': {
                'enabled': True,
                'schedule': self.policy_config['full_backup_cron'],
                'description': '每日全量备份',
                'timeout_minutes': 30,
                'max_retries': 3,
                'retry_delay_minutes': 5
            },
            'retention': {
                'enabled': True,
                'strategy': 'hybrid',  # hybrid/time/count
                'retention_days': self.policy_config['retention_days'],
                'min_free_space_gb': 10
            },
            'encryption': {
                'enabled': self.policy_config['encryption_enabled'],
                'algorithm': self.policy_config['encryption_algorithm'],
                'key_rotation_days': 90
            },
            'compression': {
                'enabled': True,
                'level': self.policy_config['compression_level'],
                'algorithm': 'zip'
            },
            'validation': {
                'pre_backup_check': self.policy_config['pre_backup_check'],
                'post_backup_validation': self.policy_config['post_backup_validation'],
                'integrity_check_frequency': 'daily',
                'recovery_test_frequency': 'weekly'
            },
            'notification': {
                'enabled': True,
                'notify_on_success': self.policy_config['notify_on_success'],
                'notify_on_failure': self.policy_config['notify_on_failure'],
                'notify_on_warning': self.policy_config['notify_on_warning'],
                'email_recipients': [],
                'webhook_urls': []
            },
            'performance': {
                'parallel_backup': self.policy_config['parallel_backup'],
                'max_parallel_jobs': self.policy_config['max_parallel_jobs'],
                'max_backup_size_mb': 1024,
                'chunk_size_mb': 100
            },
            'storage': {
                'primary_location': self.policy_config['storage_location'],
                'secondary_location': '',
                'sync_to_secondary': False
            }
        }

    def _is_valid_cron(self, cron_expr: str) -> bool:
        """验证cron表达式"""
        # 简单的cron表达式验证
        parts = cron_expr.strip().split()
        if len(parts) != 5:
            return False

        # 各字段取值范围: 分钟 时 日 月 周
        field_ranges = [(0, 59), (0, 23), (1, 31), (1, 12), (0, 7)]

        # 检查每个部分
        for part, (min_val, max_val) in zip(parts, field_ranges, strict=False):
            if not self._is_valid_cron_part(part, min_val, max_val):
                return False

        return True

    def _is_valid_cron_part(self, part: str, min_val: int = 0, max_val: int = 59) -> bool:
        """验证cron表达式部分（支持 *、数字、范围、列表、步长及其组合）"""
        if part == '*':
            return True

        # 步长: */5 或 0-23/2
        if '/' in part:
            base, _, step_str = part.partition('/')
            if not step_str.isdigit() or int(step_str) == 0:
                return False
            if base == '*':
                return True
            return self._is_valid_cron_part(base, min_val, max_val)

        # 范围 0-59
        if '-' in part:
            try:
                start, end = part.split('-')
            except ValueError:
                return False
            if not (start.isdigit() and end.isdigit()):
                return False
            return min_val <= int(start) <= max_val and min_val <= int(end) <= max_val

        # 列表 1,2,3
        if ',' in part:
            return all(
                self._is_valid_cron_part(item, min_val, max_val)
                for item in part.split(',')
            )

        # 检查数字范围
        if part.isdigit():
            return min_val <= int(part) <= max_val

        return False

    async def apply_backup_policy(self) -> dict[str, Any]:
        """
        应用备份策略

        Returns:
            Dict[str, Any]: 应用结果
        """
        logger.info("开始应用备份策略...")

        try:
            # 获取当前策略
            policy = await self.get_current_policy()

            # 检查策略是否启用
            if not policy.get('full_backup', {}).get('enabled', True):
                return {
                    'success': True,
                    'message': '备份策略已禁用',
                    'policy_applied': False
                }

            # 执行策略检查
            checks = await self._perform_policy_checks(policy)

            # 应用清理策略
            cleanup_result = await self._apply_retention_policy(policy)

            # 应用存储策略
            storage_result = await self._apply_storage_policy(policy)

            result = {
                'success': True,
                'message': '备份策略应用成功',
                'policy_applied': True,
                'policy_name': policy.get('policy_name'),
                'checks': checks,
                'cleanup_result': cleanup_result,
                'storage_result': storage_result,
                'applied_at': datetime.now().isoformat()
            }

            logger.info(f"备份策略应用成功: {policy.get('policy_name')}")
            return result

        except Exception as e:  # defensive: policy application must report failure gracefully
            logger.error(f"应用备份策略失败: {e}")

            # 发送告警
            await alert_service.send_alert(
                task_name='apply_backup_policy',
                error=f"应用备份策略失败: {e!s}",
                task_type='policy',
                severity='error'
            )

            return {
                'success': False,
                'message': f'应用备份策略失败: {e!s}',
                'policy_applied': False,
                'error': str(e)
            }

    async def _perform_policy_checks(self, policy: dict[str, Any]) -> dict[str, Any]:
        """执行策略检查"""
        checks: dict[str, _CheckResult] = {
            'disk_space': {'passed': True, 'message': ''},
            'backup_location': {'passed': True, 'message': ''},
            'encryption_key': {'passed': True, 'message': ''},
            'schedule_validity': {'passed': True, 'message': ''}
        }

        try:
            # 检查磁盘空间
            storage_location = Path(policy.get('storage', {}).get('primary_location', str(BACKUP_DIR)))
            if storage_location.exists():
                import psutil
                disk_usage = psutil.disk_usage(str(storage_location))
                free_gb = disk_usage.free / (1024 ** 3)

                min_free_gb = policy.get('retention', {}).get('min_free_space_gb', 10)
                if free_gb < min_free_gb:
                    checks['disk_space']['passed'] = False
                    checks['disk_space']['message'] = f'磁盘空间不足: {free_gb:.1f}GB 可用，需要至少 {min_free_gb}GB'
                else:
                    checks['disk_space']['message'] = f'磁盘空间充足: {free_gb:.1f}GB 可用'
            else:
                checks['backup_location']['passed'] = False
                checks['backup_location']['message'] = f'备份目录不存在: {storage_location}'

            # 检查备份位置
            if not storage_location.exists():
                try:
                    storage_location.mkdir(parents=True, exist_ok=True)
                    checks['backup_location']['message'] = f'备份目录已创建: {storage_location}'
                except OSError as e:
                    checks['backup_location']['passed'] = False
                    checks['backup_location']['message'] = f'无法创建备份目录: {e!s}'

            # 检查加密密钥
            encryption = policy.get('encryption', {})
            if encryption.get('enabled', False):
                key_path = encryption.get('key_path', '')
                if key_path and not Path(key_path).exists():
                    checks['encryption_key']['passed'] = False
                    checks['encryption_key']['message'] = f'加密密钥文件不存在: {key_path}'
                else:
                    checks['encryption_key']['message'] = '加密配置正常'

            # 检查计划任务有效性
            full_schedule = policy.get('full_backup', {}).get('schedule', '')

            if full_schedule and not self._is_valid_cron(full_schedule):
                checks['schedule_validity']['passed'] = False
                checks['schedule_validity']['message'] = f'全量备份计划无效: {full_schedule}'

            if checks['schedule_validity']['passed']:
                checks['schedule_validity']['message'] = '计划任务配置有效'

            return checks

        except Exception as e:  # defensive: policy checks should return partial results on failure
            logger.error(f"策略检查失败: {e}")
            checks['policy_checks'] = {'passed': False, 'message': f'策略检查失败: {e!s}'}
            return checks

    async def _apply_retention_policy(self, policy: dict[str, Any]) -> dict[str, Any]:
        """应用保留策略"""
        try:
            retention = policy.get('retention', {})
            if not retention.get('enabled', True):
                return {'applied': False, 'message': '保留策略已禁用', 'deleted_count': 0}

            strategy = retention.get('strategy', 'hybrid')
            keep_manual = retention.get('keep_manual_backups', True)
            keep_failed = retention.get('keep_failed_backups', False)

            # 获取所有备份记录
            async with get_async_db_context() as db:
                stmt = select(BackupRecord).order_by(BackupRecord.created_at.desc())
                result = await db.execute(stmt)
                all_records = result.scalars().all()

                # 应用保留策略
                records_to_keep = []
                records_to_delete = []

                for record in all_records:
                    keep = self._should_keep_backup(record, strategy, retention, keep_manual, keep_failed)

                    if keep:
                        records_to_keep.append(record)
                    else:
                        records_to_delete.append(record)

                # 删除备份文件
                deleted_files = []
                for record in records_to_delete:
                    if record.filename:
                        backup_file = BACKUP_DIR / record.filename
                        if backup_file.exists():
                            try:
                                backup_file.unlink()
                                deleted_files.append(record.filename)
                            except OSError as e:
                                logger.error(f"删除备份文件失败 {record.filename}: {e}")

                # 删除数据库记录（单条批量 DELETE 替代逐条 session.delete）
                if records_to_delete:
                    delete_ids = [record.id for record in records_to_delete]
                    await db.execute(delete(BackupRecord).where(BackupRecord.id.in_(delete_ids)))
                    await db.commit()  # manual-tx: 保留策略批量删除须即时提交（备份文件已物理删除，事务回滚无法复原）

                result = {
                    'applied': True,
                    'strategy': strategy,
                    'total_records': len(all_records),
                    'kept_records': len(records_to_keep),
                    'deleted_records': len(records_to_delete),
                    'deleted_files': deleted_files,
                    'message': f'保留策略应用成功，保留 {len(records_to_keep)} 个，删除 {len(records_to_delete)} 个备份记录'
                }

                if deleted_files:
                    logger.info(f"删除了 {len(deleted_files)} 个备份文件: {', '.join(deleted_files[:5])}{'...' if len(deleted_files) > 5 else ''}")

                return result

        except (SQLAlchemyError, OSError) as e:
            logger.error(f"应用保留策略失败: {e}")
            return {
                'applied': False,
                'error': str(e),
                'message': f'应用保留策略失败: {e!s}'
            }

    def _should_keep_backup(self,  # log-context: internal helper 无请求上下文
                           record: BackupRecord,
                           strategy: str,
                           retention: dict[str, Any],
                           keep_manual: bool,
                           keep_failed: bool) -> bool:
        """判断是否应该保留备份"""
        # 保留手动备份
        if keep_manual and record.trigger_type == 'manual':
            return True

        # 保留失败备份
        if keep_failed and record.status == 'failed':
            return True

        # 根据策略判断
        if strategy == 'time':
            # 基于时间保留
            if record.created_at:
                age_days = (datetime.now(record.created_at.tzinfo) - record.created_at).days
                # 兜底默认引用 _constants 单一来源（F-07）：此前硬编码 30，
                # 与 env 真源 BACKUP_RETENTION_DAYS 的默认值可能各自漂移。
                return age_days <= retention.get('retention_days', RETENTION_DAYS_DEFAULT)
            return True

        elif strategy == 'count':
            # 基于数量保留 - 这个逻辑需要在外部处理
            return True  # 外部会处理计数

        elif strategy == 'hybrid':
            # 混合策略 - 外部处理
            return True

        return True

    async def _apply_storage_policy(self, policy: dict[str, Any]) -> dict[str, Any]:
        """应用存储策略。

        Z05-R22：二级存储同步从未实现。旧代码在此直接返回「应用成功」，
        用户以为备份已复制到二级位置。显式 NotImplementedError **上抛**，
        由 ``apply_backup_policy`` 的异常分支报失败并发告警——此前本函数
        自带的 ``except Exception`` 会把异常就地吞成 ``applied: False``，
        外层照常返回 ``success: True``，告警分支永远到不了（合并前审查
        H2：假成功换了个位置继续存在）。
        默认未启用，不影响现行清理链路。
        """
        storage = policy.get('storage', {})
        sync_to_secondary = storage.get('sync_to_secondary', False)
        secondary_location = storage.get('secondary_location', '')

        if not sync_to_secondary or not secondary_location:
            return {
                'applied': False,
                'message': '存储同步未启用或未配置二级存储位置'
            }

        raise NotImplementedError(
            '二级存储同步尚未实现，请关闭 storage.sync_to_secondary'
        )

# 全局备份策略服务实例
policy_service = BackupPolicyService()
