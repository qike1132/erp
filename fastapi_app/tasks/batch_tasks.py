"""批量导入异步任务

Excel 批量导入耗时操作由 ARQ Worker 执行。行循环使用异步会话
（numbering_counter 原子取号，spec 2026-09-29 订单号统一 §4.2）。
"""
import contextlib
import os
import tempfile

from sqlalchemy import or_
from sqlalchemy import select as sa_select

from fastapi_app.core.logger import logger
from fastapi_app.shared_models import Product
from fastapi_app.shared_models.order import ORDER_STATUS_PENDING_STOCK

ALLOWED_UPLOAD_DIRS = [
    tempfile.gettempdir(),
    os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), 'static', 'uploads'),
]


def _is_allowed_upload_path(file_path: str) -> bool:
    """校验上传文件路径是否位于允许的目录内。

    两侧均取 ``realpath``：Windows 下 ``tempfile.gettempdir()`` 可能返回 8.3 短名
    （如 ``C:\\Users\\ADMINI~1\\...``），而 ``realpath(file_path)`` 会展开为长名，
    不归一会导致本应命中的临时目录被判为不匹配。跨盘符时 ``os.path.commonpath``
    抛 ``ValueError``，按"不在该目录内"处理并继续检查下一个候选目录。
    """
    real_path = os.path.realpath(file_path)
    for d in ALLOWED_UPLOAD_DIRS:
        if not os.path.exists(d):
            continue
        real_dir = os.path.realpath(d)
        try:
            if os.path.commonpath([real_path, real_dir]) == real_dir:
                return True
        except ValueError:
            # 跨盘符：commonpath 拒绝混合 drive，视为不在该目录内
            continue
    return False


async def _parse_rows_async(file_path: str) -> tuple[bool, list, str]:
    """解析 Excel（阻塞解析仍在 executor 里跑，不阻塞 worker 事件循环）。"""
    from fastapi_app.services.batch_import_parser import parse_excel_file_async

    return await parse_excel_file_async(file_path)


async def _open_import_session():
    """开启异步导入会话（延迟导入，避免 import 期绑定引擎）。"""
    from fastapi_app.core.database import require_async_session_local

    return require_async_session_local()()


async def _resolve_product_locked(db, product_identifier: str) -> Product | None:
    """按名称/条码查找产品并加行锁，未找到返回 None。"""
    result = await db.execute(
        sa_select(Product).where(
            or_(Product.name == product_identifier, Product.barcode == product_identifier)
        ).with_for_update()
    )
    return result.scalar_one_or_none()


async def _resolve_row_product(db, row: dict) -> tuple[Product | None, str | None]:
    """解析行内产品标识并加行锁；返回 (product, 错误消息)。缺少必填字段/产品不存在返回错误消息。"""
    product_identifier = row.get('产品名称', row.get('产品编号', ''))
    customer = row.get('客户名称', '')
    quantity = row.get('数量', 0)
    if not all([product_identifier, customer, quantity]):
        return None, '缺少必填字段'
    product = await _resolve_product_locked(db, product_identifier)
    if not product:
        return None, f"产品 '{product_identifier}' 不存在"
    return product, None


