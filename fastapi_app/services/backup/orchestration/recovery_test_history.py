"""灾备演练历史查询服务（2026-10-15 自 recovery_test_service.py 拆出）。

搬移原因：``get_test_history`` / ``get_test_summary`` 因「API 形状演进」而变，
``perform_recovery_test`` 因「备份格式/演练执行」而变——两个不同的变更原因
（Divergent Change）此前挤在同一个 1400+ 行的类里。拆出后各自独立演进。

代码为纯方法搬移，行为与拆分前逐字一致；原服务实例上的同名方法保留为薄委托，
外部调用方（hasattr 契约测试等）不受影响。
"""
import json
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class RecoveryTestHistoryService:
    """演练历史报告的读取与汇总（只读，不触碰演练执行）。"""

    def __init__(self, test_results_dir: Path):
        self.test_results_dir = test_results_dir

    async def get_test_history(self, days: int = 30) -> list[dict[str, Any]]:
        """获取测试历史记录"""
        try:
            test_results_dir = self.test_results_dir
            if not test_results_dir.exists():
                return []

            cutoff_date = datetime.now() - timedelta(days=days)
            reports = []

            for report_file in test_results_dir.glob('recovery_test_*.json'):
                try:
                    # 从文件名解析日期
                    filename = report_file.stem
                    date_str = filename.replace('recovery_test_', '')
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
            reports.sort(key=lambda x: x.get('start_time', ''), reverse=True)
            return reports

        except OSError as e:
            logger.error(f"获取测试历史失败: {e}")
            return []

    async def get_test_summary(self, days: int = 30) -> dict[str, Any]:
        """获取测试摘要"""
        try:
            test_history = await self.get_test_history(days)

            if not test_history:
                return {
                    'total_tests': 0,
                    'success_rate': 0,
                    'average_duration_seconds': 0,
                    'recent_tests': []
                }

            total_tests = len(test_history)
            successful_tests = sum(1 for test in test_history if test.get('overall_success', False))
            success_rate = (successful_tests / total_tests * 100) if total_tests > 0 else 0

            durations = [test.get('duration_seconds', 0) for test in test_history]
            avg_duration = sum(durations) / len(durations) if durations else 0

            # 按备份类型统计
            type_stats = {}
            for test in test_history:
                backup_type = test.get('backup_info', {}).get('backup_type', 'unknown')
                if backup_type not in type_stats:
                    type_stats[backup_type] = {'total': 0, 'success': 0}

                type_stats[backup_type]['total'] += 1
                if test.get('overall_success', False):
                    type_stats[backup_type]['success'] += 1

            summary = {
                'time_period_days': days,
                'total_tests': total_tests,
                'successful_tests': successful_tests,
                'failed_tests': total_tests - successful_tests,
                'success_rate': round(success_rate, 2),
                'average_duration_seconds': round(avg_duration, 2),
                'type_stats': type_stats,
                'recent_tests': test_history[:10],  # 最近10次测试
                'last_test_time': test_history[0].get('end_time') if test_history else None,
                'last_test_result': test_history[0].get('overall_success') if test_history else None
            }

            return summary

        except Exception as e:  # defensive: summary generation must return error payload gracefully
            logger.error(f"获取测试摘要失败: {e}")
            return {
                'error': str(e),
                'message': '获取测试摘要失败'
            }
