"""
报表导出异步任务
将耗时报表生成放入 Celery Worker 执行
"""
import os
import tempfile

from celery import shared_task

from fastapi_app.core.logger import logger


@shared_task(bind=True, name='export_report', queue='reports', max_retries=1, default_retry_delay=60)
def export_report_task(self, report_type: str, filters: dict, user_id: int):
    """异步导出报表

    Args:
        report_type: 报表类型 (order/stockin/stockout/deduction)
        filters: 筛选条件 {customer, product, status, start_date, end_date}
        user_id: 操作用户ID

    Returns:
        dict: 导出结果 {success, file_path, filename, row_count, task_id}
    """
    try:
        from fastapi_app.core.database import SyncSessionLocal
        from fastapi_app.shared.report_data_service import get_all_logs_data
        from utils.report_exporter import ReportExporter
        session = SyncSessionLocal()
        try:
            customer = filters.get('customer', '')
            product = filters.get('product', '')
            status = filters.get('status', '')
            start_date = filters.get('start_date', '')
            end_date = filters.get('end_date', '')
            logs, stats = get_all_logs_data(session, report_type, customer=customer, product=product, status=status, start_date=start_date, end_date=end_date)
            if len(logs) > 10000:
                logs = logs[:10000]
            exporter = ReportExporter()
            export_methods = {'order': exporter.export_order_logs, 'stockin': exporter.export_stockin_logs, 'stockout': exporter.export_stockout_logs, 'deduction': exporter.export_deduction_logs}
            export_func = export_methods.get(report_type)
            if not export_func:
                return {'success': False, 'error': f'不支持的报表类型: {report_type}', 'task_id': self.request.id}
            output_buffer = export_func(logs, stats)
            import uuid
            filename = f'{report_type}_report_{uuid.uuid4().hex[:8]}.xlsx'
            file_path = os.path.join(tempfile.gettempdir(), filename)
            with open(file_path, 'wb') as f:
                f.write(output_buffer.getvalue())
            return {'success': True, 'file_path': file_path, 'filename': filename, 'row_count': len(logs), 'task_id': self.request.id}
        finally:
            session.close()
    except (ValueError, OSError, RuntimeError) as exc:
        logger.error(f'报表导出任务失败: {exc}', exc_info=True)
        raise self.retry(exc=exc) from exc
