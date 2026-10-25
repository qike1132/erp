"""备份清理服务 —— 全量-only，按天数保留。

规则（唯一）：扫描 BACKUP_DIR 下全量文件（erp_backup_ 手动 / erp_auto_ 自动，
后缀 .zip/.zip.enc），年龄（.meta.created_at，缺则 mtime）> BACKUP_RETENTION_DAYS
天即删；手动与自动一视同仁；任何情况下至少保留最新 1 个。

保留的既有方法（语义原样）：_execute_cleanup / _delete_backup_records /
_save_cleanup_report / _cleanup_old_reports / _send_cleanup_notification /
get_cleanup_history；__init__/_load_cleanup_config 为上述方法的配置依赖
（cleanup_report_days 等），一并保留。
"""
import json
import logging
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import psutil
from sqlalchemy.exc import SQLAlchemyError

from fastapi_app.core.database import get_async_db_context
from fastapi_app.services.backup._constants import (
    BACKUP_CLEANUP_PREFIXES,
    BACKUP_CLEANUP_SUFFIXES,
    BACKUP_DIR,
    retention_count,
    retention_days,
)
from fastapi_app.services.backup.metrics.alert_service import alert_service
from fastapi_app.services.backup.records import _delete_backup_sidecars
from fastapi_app.shared_models.backup_record import BackupRecord

logger = logging.getLogger(__name__)

# 清理口径（单源见 _constants，L-1）：只清在产格式；legacy（erp_incremental_/.json）
# 刻意不在清理范围——防误删历史档案。
_FULL_PREFIXES = BACKUP_CLEANUP_PREFIXES
_FULL_SUFFIXES = BACKUP_CLEANUP_SUFFIXES
_WRITE_GRACE_SECONDS = 120


def ensure_backup_dir() -> None:  # log-context: internal helper 无请求上下文
    """确保备份目录存在。**必须定义在本模块**（用本模块 BACKUP_DIR），
    否则从 records 导入会让测试的 monkeypatch(BACKUP_DIR) 失效、在真实目录建目录。"""
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)


def _backup_created_time(f: Path) -> datetime:  # log-context: internal helper 无请求上下文
    """备份文件真实创建时间：优先 .meta.created_at，缺则 mtime。"""
    meta_path = f.parent / (f.name + '.meta')
    if meta_path.exists():
        try:
            meta = json.loads(meta_path.read_text(encoding='utf-8'))
            created_at = meta.get('created_at')
            if created_at:
                return datetime.strptime(created_at, '%Y-%m-%d %H:%M:%S')
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            pass  # defensive: 异常静默处理,不影响主流程
    return datetime.fromtimestamp(f.stat().st_mtime)