async def _run_batch_import_async(file_path: str, job_id: str, task_label: str, build_row) -> dict:
    """订单/备货批量导入共享骨架（异步版）。

    语义与同步版逐字一致（50 行一批提交 / 行级失败 continue /
    ValueError/TypeError/OSError 回滚当前未提交批并计 skipped_uncommitted /
    抛出时保留文件供重试）。

    Args:
        file_path: 已保存的临时文件路径。
        job_id: ARQ 任务 ID。
        task_label: 任务标签（日志用，如 '订单'/'备货'）。
        build_row: 单行处理协程 ``async def(db, row, i) -> str | None``。

    Returns:
        dict: {success, imported_count, errors, task_id}
    """
    if not _is_allowed_upload_path(file_path):
        logger.error(f'批量导入{task_label}任务拒绝非法文件路径: {file_path}')
        return {'success': False, 'error': '非法文件路径', 'imported_count': 0, 'task_id': job_id}
    delete_file = True
    try:
        success, data_list, error = await _parse_rows_async(file_path)
        if not success:
            return {'success': False, 'error': error, 'imported_count': 0, 'task_id': job_id}
        db = await _open_import_session()
        try:
            imported_count = 0
            last_committed_count = 0
            errors = []
            BATCH_COMMIT_SIZE = 50
            for i, row in enumerate(data_list, start=2):
                try:
                    row_error = await build_row(db, row, i)
                except (ValueError, TypeError, OSError) as e:
                    await db.rollback()
                    # 保留已提交批次的计数，仅回滚当前未提交批次
                    uncommitted_in_batch = imported_count - last_committed_count
                    imported_count = last_committed_count
                    errors.append({'row': i, 'error': str(e), 'skipped_uncommitted': uncommitted_in_batch})
                    logger.error(f'批量导入{task_label}行{i}失败: {e}')
                    continue
                if row_error:
                    errors.append({'row': i, 'error': row_error})
                    continue
                imported_count += 1
                if imported_count % BATCH_COMMIT_SIZE == 0:
                    await db.commit()
                    last_committed_count = imported_count
            await db.commit()
            return {'success': True, 'imported_count': imported_count, 'errors': errors, 'task_id': job_id}
        finally:
            await db.close()
    except (ValueError, TypeError, OSError) as exc:
        logger.error(f'批量导入{task_label}任务失败: {exc}', exc_info=True)
        # 保留文件以供 ARQ 重试（max_tries 控制重试上限）
        delete_file = False
        raise exc
    finally:
        if delete_file and file_path and os.path.exists(file_path):
            with contextlib.suppress(OSError):
                os.unlink(file_path)


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

    async def _orders_row(db, row: dict, i: int) -> str | None:
        from datetime import UTC, datetime

        from fastapi_app.services.numbering import generate_order_number
        from fastapi_app.shared_models import InventoryLog, Order
        product, row_error = await _resolve_row_product(db, row)
        if row_error:
            return row_error
        order = Order(
            order_no=await generate_order_number(db),
            product_id=product.id, customer=row.get('客户名称', ''),
            quantity=int(row.get('数量', 0)),
            order_date=datetime.now(UTC),  # aware UTC：order_date 为 timestamptz
            status=ORDER_STATUS_PENDING_STOCK, note=row.get('备注', ''))
        db.add(order)
        await db.flush()
        log = InventoryLog(product_id=product.id, change_type='订单创建',
                           change_quantity=int(row.get('数量', 0)),
                           change_date=datetime.now(UTC), customer=row.get('客户名称', ''),
                           related_id=str(order.id), note=f'批量导入订单 {order.order_no}')
        db.add(log)
        return None

    return await _run_batch_import_async(file_path, job_id, '订单', _orders_row)


async def batch_import_stockins_task(ctx, file_path: str, original_filename: str, user_id: int):
    """异步批量导入备货"""
    job_id = ctx['job_id']

    async def _stockins_row(db, row: dict, i: int) -> str | None:
        from datetime import UTC, datetime

        from fastapi_app.services.numbering import generate_stockin_number
        from fastapi_app.shared_models import InventoryLog, StockIn
        product, row_error = await _resolve_row_product(db, row)
        if row_error:
            return row_error
        quantity = int(row.get('数量', 0))
        stockin = StockIn(
            stockin_no=await generate_stockin_number(db),
            product_id=product.id, customer=row.get('客户名称', ''),
            quantity=quantity, stockin_date=datetime.now(UTC),
            note=row.get('备注', ''))
        db.add(stockin)
        await db.flush()
        product.current_stock += quantity
        log = InventoryLog(product_id=product.id, change_type='备货入库',
                           change_quantity=quantity, change_date=datetime.now(UTC),
                           customer=row.get('客户名称', ''), related_id=str(stockin.id),
                           note=f'批量导入备货 {stockin.stockin_no}')
        db.add(log)
        return None

    return await _run_batch_import_async(file_path, job_id, '备货', _stockins_row)
