"""
备份性能监控指标收集服务

收集和存储备份性能指标：
1. 备份耗时
2. 备份大小
3. 压缩率
4. 成功率
5. 资源使用（CPU、内存、磁盘IO）
6. 趋势分析
"""

import asyncio
import json
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, TypedDict

import psutil
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from fastapi_app.core.database import get_async_db_context
from fastapi_app.services.backup._constants import BACKUP_DIR
from fastapi_app.shared_models.backup_record import BackupRecord

logger = logging.getLogger(__name__)


class _DailyStat(TypedDict):
    """daily_stats 条目形态（纯类型层声明，运行期仍是普通 dict）。"""

    date: str
    total: int
    success: int
    failed: int
    total_size: int
    total_duration: float
    avg_duration: float


class BackupMetricsService:
    """备份性能监控指标服务类"""

    def __init__(self):
        self.metrics_config = self._load_metrics_config()
        self.metrics_file = BACKUP_DIR / 'backup_metrics.json'
        # Z05-R20：同一 worker 内并发备份任务会同时 read-modify-write 日文件，后写覆盖先写
        self._metrics_lock = asyncio.Lock()

    def _load_metrics_config(self) -> dict[str, Any]:
        """加载指标配置"""
        import os

        return {
            # 指标收集频率（秒）
            'collection_interval': int(os.environ.get('BACKUP_METRICS_INTERVAL', '60')),

            # 指标保留时间（天）
            'retention_days': int(os.environ.get('BACKUP_METRICS_RETENTION_DAYS', '90')),

            # 性能阈值
            'backup_duration_threshold': int(os.environ.get('BACKUP_DURATION_THRESHOLD', '1800')),  # 30分钟
            'backup_size_threshold': int(os.environ.get('BACKUP_SIZE_THRESHOLD', '1073741824')),  # 1GB
            'cpu_usage_threshold': float(os.environ.get('BACKUP_CPU_THRESHOLD', '80.0')),  # 80%
            'memory_usage_threshold': float(os.environ.get('BACKUP_MEMORY_THRESHOLD', '80.0')),  # 80%
            'disk_io_threshold': int(os.environ.get('BACKUP_DISK_IO_THRESHOLD', '100')),  # 100MB/s

            # 趋势分析窗口（小时）
            'trend_window_hours': int(os.environ.get('BACKUP_TREND_WINDOW', '24')),

            # 告警阈值
            'success_rate_threshold': float(os.environ.get('BACKUP_SUCCESS_RATE_THRESHOLD', '95.0')),  # 95%
            'failure_count_threshold': int(os.environ.get('BACKUP_FAILURE_COUNT_THRESHOLD', '3')),
        }

    async def collect_backup_metrics(self,
                                   backup_type: str,
                                   start_time: datetime,
                                   end_time: datetime,
                                   backup_size: int,
                                   success: bool,
                                   error_message: str | None = None,
                                   additional_metrics: dict[str, Any] | None = None) -> dict[str, Any]:
        """
        收集备份性能指标

        Args:
            backup_type: 备份类型（full/incremental）
            start_time: 开始时间
            end_time: 结束时间
            backup_size: 备份大小（字节）
            success: 是否成功
            error_message: 错误信息
            additional_metrics: 附加指标

        Returns:
            Dict[str, Any]: 收集的指标
        """
        try:
            # 计算耗时
            duration_seconds = (end_time - start_time).total_seconds()

            # 收集系统资源使用情况
            system_metrics = await self._collect_system_metrics()

            # 计算压缩率（如果有原始大小）
            compression_ratio = None
            if additional_metrics and 'original_size' in additional_metrics:
                original_size = additional_metrics['original_size']
                if original_size > 0:
                    compression_ratio = backup_size / original_size

            # 构建指标数据
            metrics = {
                'backup_type': backup_type,
                'start_time': start_time.isoformat(),
                'end_time': end_time.isoformat(),
                'duration_seconds': round(duration_seconds, 2),
                'backup_size_bytes': backup_size,
                'backup_size_mb': round(backup_size / (1024 ** 2), 2),
                'success': success,
                'error_message': error_message,
                'compression_ratio': compression_ratio,
                'system_metrics': system_metrics,
                'additional_metrics': additional_metrics or {},
                'collected_at': datetime.now().isoformat()
            }

            # 存储指标
            await self._store_metrics(metrics)

            # 检查性能阈值
            await self._check_performance_thresholds(metrics)

            logger.info(f"备份指标收集完成: {backup_type}, 耗时: {duration_seconds:.2f}秒, 大小: {backup_size / (1024**2):.2f}MB")
            return metrics

        except Exception as e:  # defensive: metrics collection must not crash the backup task
            logger.error(f"收集备份指标失败: {e}")
            return {
                'error': str(e),
                'success': False
            }

    async def _collect_system_metrics(self) -> dict[str, Any]:
        """收集系统资源指标"""
        try:
            # CPU使用率
            cpu_percent = psutil.cpu_percent(interval=0.1)

            # 内存使用率
            memory = psutil.virtual_memory()

            # 磁盘IO（如果有）
            disk_io = psutil.disk_io_counters()

            # 网络IO（如果有）
            net_io = psutil.net_io_counters()

            metrics = {
                'cpu_percent': round(cpu_percent, 2),
                'memory_percent': round(memory.percent, 2),
                'memory_available_gb': round(memory.available / (1024 ** 3), 2),
                'memory_used_gb': round(memory.used / (1024 ** 3), 2),
                'memory_total_gb': round(memory.total / (1024 ** 3), 2),
                'timestamp': datetime.now().isoformat()
            }

            if disk_io:
                metrics.update({
                    'disk_read_mb': round(disk_io.read_bytes / (1024 ** 2), 2),
                    'disk_write_mb': round(disk_io.write_bytes / (1024 ** 2), 2),
                    'disk_read_count': disk_io.read_count,
                    'disk_write_count': disk_io.write_count,
                })

            if net_io:
                metrics.update({
                    'net_sent_mb': round(net_io.bytes_sent / (1024 ** 2), 2),
                    'net_recv_mb': round(net_io.bytes_recv / (1024 ** 2), 2),
                })

            return metrics

        except Exception as e:  # defensive: psutil 可能抛任意运行时异常，系统指标收集失败不影响备份主流程
            logger.error(f"收集系统指标失败: {e}")
            return {
                'error': str(e),
                'timestamp': datetime.now().isoformat()
            }

    async def _store_metrics(self, metrics: dict[str, Any]) -> None:
        """存储指标数据（进程内串行化，避免并发 read-modify-write 丢点）。"""
        async with self._metrics_lock:
            await self._store_metrics_unlocked(metrics)

    async def _store_metrics_unlocked(self, metrics: dict[str, Any]) -> None:
        """实际读写日指标文件（调用方须持有 self._metrics_lock）。"""
        try:
            # 确保指标目录存在
            metrics_dir = BACKUP_DIR / 'metrics'
            metrics_dir.mkdir(parents=True, exist_ok=True)

            # 生成文件名
            timestamp = datetime.now().strftime('%Y%m%d')
            metrics_file = metrics_dir / f'backup_metrics_{timestamp}.json'

            # 读取现有指标或创建新文件
            all_metrics = []
            if metrics_file.exists():
                try:
                    with open(metrics_file, encoding='utf-8') as f:
                        all_metrics = json.load(f)
                        if not isinstance(all_metrics, list):
                            all_metrics = []
                except (OSError, json.JSONDecodeError):
                    all_metrics = []

            # 添加新指标
            all_metrics.append(metrics)

            # 保存指标
            with open(metrics_file, 'w', encoding='utf-8') as f:
                json.dump(all_metrics, f, ensure_ascii=False, indent=2)

            # 清理旧指标文件
            await self._cleanup_old_metrics(metrics_dir)

        except OSError as e:
            logger.error(f"存储指标数据失败: {e}")

    async def _cleanup_old_metrics(self, metrics_dir: Path) -> None:
        """清理旧的指标文件"""
        try:
            retention_days = self.metrics_config['retention_days']
            cutoff_date = datetime.now() - timedelta(days=retention_days)

            metrics_files = list(metrics_dir.glob('backup_metrics_*.json'))
            deleted_count = 0

            for metrics_file in metrics_files:
                try:
                    # 从文件名解析日期
                    filename = metrics_file.stem
                    date_str = filename.replace('backup_metrics_', '')
                    file_date = datetime.strptime(date_str, '%Y%m%d')

                    if file_date < cutoff_date:
                        metrics_file.unlink()
                        deleted_count += 1

                except (ValueError, IndexError):
                    # 如果无法解析日期，使用文件修改时间
                    file_mtime = datetime.fromtimestamp(metrics_file.stat().st_mtime)
                    if file_mtime < cutoff_date:
                        metrics_file.unlink()
                        deleted_count += 1

            if deleted_count > 0:
                logger.info(f"清理了 {deleted_count} 个旧的指标文件")

        except OSError as e:
            logger.error(f"清理指标文件失败: {e}")

    async def _check_performance_thresholds(self, metrics: dict[str, Any]) -> None:
        """检查性能阈值"""
        try:
            issues = []

            # 检查备份耗时
            duration = metrics.get('duration_seconds', 0)
            duration_threshold = self.metrics_config['backup_duration_threshold']
            if duration > duration_threshold:
                issues.append(f"备份耗时过长: {duration:.2f}秒 > {duration_threshold}秒阈值")

            # 检查备份大小
            backup_size = metrics.get('backup_size_bytes', 0)
            size_threshold = self.metrics_config['backup_size_threshold']
            if backup_size > size_threshold:
                issues.append(f"备份文件过大: {backup_size / (1024**3):.2f}GB > {size_threshold / (1024**3):.2f}GB阈值")

            # 检查系统资源
            system_metrics = metrics.get('system_metrics', {})
            cpu_percent = system_metrics.get('cpu_percent', 0)
            cpu_threshold = self.metrics_config['cpu_usage_threshold']
            if cpu_percent > cpu_threshold:
                issues.append(f"CPU使用率过高: {cpu_percent:.1f}% > {cpu_threshold}%阈值")

            memory_percent = system_metrics.get('memory_percent', 0)
            memory_threshold = self.metrics_config['memory_usage_threshold']
            if memory_percent > memory_threshold:
                issues.append(f"内存使用率过高: {memory_percent:.1f}% > {memory_threshold}%阈值")

            # 如果有问题，记录警告日志
            if issues:
                logger.warning(f"性能阈值检查发现问题: {'; '.join(issues)}")
                # Z05-R20：阈值问题接入告警通道（失败仅记日志，不影响指标采集）
                try:
                    from fastapi_app.services.backup.metrics.alert_service import alert_service
                    await alert_service.send_alert(
                        task_name='backup_metrics',
                        error='; '.join(issues),
                        task_type='backup',
                        severity='warning',
                    )
                except Exception as alert_err:  # broad-except: 告警通道失败不得打断指标链路
                    logger.warning(f"性能阈值告警发送失败: {alert_err}")

        except Exception as e:  # defensive: threshold check must not crash metrics collection
            logger.error(f"检查性能阈值失败: {e}")

    async def get_performance_summary(self,
                                    hours: int = 24,
                                    backup_type: str | None = None) -> dict[str, Any]:
        """
        获取性能摘要

        Args:
            hours: 时间范围（小时）
            backup_type: 备份类型过滤

        Returns:
            Dict[str, Any]: 性能摘要
        """
        try:
            async with get_async_db_context() as db:
                # 计算时间范围
                cutoff_time = datetime.now() - timedelta(hours=hours)

                # 构建查询
                stmt = select(BackupRecord)
                if backup_type:
                    stmt = stmt.where(BackupRecord.type == backup_type)
                stmt = stmt.where(BackupRecord.created_at >= cutoff_time)

                result = await db.execute(stmt)
                records = result.scalars().all()

                if not records:
                    return {
                        'total_backups': 0,
                        'success_rate': 0,
                        'average_duration': 0,
                        'total_size_mb': 0,
                        'time_period_hours': hours,
                        'backup_type': backup_type or 'all'
                    }

                # 计算统计信息
                total_count = len(records)
                success_count = sum(1 for r in records if r.status == 'success')
                failed_count = total_count - success_count
                success_rate = (success_count / total_count * 100) if total_count > 0 else 0

                # 计算平均耗时
                durations = [r.duration_seconds for r in records if r.duration_seconds]
                avg_duration = sum(durations) / len(durations) if durations else 0

                # 计算总大小
                sizes = [r.size for r in records if r.size]
                total_size = sum(sizes) if sizes else 0

                # 按类型分组
                type_stats = {}
                for record in records:
                    backup_type_key = record.type or 'unknown'
                    if backup_type_key not in type_stats:
                        type_stats[backup_type_key] = {
                            'count': 0,
                            'success': 0,
                            'failed': 0,
                            'total_size': 0,
                            'avg_duration': 0
                        }

                    type_stats[backup_type_key]['count'] += 1
                    if record.status == 'success':
                        type_stats[backup_type_key]['success'] += 1
                    else:
                        type_stats[backup_type_key]['failed'] += 1

                    if record.size:
                        type_stats[backup_type_key]['total_size'] += record.size

                    if record.duration_seconds:
                        # 这里简化处理，实际应该计算平均值
                        pass

                # 计算每个类型的平均持续时间
                for backup_type_key, stats in type_stats.items():
                    type_records = [r for r in records if (r.type or 'unknown') == backup_type_key and r.duration_seconds]
                    if type_records:
                        stats['avg_duration'] = sum(r.duration_seconds for r in type_records) / len(type_records)

                summary = {
                    'time_period_hours': hours,
                    'backup_type': backup_type or 'all',
                    'total_backups': total_count,
                    'success_count': success_count,
                    'failed_count': failed_count,
                    'success_rate': round(success_rate, 2),
                    'average_duration_seconds': round(avg_duration, 2),
                    'total_size_bytes': total_size,
                    'total_size_mb': round(total_size / (1024 ** 2), 2),
                    'type_stats': type_stats,
                    'time_range_start': cutoff_time.isoformat(),
                    'time_range_end': datetime.now().isoformat()
                }

                return summary

        except SQLAlchemyError as e:
            logger.error(f"获取性能摘要失败: {e}")
            return {
                'error': str(e),
                'message': '获取性能摘要失败'
            }

    async def get_trend_analysis(self,
                               days: int = 7,
                               backup_type: str | None = None) -> dict[str, Any]:
        """
        获取趋势分析

        Args:
            days: 分析天数
            backup_type: 备份类型过滤

        Returns:
            Dict[str, Any]: 趋势分析结果
        """
        try:
            async with get_async_db_context() as db:
                # 计算时间范围（含当天共 days 天）
                end_date = datetime.now()
                start_date = end_date - timedelta(days=days - 1)

                # 按天分组查询
                # 注意：这里简化处理，实际应该使用SQL的日期函数
                stmt = select(BackupRecord)
                if backup_type:
                    stmt = stmt.where(BackupRecord.type == backup_type)
                stmt = stmt.where(BackupRecord.created_at >= start_date)

                result = await db.execute(stmt)
                records = result.scalars().all()

                # 按天分组
                daily_stats: dict[str, _DailyStat] = {}
                current_date = start_date.date()
                while current_date <= end_date.date():
                    date_key = current_date.isoformat()
                    daily_stats[date_key] = {
                        'date': date_key,
                        'total': 0,
                        'success': 0,
                        'failed': 0,
                        'total_size': 0,
                        'total_duration': 0,
                        'avg_duration': 0
                    }
                    current_date += timedelta(days=1)

                # 填充数据
                for record in records:
                    if record.created_at:
                        date_key = record.created_at.date().isoformat()
                        if date_key in daily_stats:
                            stats = daily_stats[date_key]
                            stats['total'] += 1

                            if record.status == 'success':
                                stats['success'] += 1
                            else:
                                stats['failed'] += 1

                            if record.size:
                                stats['total_size'] += record.size

                            if record.duration_seconds:
                                stats['total_duration'] += record.duration_seconds

                # 计算平均值
                for _date_key, stats in daily_stats.items():
                    if stats['success'] > 0:
                        stats['avg_duration'] = stats['total_duration'] / stats['success']

                # 转换为列表
                daily_list = list(daily_stats.values())

                # 计算总体趋势
                total_records = sum(stats['total'] for stats in daily_stats.values())
                total_success = sum(stats['success'] for stats in daily_stats.values())
                total_failed = sum(stats['failed'] for stats in daily_stats.values())
                overall_success_rate = (total_success / total_records * 100) if total_records > 0 else 0

                # 计算成功率趋势
                success_rates = []
                for stats in daily_stats.values():
                    rate = (stats['success'] / stats['total'] * 100) if stats['total'] > 0 else 0
                    success_rates.append(round(rate, 2))

                # 计算平均成功率
                avg_success_rate = sum(success_rates) / len(success_rates) if success_rates else 0

                # 计算趋势方向
                trend_direction = 'stable'
                if len(success_rates) >= 2:
                    recent_rate = success_rates[-1]
                    previous_rate = success_rates[-2] if len(success_rates) >= 2 else recent_rate

                    if recent_rate > previous_rate + 5:  # 提升5%以上
                        trend_direction = 'improving'
                    elif recent_rate < previous_rate - 5:  # 下降5%以上
                        trend_direction = 'declining'

                analysis = {
                    'time_period_days': days,
                    'backup_type': backup_type or 'all',
                    'start_date': start_date.date().isoformat(),
                    'end_date': end_date.date().isoformat(),
                    'total_backups': total_records,
                    'total_success': total_success,
                    'total_failed': total_failed,
                    'overall_success_rate': round(overall_success_rate, 2),
                    'average_success_rate': round(avg_success_rate, 2),
                    'trend_direction': trend_direction,
                    'daily_stats': daily_list,
                    'success_rates': success_rates,
                    'recommendations': self._generate_trend_recommendations(daily_list, success_rates)
                }

                return analysis

        except SQLAlchemyError as e:
            logger.error(f"获取趋势分析失败: {e}")
            return {
                'error': str(e),
                'message': '获取趋势分析失败'
            }

    def _generate_trend_recommendations(self,
                                      daily_stats: list[_DailyStat],
                                      success_rates: list[float]) -> list[str]:
        """根据趋势生成建议"""
        recommendations: list[str] = []

        if not daily_stats or not success_rates:
            return recommendations

        # 检查成功率趋势
        if len(success_rates) >= 3:
            recent_avg = sum(success_rates[-3:]) / 3
            overall_avg = sum(success_rates) / len(success_rates)

            if recent_avg < 95:
                recommendations.append("最近3天备份成功率低于95%，建议检查备份配置和系统资源")
            elif recent_avg < overall_avg - 10:
                recommendations.append("最近备份成功率有明显下降趋势，建议关注")

        # 检查备份频率
        daily_counts = [stats['total'] for stats in daily_stats[-7:]]  # 最近7天
        avg_daily_count = sum(daily_counts) / len(daily_counts) if daily_counts else 0

        if avg_daily_count < 1:
            recommendations.append("备份频率过低，建议检查备份任务调度")
        elif avg_daily_count > 50:
            recommendations.append("备份频率过高，可能影响系统性能，建议调整备份策略")

        # 检查备份大小趋势
        recent_sizes = [stats['total_size'] for stats in daily_stats[-3:]]
        if len(recent_sizes) >= 2:
            size_growth = (recent_sizes[-1] - recent_sizes[0]) / recent_sizes[0] * 100 if recent_sizes[0] > 0 else 0
            if abs(size_growth) > 50:  # 增长或减少超过50%
                recommendations.append(f"备份大小变化显著 ({size_growth:.1f}%)，建议检查数据增长情况")

        return recommendations

    async def get_performance_alerts(self) -> list[dict[str, Any]]:
        """获取性能告警"""
        try:
            alerts = []

            # 获取最近24小时的性能摘要
            summary = await self.get_performance_summary(hours=24)

            # 检查成功率
            success_rate = summary.get('success_rate', 100)
            success_threshold = self.metrics_config['success_rate_threshold']
            if success_rate < success_threshold:
                alerts.append({
                    'type': 'success_rate_low',
                    'severity': 'warning',
                    'message': f'备份成功率低于阈值: {success_rate:.1f}% < {success_threshold}%',
                    'current_value': success_rate,
                    'threshold': success_threshold,
                    'time_period': '24h'
                })

            # 检查失败次数
            failed_count = summary.get('failed_count', 0)
            failure_threshold = self.metrics_config['failure_count_threshold']
            if failed_count >= failure_threshold:
                alerts.append({
                    'type': 'failure_count_high',
                    'severity': 'error',
                    'message': f'备份失败次数超过阈值: {failed_count}次 >= {failure_threshold}次',
                    'current_value': failed_count,
                    'threshold': failure_threshold,
                    'time_period': '24h'
                })

            # 检查平均耗时
            avg_duration = summary.get('average_duration_seconds', 0)
            duration_threshold = self.metrics_config['backup_duration_threshold']
            if avg_duration > duration_threshold:
                alerts.append({
                    'type': 'duration_too_long',
                    'severity': 'warning',
                    'message': f'平均备份耗时过长: {avg_duration:.1f}秒 > {duration_threshold}秒',
                    'current_value': avg_duration,
                    'threshold': duration_threshold,
                    'time_period': '24h'
                })

            # 检查总大小
            total_size_mb = summary.get('total_size_mb', 0)
            size_threshold_mb = self.metrics_config['backup_size_threshold'] / (1024 ** 2)
            if total_size_mb > size_threshold_mb:
                alerts.append({
                    'type': 'size_too_large',
                    'severity': 'warning',
                    'message': f'备份总大小过大: {total_size_mb:.1f}MB > {size_threshold_mb:.1f}MB',
                    'current_value': total_size_mb,
                    'threshold': size_threshold_mb,
                    'time_period': '24h'
                })

            return alerts

        except Exception as e:  # defensive: alert generation must not crash metrics service
            logger.error(f"获取性能告警失败: {e}")
            return [{
                'type': 'metrics_error',
                'severity': 'error',
                'message': f'获取性能告警失败: {e!s}'
            }]

    async def export_metrics_report(self,
                                  days: int = 7,
                                  format: str = 'json') -> dict[str, Any]:
        """
        导出指标报告

        Args:
            days: 报告天数
            format: 报告格式（json/csv）

        Returns:
            Dict[str, Any]: 报告数据
        """
        try:
            # 获取性能摘要
            summary = await self.get_performance_summary(hours=days*24)

            # 获取趋势分析
            trend = await self.get_trend_analysis(days=days)

            # 获取性能告警
            alerts = await self.get_performance_alerts()

            # 构建报告
            report = {
                'generated_at': datetime.now().isoformat(),
                'time_period_days': days,
                'summary': summary,
                'trend_analysis': trend,
                'alerts': alerts,
                'recommendations': trend.get('recommendations', [])
            }

            # 根据格式处理
            if format == 'csv':
                # Z05-R20：CSV 导出未实现——显式失败，避免调用方拿到 JSON 却以为 CSV
                raise NotImplementedError('指标报告 CSV 导出尚未实现（当前仅支持 json）')

            return report

        except Exception as e:  # defensive: report export must return error payload gracefully
            logger.error(f"导出指标报告失败: {e}")
            return {
                'error': str(e),
                'message': '导出指标报告失败'
            }


# 全局性能指标服务实例
metrics_service = BackupMetricsService()
