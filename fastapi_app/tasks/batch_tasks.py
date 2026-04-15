"""
批量导入异步任务
将 Excel 批量导入等耗时操作放入 Celery Worker 执行
"""
import os
import tempfile
from celery import shared_task
from fastapi_app.core.celery_app import celery_app
from fastapi_app.core.logger import logger


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
    try:
        from utils.batch_upload_utils import parse_excel_file, batch_save_with_transaction
        from app import db
        from app.models import Product, Order, InventoryLog
        from app import create_app

        # 在 Worker 进程中创建 Flask 应用上下文（用于同步DB操作）
        app = create_app()
        with app.app_context():
            success, data_list, error = parse_excel_file(file_path)
            if not success:
                return {"success": False, "error": error, "imported_count": 0, "task_id": self.request.id}

            results = []
            imported_count = 0
            errors = []

            for i, row in enumerate(data_list, start=2):
                try:
                    product_identifier = row.get("产品名称", row.get("产品编号", ""))
                    customer = row.get("客户名称", "")
                    quantity = row.get("数量", 0)

                    if not all([product_identifier, customer, quantity]):
                        errors.append({"row": i, "error": "缺少必填字段"})
                        continue

                    from utils.number_generator import generate_order_number
                    from datetime import datetime

                    product = Product.query.filter(
                        (Product.name == product_identifier) | (Product.barcode == product_identifier)
                    ).first()

                    if not product:
                        errors.append({"row": i, "error": f"产品 '{product_identifier}' 不存在"})
                        continue

                    order = Order(
                        order_no=generate_order_number(db, Order),
                        product_id=product.id,
                        customer=customer,
                        quantity=int(quantity),
                        order_date=datetime.now(),
                        status="待备货",
                        note=row.get("备注", ""),
                    )
                    db.session.add(order)
                    db.session.flush()
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
                    db.session.add(log)
                    imported_count += 1

                except Exception as e:
                    errors.append({"row": i, "error": str(e)})
                    logger.error(f"批量导入订单行{i}失败: {e}")

            db.session.commit()

            return {
                "success": True,
                "imported_count": imported_count,
                "errors": errors,
                "task_id": self.request.id,
            }

    except Exception as exc:
        logger.error(f"批量导入订单任务失败: {exc}", exc_info=True)
        raise self.retry(exc=exc)

    finally:
        # 清理临时文件
        if file_path and os.path.exists(file_path):
            os.unlink(file_path)


@shared_task(
    bind=True,
    name="batch_import_stockins",
    queue="batch",
    max_retries=2,
    default_retry_delay=30,
)
def batch_import_stockins_task(self, file_path: str, original_filename: str, user_id: int):
    """异步批量导入备货"""
    try:
        from utils.batch_upload_utils import parse_excel_file
        from app import db
        from app.models import Product, StockIn, InventoryLog
        from app import create_app

        app = create_app()
        with app.app_context():
            success, data_list, error = parse_excel_file(file_path)
            if not success:
                return {"success": False, "error": error, "imported_count": 0, "task_id": self.request.id}

            imported_count = 0
            errors = []

            for i, row in enumerate(data_list, start=2):
                try:
                    product_identifier = row.get("产品名称", row.get("产品编号", ""))
                    customer = row.get("客户名称", "")
                    quantity = row.get("数量", 0)

                    if not all([product_identifier, customer, quantity]):
                        errors.append({"row": i, "error": "缺少必填字段"})
                        continue

                    from utils.number_generator import generate_stockin_number
                    from datetime import datetime

                    product = Product.query.filter(
                        (Product.name == product_identifier) | (Product.barcode == product_identifier)
                    ).first()

                    if not product:
                        errors.append({"row": i, "error": f"产品 '{product_identifier}' 不存在"})
                        continue

                    stockin = StockIn(
                        stockin_no=generate_stockin_number(db, StockIn),
                        product_id=product.id,
                        customer=customer,
                        quantity=int(quantity),
                        stockin_date=datetime.now(),
                        note=row.get("备注", ""),
                    )
                    db.session.add(stockin)
                    db.session.flush()
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
                    db.session.add(log)
                    imported_count += 1

                except Exception as e:
                    errors.append({"row": i, "error": str(e)})

            db.session.commit()

            return {
                "success": True,
                "imported_count": imported_count,
                "errors": errors,
                "task_id": self.request.id,
            }

    except Exception as exc:
        logger.error(f"批量导入备货任务失败: {exc}", exc_info=True)
        raise self.retry(exc=exc)

    finally:
        if file_path and os.path.exists(file_path):
            os.unlink(file_path)