class BackupCleanupService:
    """备份清理服务：全量-only、按天数保留。"""

    def __init__(self):
        self.cleanup_config = self._load_cleanup_config()

    def _load_cleanup_config(self) -> dict[str, Any]:
        """清理服务配置。

        仅保留仍被读取的键。已**退役**、不再被清理规则读取的 env（删代码读的同时
        已从 .env.example 移除，避免运维误信）：BACKUP_KEEP_MANUAL / BACKUP_KEEP_FAILED /
        BACKUP_SMART_CLEANUP / BACKUP_TEST_SAMPLE_RATE / BACKUP_NOTIFY_CLEANUP /
        BACKUP_TEST_BEFORE_DELETE。保留策略见 _retention_days()。
        """
        import os

        return {'cleanup_report_days': int(os.environ.get('BACKUP_CLEANUP_REPORT_DAYS', '7'))}

    def _retention_days(self) -> int:
        """保留天数：env 单一真源（BACKUP_RETENTION_DAYS，默认 7），运行时求值。"""
        return retention_days()

    async def smart_cleanup(self) -> dict[str, Any]:
        logger.info('开始备份清理（全量-only，保留 %d 天）...', self._retention_days())
        try:
            disk_info = await self._check_disk_space()
            backup_files = await self._get_backup_files_info()
            if not backup_files:
                return {'success': True, 'message': '没有找到备份文件',
                        'cleaned_files': [], 'kept_files': [], 'disk_info': disk_info}

            cutoff = datetime.now() - timedelta(days=self._retention_days())
            files_to_keep = {f['name'] for f in backup_files if f['mtime'] >= cutoff}
            files_to_delete = {f['name'] for f in backup_files if f['name'] not in files_to_keep}
            files_to_delete = self._enforce_keep_floor(backup_files, files_to_delete)
            files_to_keep = {f['name'] for f in backup_files} - files_to_delete
            # B2-05：count/hybrid 的份数截断作用于**保留集**（超额者转删除）
            files_to_keep = self._enforce_count_ceiling(backup_files, files_to_keep)
            files_to_delete = {f['name'] for f in backup_files} - files_to_keep

            cleanup_result = await self._execute_cleanup(files_to_delete)
            report = await self._generate_cleanup_report(
                backup_files, files_to_keep, files_to_delete, cleanup_result, disk_info)
            if cleanup_result['deleted_count'] > 0:
                await self._send_cleanup_notification(report)
            logger.info('备份清理完成: 删除 %d，保留 %d',
                        cleanup_result['deleted_count'], len(files_to_keep))
            return report
        except Exception as e:  # defensive: cleanup task must report failure but not crash
            logger.error('备份清理失败: %s', e)
            await alert_service.send_alert(task_name='smart_cleanup',
                                           error=f'备份清理失败: {e!s}',
                                           task_type='cleanup', severity='error')
            return {'success': False, 'error': str(e), 'message': '备份清理失败'}

    async def _check_disk_space(self) -> dict[str, Any]:
        """磁盘信息（仅用于报告，不再驱动删除）。"""
        try:
            ensure_backup_dir()
            backup_path = BACKUP_DIR.resolve()
            u = psutil.disk_usage(str(backup_path))
            free_gb = u.free / (1024 ** 3)
            return {'path': str(backup_path), 'total_gb': round(u.total / 1024**3, 2),
                    'used_gb': round(u.used / 1024**3, 2), 'free_gb': round(free_gb, 2),
                    'used_percent': round(u.percent, 2),
                    'free_percent': round(100 - u.percent, 2)}
        except OSError as e:
            logger.error('检查磁盘空间失败: %s', e)
            return {'error': str(e)}

    async def _get_backup_files_info(self) -> list[dict[str, Any]]:
        """扫描全量备份文件（不含增量）。"""
        try:
            ensure_backup_dir()
            out: list[dict[str, Any]] = []
            for fp in BACKUP_DIR.iterdir():
                if not fp.is_file():
                    continue
                if not (fp.name.startswith(_FULL_PREFIXES) and fp.name.endswith(_FULL_SUFFIXES)):
                    continue
                try:
                    if time.time() - fp.stat().st_mtime < _WRITE_GRACE_SECONDS:
                        logger.debug('跳过仍在写入的备份文件: %s', fp.name)
                        continue
                except OSError:
                    continue
                out.append({'path': fp, 'name': fp.name,
                            'size_bytes': fp.stat().st_size,
                            'size_mb': round(fp.stat().st_size / 1024**2, 2),
                            'mtime': _backup_created_time(fp)})
            out.sort(key=lambda x: x['mtime'], reverse=True)
            return out
        except OSError as e:
            logger.error('获取备份文件信息失败: %s', e)
            return []

    def _enforce_count_ceiling(self, backup_files: list[dict[str, Any]],
                               files_to_keep: set[str]) -> set[str]:
        """B2-05（2026-10-24 审计）：count/hybrid 策略的份数上限落地。

        BACKUP_RETENTION_COUNT 此前是死配置（policy_service 声称「外部会处理
        计数」而外部处理从未存在）——保留份数无上限，备份可吃满磁盘。此处按
        mtime 倒序保留最新 retention_count 份，超额部分进删除集。
        """
        from fastapi_app.services.backup.orchestration.policy_service import BackupPolicyService

        policy = BackupPolicyService()._load_policy_config().get('retention', {})
        strategy = policy.get('strategy', 'days')
        if strategy not in ('count', 'hybrid'):
            return files_to_keep
        ceiling = retention_count()
        if ceiling <= 0 or len(backup_files) <= ceiling:
            return files_to_keep
        # mtime 倒序（backup_files 已按 mtime 倒序，防御式再排一次）
        ordered = sorted(backup_files, key=lambda f: f['mtime'], reverse=True)
        over_quota = [f['name'] for f in ordered[ceiling:]]
        # 只把「本会话打算保留」的超额者移出保留集（转由外层统一删除）
        excess = {name for name in over_quota if name in files_to_keep}
        if not excess:
            return files_to_keep
        logger.info('count 策略份数截断：保留最新 %d 份，超额移出 %d 份', ceiling, len(excess))
        return files_to_keep - excess

    def _enforce_keep_floor(self, backup_files: list[dict[str, Any]],
                            files_to_delete: set[str]) -> set[str]:
        """兜底：任何情况下至少留一个可还原的全量备份。

        只在**会删光**时介入，从删除集里救回最新且未被判定损坏的一个
        （列表按 mtime 倒序，首个非 corrupted 即最新可还原者）。

        注意：全量-only 扫描（_get_backup_files_info）已不产出 health_status，
        `f.get('health_status') != 'corrupted'` 当前恒真、candidates 恒等于全部 ——
        保留该过滤是**有意的防御分支**（未来若恢复健康检测可直接生效，
        test_backup_cleanup_keep_floor.py 仍直测它）。
        """
        if any(f['name'] not in files_to_delete for f in backup_files):
            return files_to_delete
        candidates = [f for f in backup_files if f.get('health_status') != 'corrupted']
        if not candidates:
            candidates = list(backup_files)
        if not candidates:
            return files_to_delete
        survivor = candidates[0]['name']
        files_to_delete.discard(survivor)
        logger.warning('本次清理会删光全部 %d 个备份，已强制保留 %s', len(backup_files), survivor)
        return files_to_delete

    async def _execute_cleanup(self, files_to_delete: set[str]) -> dict[str, Any]:
        """执行清理操作"""
        deleted_files = []
        errors: list[str] = []

        try:
            for filename in files_to_delete:
                filepath = BACKUP_DIR / filename
                if filepath.exists():
                    try:
                        filepath.unlink()
                        deleted_files.append(filename)
                        logger.info(f"删除备份文件: {filename}")

                        # 同时删除伴随文件：.meta（含 .zip.enc.meta）与 .record。
                        # 与 records.cleanup_old_backups 同口径（共用同一 helper），
                        # 避免「删了 .enc，.zip.enc.meta / .record 永久残留」。
                        # t38：errors 聚合器透传给 helper，伴随文件清理失败进清理
                        # 结果（error_count/success），不再只有 ERROR 日志。
                        _delete_backup_sidecars(filepath, errors)

                    except OSError as e:
                        errors.append(f"{filename}: {e!s}")
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

    async def _delete_backup_records(self, deleted_files: list[str]) -> tuple[int, bool]:
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
                    await db.commit()  # manual-tx: 批量清理须即时提交并释放行锁（异常由本函数兜底，不回滚已删文件）

                return deleted_count, False

        except SQLAlchemyError as e:
            logger.error(f"删除备份记录失败: {e}")
            return 0, True

    async def _generate_cleanup_report(self,
                                     backup_files: list[dict[str, Any]],
                                     files_to_keep: set[str],
                                     files_to_delete: set[str],
                                     cleanup_result: dict[str, Any],
                                     disk_info: dict[str, Any]) -> dict[str, Any]:
        try:
            total_mb = sum(f['size_mb'] for f in backup_files)
            deleted_mb = sum(f['size_mb'] for f in backup_files if f['name'] in files_to_delete)
            kept_mb = sum(f['size_mb'] for f in backup_files if f['name'] in files_to_keep)
            report = {
                'timestamp': datetime.now().isoformat(),
                'success': cleanup_result['success'],
                'disk_info': disk_info,
                'retention_days': self._retention_days(),
                'summary': {
                    'total_files': len(backup_files), 'kept_files': len(files_to_keep),
                    'deleted_files': len(files_to_delete),
                    'total_size_mb': round(total_mb, 2), 'kept_size_mb': round(kept_mb, 2),
                    'deleted_size_mb': round(deleted_mb, 2),
                },
                'cleanup_result': cleanup_result,
            }
            await self._save_cleanup_report(report)
            return report
        except Exception as e:  # defensive: report generation must not abort cleanup
            logger.error('生成清理报告失败: %s', e)
            return {'timestamp': datetime.now().isoformat(), 'success': False, 'error': str(e)}

    async def _save_cleanup_report(self, report: dict[str, Any]) -> None:
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

    async def _send_cleanup_notification(self, report: dict[str, Any]) -> None:
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

    async def get_cleanup_history(self, days: int = 7) -> list[dict[str, Any]]:
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
                        with open(report_file, encoding='utf-8') as f:
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
