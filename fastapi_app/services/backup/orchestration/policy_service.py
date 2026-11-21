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

# L-11（2026-11-21 审计）：加密检查改校验真正的决策点（原 policy['encryption']
# 键恒空，检查恒真）。crypto 只依赖 _constants/config，无循环导入。
from fastapi_app.services.backup.crypto import (
    get_backup_encryption_password,
    is_encryption_enabled,
)
from fastapi_app.services.backup.metrics.alert_service import alert_service

# L-12（2026-11-21 审计）：cron 校验单源收口到 schedule_service.parse_cron
# （原先两套口径相反：本文件放行步长 `*/5`，调度器 parse_cron 不认 → 假绿灯永不执行）。
from fastapi_app.services.backup.schedule_service import parse_cron
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
        """验证 cron 表达式（L-12，2026-11-21 审计：单源收口到 schedule_service.parse_cron）。

        原实现自带一套更宽松的校验（支持 `*/5` 步长等），与真正执行调度的
        ``schedule_service.parse_cron`` 口径**相反**：步长表达式能过这里的检查
        （假绿灯），但 parse_cron 不认步长 → 调度器永不命中，任务静默不跑。
        收口后「检查通过」与「调度可执行」是同一个事实源；本方法只是薄包装，
        保留方法名以稳定既有调用点与测试桩。
        """
        return parse_cron(cron_expr) is not None

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
            # M4（2026-10-25）：外发只给类型名，异常原文（可能含配置/路径）留内部日志
            await alert_service.send_alert(
                task_name='apply_backup_policy',
                error=f"应用备份策略失败: {type(e).__name__}（详见内部日志）",
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

            # 检查加密配置
            # L-11（2026-11-21 审计）：原实现读 policy['encryption']['key_path']——
            # 策略字典里基本没有这个键，`if key_path and not exists` 恒走 else
            # 「加密配置正常」，是恒真的假绿灯。改为校验**真正的加密决策点**
            # （crypto.resolve 链路：is_encryption_enabled + 密码可得性），与
            # AGENTS.md 红线 #4 的语义对齐：开关开而密码缺 = fail-closed 隐患，
            # 必须在策略检查里报出来而不是绿灯。
            encryption_enabled = is_encryption_enabled()
            encryption_password = get_backup_encryption_password() if encryption_enabled else None
            if encryption_enabled and not encryption_password:
                checks['encryption_key']['passed'] = False
                checks['encryption_key']['message'] = (
                    'BACKUP_ENCRYPTION_ENABLED=true 但未配置 '
                    'BACKUP_ENCRYPTION_PASSWORD/BACKUP_ENCRYPTION_KEY，'
                    '加密请求将 fail-closed（全量备份拒绝产出）'
                )
            else:
                checks['encryption_key']['message'] = (
                    '备份加密已启用且密码可用' if encryption_enabled else '备份加密未启用（明文备份）'
                )

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

    def _select_retention_deletions(self, all_records, records_to_delete):
        """按保底规则算出「本次真能删」的文件名集合，并返回被救回的名字。

        这条清理链此前会把备份删光（P2-1）。保底候选必须同时满足「磁盘上真有」与
        「不是 failed/running 记录」——否则救回的是打不开（或根本不存在）的东西，
        真实备份反而被全删（2026-11-19 评审 High）。
        """
        from fastapi_app.services.backup.cleanup.service import apply_keep_floor

        names_in_order = [
            r.filename for r in all_records
            if r.filename and (BACKUP_DIR / r.filename).is_file()
        ]
        corrupted = {
            r.filename for r in all_records
            if r.filename and r.status in ('failed', 'running')
        }
        to_delete_names = {r.filename for r in records_to_delete if r.filename}
        if names_in_order:
            to_delete_names = apply_keep_floor(names_in_order, to_delete_names, corrupted)
        elif to_delete_names:
            # DB 记录与磁盘文件不一致（有记录无文件）：无法判定哪份是「最后一份」，
            # 保守起见本轮不删任何文件，把不一致交给 sync_backup_records 自愈。
            logger.warning('保留策略跳过删除：DB 记录与磁盘文件不一致（无可定位的备份文件）')
            to_delete_names = set()
        rescued = {r.filename for r in records_to_delete if r.filename} - to_delete_names
        return to_delete_names, rescued

    @staticmethod
    def _unlink_retention_files(records_to_delete) -> list[str]:
        """删掉这些记录对应的备份文件与 sidecar，返回实际删除的文件名。"""
        from fastapi_app.services.backup.records import _delete_backup_sidecars

        deleted_files: list[str] = []
        for record in records_to_delete:
            if not record.filename:
                continue
            backup_file = BACKUP_DIR / record.filename
            if not backup_file.exists():
                continue
            try:
                backup_file.unlink()
                deleted_files.append(record.filename)
                _delete_backup_sidecars(backup_file)
            except OSError as e:
                logger.error(f"删除备份文件失败 {record.filename}: {e}")
        return deleted_files

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
                # P2-1（2026-10-17 审计）：本仓有两条清理链 —— 这里与 smart_cleanup。此前这条
                # 既没有「至少留一份」保底（能删光），也不删 .meta/.record（留下「有元数据没
                # 文件」的僵尸条目）。保底规则复用 cleanup 的同一实现，sidecar 复用同一 helper。
                # P2-1（2026-10-17 审计）：本仓有两条清理链 —— 这里与 smart_cleanup。此前这条
                # 既没有「至少留一份」保底（能删光），也不删 .meta/.record（留下「有元数据没
                # 文件」的僵尸条目）。保底与 sidecar 清理都收进下面的私有方法。
                to_delete_names, rescued = self._select_retention_deletions(
                    all_records, records_to_delete
                )
                if rescued:
                    logger.warning('保留策略本次会删光全部备份，已强制保留 %s', sorted(rescued))
                    records_to_delete = [
                        r for r in records_to_delete
                        if not r.filename or r.filename in to_delete_names
                    ]
                    # 被保底救回的记录要计入「保留」，否则 kept/deleted 两个数对不上实际文件数
                    records_to_keep.extend(r for r in all_records if r.filename in rescued)

                deleted_files = self._unlink_retention_files(records_to_delete)

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
            # B2-05（2026-10-24 审计）：原注释「外部会处理计数」所指的外部处理
            # 从未存在——BACKUP_RETENTION_COUNT 是死配置。现在 count/hybrid 的
            # 份数截断由 cleanup/service.py 的 smart_cleanup 按本策略值执行。
            return True

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
