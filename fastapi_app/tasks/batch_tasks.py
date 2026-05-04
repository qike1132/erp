"""
批量导入异步任务

将 Excel 批量导入等耗时操作放入 Celery Worker 执行。
已去除 Flask create_app 依赖，使用 SyncSessionLocal + shared_models。
"""
import contextlib
import os
import tempfile

from celery import shared_task

from fastapi_app.core.database import SyncSessionLocal
from fastapi_app.core.logger import logger


@shared_task(bind=True, name='batch_import_orders', queue='batch', max_retries=2, default_retry_delay=30, soft_time_limit=300, time_limit=600)
def batch_import_orders_task(self, file_path: str, original_filename: str, user_id: int):
    """异步批量导入订单

    Args:
        file_path: 已保存的临时文件路径
        original_filename: 原始文件名
        user_id: 操作用户ID

    Returns:
        dict: 导入结果 {success, imported_count, errors, task_id}
    """
    allowed_dirs = [tempfile.gettempdir(), os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), 'static', 'uploads')]
    real_path = os.path.realpath(file_path)
    if not any(os.path.commonpath([real_path, d]) == d for d in allowed_dirs if os.path.exists(d)):
        logger.error(f'批量导入订单任务拒绝非法文件路径: {file_path}')
        return {'success': False, 'error': '非法文件路径', 'imported_count': 0, 'task_id': self.request.id}
    try:
        from datetime import datetime

        from sqlalchemy import or_
        from sqlalchemy import select as sa_select

        from fastapi_app.shared.stock_crud_service import generate_order_number_sync
        from fastapi_app.shared_models import InventoryLog, Order, Product
        from utils.batch_upload_utils import parse_excel_file
        success, data_list, error = parse_excel_file(file_path)
        if not success:
            return {'success': False, 'error': error, 'imported_count': 0, 'task_id': self.request.id}
        session = SyncSessionLocal()
        try:
            imported_count = 0
            errors = []
            BATCH_COMMIT_SIZE = 50
            for i, row in enumerate(data_list, start=2):
                try:
                    product_identifier = row.get('产品名称', row.get('产品编号', ''))
                    customer = row.get('客户名称', '')
                    quantity = row.get('数量', 0)
                    if not all([product_identifier, customer, quantity]):
                        errors.append({'row': i, 'error': '缺少必填字段'})
                        continue
                    product = session.execute(sa_select(Product).where(or_(Product.name == product_identifier, Product.barcode == product_identifier)).with_for_update()).scalar_one_or_none()
                    if not product:
                        errors.append({'row': i, 'error': f"产品 '{product_identifier}' 不存在"})
                        continue
                    order = Order(order_no=generate_order_number_sync(session), product_id=product.id, customer=customer, quantity=int(quantity), order_date=datetime.now(), status='待备货', note=row.get('备注', ''))
                    session.add(order)
                    session.flush()
                    product.current_stock += int(quantity)
                    log = InventoryLog(product_id=product.id, change_type='订单创建', change_quantity=int(quantity), change_date=datetime.now(), customer=customer, related_id=str(order.id), note=f'批量导入订单 {order.order_no}')
                    session.add(log)
                    imported_count += 1
                    if imported_count % BATCH_COMMIT_SIZE == 0:
                        session.commit()
                except (ValueError, TypeError, OSError) as e:
                    session.rollback()
                    errors.append({'row': i, 'error': str(e)})
                    logger.error(f'批量导入订单行{i}失败: {e}')
            session.commit()
            return {'success': True, 'imported_count': imported_count, 'errors': errors, 'task_id': self.request.id}
        finally:
            session.close()
    except (ValueError, TypeError, OSError) as exc:
        logger.error(f'批量导入订单任务失败: {exc}', exc_info=True)
        if self.request.retries < self.max_retries:
            raise self.retry(exc=exc) from exc
        if file_path and os.path.exists(file_path):
            with contextlib.suppress(OSError):
                os.unlink(file_path)
        raise
    if file_path and os.path.exists(file_path):
        with contextlib.suppress(OSError):
            os.unlink(file_path)

@shared_task(bind=True, name='batch_import_stockins', queue='batch', max_retries=2, default_retry_delay=30, soft_time_limit=300, time_limit=600)
def batch_import_stockins_task(self, file_path: str, original_filename: str, user_id: int):
    """异步批量导入备货"""
    allowed_dirs = [tempfile.gettempdir(), os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), 'static', 'uploads')]
    real_path = os.path.realpath(file_path)
    if not any(os.path.commonpath([real_path, d]) == d for d in allowed_dirs if os.path.exists(d)):
        logger.error(f'批量导入备货任务拒绝非法文件路径: {file_path}')
        return {'success': False, 'error': '非法文件路径', 'imported_count': 0, 'task_id': self.request.id}
    try:
        from datetime import datetime

        from sqlalchemy import or_
        from sqlalchemy import select as sa_select

        from fastapi_app.shared.stock_crud_service import generate_stockin_number_sync
        from fastapi_app.shared_models import InventoryLog, Product, StockIn
        from utils.batch_upload_utils import parse_excel_file
        success, data_list, error = parse_excel_file(file_path)
        if not success:
            return {'success': False, 'error': error, 'imported_count': 0, 'task_id': self.request.id}
        session = SyncSessionLocal()
        try:
            imported_count = 0
            errors = []
            BATCH_COMMIT_SIZE = 50
            for i, row in enumerate(data_list, start=2):
                try:
                    product_identifier = row.get('产品名称', row.get('产品编号', ''))
                    customer = row.get('客户名称', '')
                    quantity = row.get('数量', 0)
                    if not all([product_identifier, customer, quantity]):
                        errors.append({'row': i, 'error': '缺少必填字段'})
                        continue
                    product = session.execute(sa_select(Product).where(or_(Product.name == product_identifier, Product.barcode == product_identifier)).with_for_update()).scalar_one_or_none()
                    if not product:
                        errors.append({'row': i, 'error': f"产品 '{product_identifier}' 不存在"})
                        continue
                    stockin = StockIn(stockin_no=generate_stockin_number_sync(session), product_id=product.id, customer=customer, quantity=int(quantity), stockin_date=datetime.now(), note=row.get('备注', ''))
                    session.add(stockin)
                    session.flush()
                    product.current_stock += int(quantity)
                    log = InventoryLog(product_id=product.id, change_type='备货入库', change_quantity=int(quantity), change_date=datetime.now(), customer=customer, related_id=str(stockin.id), note=f'批量导入备货 {stockin.stockin_no}')
                    session.add(log)
                    imported_count += 1
                    if imported_count % BATCH_COMMIT_SIZE == 0:
                        session.commit()
                except (ValueError, TypeError, OSError) as e:
                    session.rollback()
                    errors.append({'row': i, 'error': str(e)})
            session.commit()
            return {'success': True, 'imported_count': imported_count, 'errors': errors, 'task_id': self.request.id}
        finally:
            session.close()
    except (ValueError, TypeError, OSError) as exc:
        logger.error(f'批量导入备货任务失败: {exc}', exc_info=True)
        if self.request.retries < self.max_retries:
            raise self.retry(exc=exc) from exc
        if file_path and os.path.exists(file_path):
            with contextlib.suppress(OSError):
                os.unlink(file_path)
        raise
    if file_path and os.path.exists(file_path):
        with contextlib.suppress(OSError):
            os.unlink(file_path)
