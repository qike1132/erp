"""
批量导入异步任务

将 Excel 批量导入等耗时操作放入 Celery Worker 执行。
已去除 Flask create_app 依赖，使用 SyncSessionLocal + shared_models。
"""
import os
import tempfile
from celery import shared_task
from fastapi_app.core.celery_app import celery_app
from fastapi_app.core.logger import logger
from fastapi_app.core.database import SyncSessionLocal


@shared_task(
    bind=True,
    name="batch_import_orders",
    queue="batch",
    max_retries=2,
    default_retry_delay=30,
)
def batch_import_orders_task(self, file_path: str, original_filename: str, user_id: int):
    """异步批量导入订单

    Args:
        file_path: 已保存的临时文件路径
        original_filename: 原始文件名
        user_id: 操作用户ID

    Returns:
        dict: 导入结果 {success, imported_count, errors, task_id}
    """
    # 安全校验：文件路径必须在临时目录内，防止路径遍历
    allowed_dirs = [tempfile.gettempdir(), os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), 'static', 'uploads')]
    real_path = os.path.realpath(file_path)
    if not any(os.path.commonpath([real_path, d]) == d for d in allowed_dirs if os.path.exists(d)):
        logger.error(f"批量导入订单任务拒绝非法文件路径: {file_path}")
        return {"success": False, "error": "非法文件路径", "imported_count": 0, "task_id": self.request.id}

    try:
        from utils.batch_upload_utils import parse_excel_file
        from fastapi_app.shared_models import Product, Order, InventoryLog
        from fastapi_app.shared.stock_crud_service import (
            generate_order_number_sync,
            get_product_for_update_sync,
        )
        from datetime import datetime
        from sqlalchemy import or_, select as sa_select

        success, data_list, error = parse_excel_file(file_path)
        if not success:
            return {"success": False, "error": error, "imported_count": 0, "task_id": self.request.id}

        session = SyncSessionLocal()
        try:
            results = []
            imported_count = 0
            errors = []
            BATCH_COMMIT_SIZE = 50  # 每50行提交一次，释放行级锁

            for i, row in enumerate(data_list, start=2):
                try:
                    product_identifier = row.get("产品名称", row.get("产品编号", ""))
                    customer = row.get("客户名称", "")
                    quantity = row.get("数量", 0)

                    if not all([product_identifier, customer, quantity]):
                        errors.append({"row": i, "error": "缺少必填字段"})
                        continue

                    product = session.execute(
                        sa_select(Product).where(
                            or_(Product.name == product_identifier, Product.barcode == product_identifier)
                        ).with_for_update()
                    ).scalar_one_or_none()

                    if not product:
                        errors.append({"row": i, "error": f"产品 '{product_identifier}' 不存在"})
                        continue

                    order = Order(
                        order_no=generate_order_number_sync(session),
                        product_id=product.id,
                        customer=customer,
                        quantity=int(quantity),
                        order_date=datetime.now(),
                        status="待备货",
                        note=row.get("备注", ""),
                    )
                    session.add(order)
                    session.flush()
                    product.current_stock += int(quantity)

                    log = InventoryLog(
                        product_id=product.id,
                        change_type="订单创建",
                        change_quantity=int(quantity),
                        change_date=datetime.now(),
                        customer=customer,
                        related_id=str(order.id),
                        note=f"批量导入订单 {order.order_no}",
                    )
                    session.add(log)
                    imported_count += 1

                    # 分批提交，避免大量行级锁同时持有
                    if imported_count % BATCH_COMMIT_SIZE == 0:
                        session.commit()

                except (ValueError, TypeError, OSError) as e:
                    session.rollback()
                    errors.append({"row": i, "error": str(e)})
                    logger.error(f"批量导入订单行{i}失败: {e}")

            session.commit()

            return {
                "success": True,
                "imported_count": imported_count,
                "errors": errors,
                "task_id": self.request.id,
            }

        finally:
            session.close()

    except (ValueError, TypeError, OSError) as exc:
        logger.error(f"批量导入订单任务失败: {exc}", exc_info=True)
        if self.request.retries < self.max_retries:
            # 仍有重试机会，保留文件供下次使用
            raise self.retry(exc=exc)
        # 重试已耗尽，清理临时文件防止永久泄漏
        if file_path and os.path.exists(file_path):
            try:
                os.unlink(file_path)
            except OSError:
                pass
        raise

    # 不再自动同步采购中心：订单应先进入"审核订单"队列，由人工审核后再生成采购订单
    # 旧逻辑：批量导入后自动调用 one_click_generate_order 生成采购订单
    # 这会导致有 BOM 的订单直接跳过审核步骤

    # 仅在任务最终成功时清理临时文件（Retry异常不会到达此处）
    if file_path and os.path.exists(file_path):
        try:
            os.unlink(file_path)
        except OSError:
            pass


