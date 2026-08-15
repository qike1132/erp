"""
批量导入异步任务

将 Excel 批量导入等耗时操作放入 ARQ Worker 执行。
任务内部使用同步数据库会话（历史实现），通过 asyncio.to_thread 在 ARQ 的
async 事件循环中运行，避免阻塞 worker。
"""
import asyncio
import contextlib
import os
import tempfile

from sqlalchemy import or_, select as sa_select

from fastapi_app.core.database import get_sync_engine
from fastapi_app.core.logger import logger
from fastapi_app.shared_models import Product
from sqlalchemy.orm import Session, sessionmaker

_SyncSession = sessionmaker(
    autocommit=False, autoflush=False, bind=get_sync_engine()
)


ALLOWED_UPLOAD_DIRS = [
    tempfile.gettempdir(),
    os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), 'static', 'uploads'),
]


def _is_allowed_upload_path(file_path: str) -> bool:
    """校验上传文件路径是否位于允许的目录内。"""
    real_path = os.path.realpath(file_path)
    return any(os.path.commonpath([real_path, d]) == d for d in ALLOWED_UPLOAD_DIRS if os.path.exists(d))


def _resolve_product_locked(session: Session, product_identifier: str) -> Product | None:
    """按名称/条码查找产品并加行锁，未找到返回 None。"""
    return session.execute(
        sa_select(Product).where(
            or_(Product.name == product_identifier, Product.barcode == product_identifier)
        ).with_for_update()
    ).scalar_one_or_none()


async def batch_import_orders_task(ctx, file_path: str, original_filename: str, user_id: int):
    """异步批量导入订单

    Args:
        ctx: ARQ 上下文（含 job_id / job_try）
        file_path: 已保存的临时文件路径
        original_filename: 原始文件名
        user_id: 操作用户ID

    Returns:
        dict: 导入结果 {success, imported_count, errors, task_id}
    """
    job_id = ctx['job_id']

    def _sync_impl():
        allowed_dirs = ALLOWED_UPLOAD_DIRS
        real_path = os.path.realpath(file_path)
        if not any(os.path.commonpath([real_path, d]) == d for d in allowed_dirs if os.path.exists(d)):
            logger.error(f'批量导入订单任务拒绝非法文件路径: {file_path}')
            return {'success': False, 'error': '非法文件路径', 'imported_count': 0, 'task_id': job_id}
        delete_file = True
        try:
            from datetime import datetime

            from fastapi_app.shared.stock_crud_service import generate_order_number_sync
            from fastapi_app.shared_models import InventoryLog, Order
            from utils.batch_upload_utils import parse_excel_file
            success, data_list, error = parse_excel_file(file_path)
            if not success:
                return {'success': False, 'error': error, 'imported_count': 0, 'task_id': job_id}
            session: Session = _SyncSession()
            try:
                imported_count = 0
                last_committed_count = 0
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
                        product = _resolve_product_locked(session, product_identifier)
                        if not product:
                            errors.append({'row': i, 'error': f"产品 '{product_identifier}' 不存在"})
                            continue
                        order = Order(order_no=generate_order_number_sync(session), product_id=product.id, customer=customer, quantity=int(quantity), order_date=datetime.now(), status='待备货', note=row.get('备注', ''))
                        session.add(order)
                        session.flush()
                        log = InventoryLog(product_id=product.id, change_type='订单创建', change_quantity=int(quantity), change_date=datetime.now(), customer=customer, related_id=str(order.id), note=f'批量导入订单 {order.order_no}')
                        session.add(log)
                        imported_count += 1
                        if imported_count % BATCH_COMMIT_SIZE == 0:
                            session.commit()
                            last_committed_count = imported_count
                    except (ValueError, TypeError, OSError) as e:
                        session.rollback()
                        # 保留已提交批次的计数，仅回滚当前未提交批次
                        uncommitted_in_batch = imported_count - last_committed_count
                        imported_count = last_committed_count
                        errors.append({'row': i, 'error': str(e), 'skipped_uncommitted': uncommitted_in_batch})
                        logger.error(f'批量导入订单行{i}失败: {e}')
                session.commit()
                return {'success': True, 'imported_count': imported_count, 'errors': errors, 'task_id': job_id}
            finally:
                session.close()
        except (ValueError, TypeError, OSError) as exc:
            logger.error(f'批量导入订单任务失败: {exc}', exc_info=True)
            # 保留文件以供 ARQ 重试（max_tries 控制重试上限）
            delete_file = False
            raise exc
        finally:
            if delete_file and file_path and os.path.exists(file_path):
                with contextlib.suppress(OSError):
                    os.unlink(file_path)

    return await asyncio.to_thread(_sync_impl)


async def batch_import_stockins_task(ctx, file_path: str, original_filename: str, user_id: int):
    """异步批量导入备货"""
    job_id = ctx['job_id']

    def _sync_impl():
        allowed_dirs = ALLOWED_UPLOAD_DIRS
        real_path = os.path.realpath(file_path)
        if not any(os.path.commonpath([real_path, d]) == d for d in allowed_dirs if os.path.exists(d)):
            logger.error(f'批量导入备货任务拒绝非法文件路径: {file_path}')
            return {'success': False, 'error': '非法文件路径', 'imported_count': 0, 'task_id': job_id}
        delete_file = True
        try:
            from datetime import datetime

            from fastapi_app.shared.stock_crud_service import generate_stockin_number_sync
            from fastapi_app.shared_models import InventoryLog, StockIn
            from utils.batch_upload_utils import parse_excel_file
            success, data_list, error = parse_excel_file(file_path)
            if not success:
                return {'success': False, 'error': error, 'imported_count': 0, 'task_id': job_id}
            session: Session = _SyncSession()
            try:
                imported_count = 0
                last_committed_count = 0
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
                        product = _resolve_product_locked(session, product_identifier)
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
                            last_committed_count = imported_count
                    except (ValueError, TypeError, OSError) as e:
                        session.rollback()
                        imported_count = last_committed_count
                        errors.append({'row': i, 'error': str(e)})
                session.commit()
                return {'success': True, 'imported_count': imported_count, 'errors': errors, 'task_id': job_id}
            finally:
                session.close()
        except (ValueError, TypeError, OSError) as exc:
            logger.error(f'批量导入备货任务失败: {exc}', exc_info=True)
            # 保留文件以供 ARQ 重试
            delete_file = False
            raise exc
        finally:
            if delete_file and file_path and os.path.exists(file_path):
                with contextlib.suppress(OSError):
                    os.unlink(file_path)

    return await asyncio.to_thread(_sync_impl)
