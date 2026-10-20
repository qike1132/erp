"""
报表导出异步任务
将耗时报表生成放入 ARQ Worker 执行（同步 DB 会话通过 asyncio.to_thread 运行）。
"""
import asyncio
import contextlib
import os
import tempfile

from sqlalchemy.orm import sessionmaker

from fastapi_app.core.database import get_sync_engine
from fastapi_app.core.logger import logger

_SyncSession = sessionmaker(
    autocommit=False, autoflush=False, bind=get_sync_engine()
)

# 导出方法表：与 /reports/export 的 ALLOWED_REPORT_TYPES、tasks.py 的
# ASYNC_EXPORT_REPORT_TYPES、report_data_service.get_all_logs_data 的分支同口径
# （tests/test_report.py::TestExportTypeParity 钉住一致，新增报表类型四处同步改）。
_EXPORT_METHODS = {
    'order': 'export_order_logs',
    'stockin': 'export_stockin_logs',
    'stockout': 'export_stockout_logs',
    'deduction': 'export_deduction_logs',
    'return': 'export_return_logs',
}


async def export_report_task(ctx, report_type: str, filters: dict, user_id: int):
    """异步导出报表

    Args:
        ctx: ARQ 上下文（含 job_id）
        report_type: 报表类型（见 _EXPORT_METHODS / ASYNC_EXPORT_REPORT_TYPES）
        filters: 筛选条件 {customer, product, status, start_date, end_date}
        user_id: 操作用户ID

    Returns:
        dict: 导出结果 {success, file_path, filename, row_count, task_id}
    """
    job_id = ctx['job_id']

    def _sync_impl():
        file_path = None
        try:
            from fastapi_app.shared.report_data_service import get_all_logs_data
            from utils.report_exporter import ReportExporter
            session = _SyncSession()
            try:
                customer = filters.get('customer', '')
                product = filters.get('product', '')
                status = filters.get('status', '')
                start_date = filters.get('start_date', '')
                end_date = filters.get('end_date', '')
                # 工厂隔离：入队端按操作者注入，任务端透传（Round16，与同步导出同口径）
                factory = filters.get('factory', '')
                logs, stats = get_all_logs_data(session, report_type, customer=customer, product=product, status=status, start_date=start_date, end_date=end_date, factory=factory)
                # 超限判定用 stats 的 total_count（统计查询无行数上限）：明细查询在
                # _MAX_EXPORT_ROWS 截断，len(logs) 恒 ≤10000，`len(logs) > 10000`
                # 永不触发（Round16：fail-closed 原是死代码，超量被静默截成 10000 行）
                total_count = int(stats.get('total_count', 0) or 0)
                # 第十轮审计：原「先全量读入内存 → 截断 10000」，截断发生在内存峰值之后，
                # 防不住超量导出撑爆 worker；且静默截断让用户拿到不完整报表而不自知。
                # 改为 fail-closed：超限直接失败并引导缩小范围（与 export_limits 门禁同语义）。
                if total_count > 10000:
                    return {'success': False, 'error': f'报表数据量过大（{total_count} 行，上限 10000），请缩小筛选范围后重新导出', 'task_id': job_id}
                exporter = ReportExporter()
                method_name = _EXPORT_METHODS.get(report_type)
                if not method_name:
                    return {'success': False, 'error': f'不支持的报表类型: {report_type}', 'task_id': job_id}
                export_func = getattr(exporter, method_name)
                output_buffer = export_func(logs)
                import uuid
                filename = f'{report_type}_report_{uuid.uuid4().hex[:8]}.xlsx'
                file_path = os.path.join(tempfile.gettempdir(), filename)
                with open(file_path, 'wb') as f:
                    # 导出器真实返回 bytes（utils/report_exporter._save_workbook 返回 getvalue()），仅 BytesIO 需要 getvalue()
                    f.write(output_buffer if isinstance(output_buffer, bytes) else output_buffer.getvalue())
                return {'success': True, 'file_path': file_path, 'filename': filename, 'row_count': len(logs), 'total_count': total_count, 'task_id': job_id}
            finally:
                session.close()
        except (ValueError, OSError, RuntimeError) as exc:
            if file_path and os.path.exists(file_path):
                with contextlib.suppress(OSError):
                    os.unlink(file_path)
            logger.error(f'报表导出任务失败: {exc}', exc_info=True)
            raise exc

    return await asyncio.to_thread(_sync_impl)