@shared_task(
    bind=True,
    name="batch_import_stockins",
    queue="batch",
    max_retries=2,
    default_retry_delay=30,
)
def batch_import_stockins_task(self, file_path: str, original_filename: str, user_id: int):
    """异步批量导入备货"""
    # 安全校验：文件路径必须在临时目录内
    allowed_dirs = [tempfile.gettempdir(), os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), 'static', 'uploads')]
    real_path = os.path.realpath(file_path)
    if not any(os.path.commonpath([real_path, d]) == d for d in allowed_dirs if os.path.exists(d)):
        logger.error(f"批量导入备货任务拒绝非法文件路径: {file_path}")
        return {"success": False, "error": "非法文件路径", "imported_count": 0, "task_id": self.request.id}

    try:
        from utils.batch_upload_utils import parse_excel_file
        from fastapi_app.shared_models import Product, StockIn, InventoryLog
        from fastapi_app.shared.stock_crud_service import (
            generate_stockin_number_sync,
            get_product_for_update_sync,
        )
        from datetime import datetime
        from sqlalchemy import or_, select as sa_select

        success, data_list, error = parse_excel_file(file_path)
        if not success:
            return {"success": False, "error": error, "imported_count": 0, "task_id": self.request.id}

        session = SyncSessionLocal()
        try:
            imported_count = 0
            errors = []
            BATCH_COMMIT_SIZE = 50  # 每50行提交一次，释放行级锁

            for i, row in enumerate(data_list, start=2):
                try:
                    product_identifier = row.get("产品名称", row.get("产品编号", ""))
                    customer = row.get("客户名称", "")
                    quantity = row.get("数量", 0)

                    if not all([product_identifier, customer, quantity]):
                        errors.append({"row": i, "error": "缺少必填字段"})
                        continue

                    product = session.execute(
                        sa_select(Product).where(
                            or_(Product.name == product_identifier, Product.barcode == product_identifier)
                        ).with_for_update()
                    ).scalar_one_or_none()

                    if not product:
                        errors.append({"row": i, "error": f"产品 '{product_identifier}' 不存在"})
                        continue

                    stockin = StockIn(
                        stockin_no=generate_stockin_number_sync(session),
                        product_id=product.id,
                        customer=customer,
                        quantity=int(quantity),
                        stockin_date=datetime.now(),
                        note=row.get("备注", ""),
                    )
                    session.add(stockin)
                    session.flush()
                    product.current_stock += int(quantity)

                    log = InventoryLog(
                        product_id=product.id,
                        change_type="备货入库",
                        change_quantity=int(quantity),
                        change_date=datetime.now(),
                        customer=customer,
                        related_id=str(stockin.id),
                        note=f"批量导入备货 {stockin.stockin_no}",
                    )
                    session.add(log)
                    imported_count += 1

                    # 分批提交，避免大量行级锁同时持有
                    if imported_count % BATCH_COMMIT_SIZE == 0:
                        session.commit()

                except (ValueError, TypeError, OSError) as e:
                    session.rollback()
                    errors.append({"row": i, "error": str(e)})

            session.commit()

            return {
                "success": True,
                "imported_count": imported_count,
                "errors": errors,
                "task_id": self.request.id,
            }

        finally:
            session.close()

    except (ValueError, TypeError, OSError) as exc:
        logger.error(f"批量导入备货任务失败: {exc}", exc_info=True)
        if self.request.retries < self.max_retries:
            raise self.retry(exc=exc)
        if file_path and os.path.exists(file_path):
            try:
                os.unlink(file_path)
            except OSError:
                pass
        raise

    # 仅在任务最终成功时清理临时文件（Retry异常不会到达此处）
    if file_path and os.path.exists(file_path):
        try:
            os.unlink(file_path)
        except OSError:
            pass
