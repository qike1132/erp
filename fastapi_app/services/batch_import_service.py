"""
批量 Excel 导入业务逻辑服务

从 batch_service.py 提取的核心导入逻辑，适配异步 SQLAlchemy。
包含通用导入框架、产品/订单/备货/出货导入函数及文件解析辅助。

本文件已拆分为：
- batch_import_parser.py：Excel 解析 + 文件工具（无业务依赖）
- batch_import_core.py：通用导入框架 + 各 from_data 导入函数

本文件保留全部 12 个端点级 service 函数，并在文件末尾 re-export
被迁移的函数名，以保持 from fastapi_app.services.batch_import_service import X 兼容。
"""
import asyncio
import logging
import os
from collections.abc import Callable
from datetime import datetime

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from fastapi_app.core.exceptions import BusinessError, NotFoundError
from fastapi_app.schemas.batch import BatchImportResult, ComprehensiveImportResult, ExcelUpload
from fastapi_app.services.inventory_service import calculate_available_shipment_quantity
from fastapi_app.services.numbering import (
    generate_case_stockin_number,
    generate_case_stockout_number,
    generate_order_number,
    generate_stockin_number,
    generate_stockout_number,
)
from fastapi_app.services.order_deduction_service import process_order_deduction
from fastapi_app.shared.stock_concurrency import get_product_for_update
from fastapi_app.shared_models import (
    CaseInventoryLog,
    CaseStockIn,
    CaseStockOut,
    InventoryLog,
    Order,
    Product,
    StockIn,
    StockOut,
)
from fastapi_app.shared_models.order import ORDER_STATUS_PENDING_STOCK
from fastapi_app.utils import validate_customer_name as _shared_validate_customer_name

logger = logging.getLogger(__name__)


# ==================== 数据验证 ====================

# 使用 fastapi_app.utils 中的统一验证函数
validate_customer_name = _shared_validate_customer_name


# ==================== 订单/备货导入（ARQ/Celery 通用） ====================

async def process_order_import(
    db: AsyncSession, file_path: str, original_filename: str, user_id: int
) -> dict:
    """处理订单批量导入（ARQ/Celery 通用）"""
    result_logger = logging.getLogger(f"{__name__}.order_import")
    result_logger.info(f"订单批量导入开始: {original_filename}, user_id={user_id}")

    success, data_list, error = await parse_excel_file_async(file_path)
    if not success:
        return {"success": False, "error": error, "imported": 0, "skipped": 0}

    if not data_list:
        return {"success": True, "imported": 0, "skipped": 0, "message": "没有有效数据行"}

    imported, errors = await import_orders_from_data(db, data_list)
    return {
        "success": True,
        "total_imported": imported,
        "imported": imported,
        "skipped": len(data_list) - imported,
        "errors": errors[:20],
    }


async def process_stockin_import(
    db: AsyncSession, file_path: str, original_filename: str, user_id: int
) -> dict:
    """处理备货批量导入（ARQ/Celery 通用）"""
    result_logger = logging.getLogger(f"{__name__}.stockin_import")
    result_logger.info(f"备货批量导入开始: {original_filename}, user_id={user_id}")

    success, data_list, error = await parse_excel_file_async(file_path)
    if not success:
        return {"success": False, "error": error, "imported": 0, "skipped": 0}

    if not data_list:
        return {"success": True, "imported": 0, "skipped": 0, "message": "没有有效数据行"}

    imported, errors = await import_stockins_from_data(db, data_list)
    return {
        "success": True,
        "total_imported": imported,
        "imported": imported,
        "skipped": len(data_list) - imported,
        "errors": errors[:20],
    }


# ==================== 端点业务逻辑（自 batch.py 端点下沉） ====================

async def _allocate_stockout_to_orders(
    db: AsyncSession, product: Product, qty: int, customer: str,
    stockout_date: datetime, note, shipment_info: dict,
) -> None:
    """按订单可用量分配出货，直到出货数量耗尽。

    Args:
        db: 异步数据库会话。
        product: 出库产品对象。
        qty: 总出库数量。
        customer: 客户名称。
        stockout_date: 出库日期。
        note: 备注原始值。
        shipment_info: 可出货量信息（含 orders 列表）。
    """
    remaining_qty = qty
    for order_detail in shipment_info['orders']:
        if remaining_qty <= 0:
            break
        if order_detail['available'] > 0:
            ship_qty = min(remaining_qty, order_detail['available'])
            stockout_no = await generate_stockout_number(db)
            stockout = StockOut(
                stockout_no=stockout_no, stockout_date=stockout_date, product_id=product.id,
                quantity=ship_qty, customer=customer, order_id=order_detail['order_id'],
                note=str(note).strip() if note else '',
            )
            db.add(stockout)
            remaining_qty -= ship_qty


async def _process_comprehensive_sheet(
    db: AsyncSession, sheet_type: str, sheet_name: str,
    data_list: list, results: ComprehensiveImportResult,
) -> None:
    """处理综合导入中的单个 Sheet。

    Args:
        db: 异步数据库会话。
        sheet_type: Sheet 类型（product/order/stockin/stockout）。
        sheet_name: Sheet 名称（用于日志和错误信息）。
        data_list: 解析后的行数据列表。
        results: 综合导入结果对象，原地更新。
    """
    entry = _SHEET_IMPORTERS.get(sheet_type)
    if entry is None:
        results.errors.append(f'Sheet {sheet_name} 类型未知: {sheet_type}')
        return
    importer, count_key = entry
    try:
        # savepoint 隔离单个 Sheet：失败仅回滚本 Sheet 未提交行，不影响其他 Sheet；
        # 计数在 savepoint 成功退出后才累加，保证上报数与实际落库一致
        async with db.begin_nested():
            # 四种 Sheet 的导入函数现在统一返回 (计数, 行级消息列表)。
            count, messages = await importer(db, data_list)
        results.imported[count_key] += count
        if messages:
            # 行级消息（含去重跳过原因）此前被整体丢弃，用户只能看到
            # 「Sheet X 导入失败」却不知道哪一行、为什么。
            results.errors.extend(messages)
    except (ValueError, TypeError, SQLAlchemyError) as e:
        # savepoint 上下文退出时已回滚本 Sheet 的未提交行
        logger.error(f'综合导入 - Sheet {sheet_name} 导入失败: {e}', exc_info=True)
        results.errors.append(f'Sheet {sheet_name} 导入失败')


async def read_template_bytes() -> tuple[bytes, str]:
    """下载统一导入模板 - 直接读取静态文件。

    Args:
        current_user: 当前登录用户（仅需通过权限校验）。

    Returns:
        tuple[bytes, str]: (文件内容, 文件名)。由端点层构造文件流响应。

    Raises:
        NotFoundError: 模板文件不存在。
        BusinessError: 模板文件为空或读取失败。
    """
    template_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
        'static', 'files', '统一导入模板.xlsx',
    )
    if not os.path.exists(template_path):
        raise NotFoundError('模板文件不存在')
    try:

        def _read_file():
            with open(template_path, 'rb') as fh:
                return fh.read()
        file_content = await asyncio.to_thread(_read_file)
        if not file_content:
            raise BusinessError('模板文件为空')
        return file_content, '统一导入模板.xlsx'
    except (OSError, ValueError) as exc:
        logger.error(f'模板读取失败: {exc}', exc_info=True)
        raise BusinessError('模板读取失败，请稍后重试') from exc


async def import_orders_service(db: AsyncSession, file: ExcelUpload) -> BatchImportResult:
    """批量导入订单 - 支持统一模板格式。

    Args:
        file: 上传的 Excel 文件（.xlsx 格式）。
        db: 异步数据库会话（读写主库）。
        current_user: 当前登录用户（仅需通过权限校验）。

    Returns:
        BatchImportResult: 包含导入结果、消息和条数的响应。
    """
    from fastapi_app.services.batch_service import get_all_products

    if (err := _validate_xlsx_file(file)):
        return err
    try:
        data_list, err = await _read_excel_sheets(file, ['订单管理'], '没有找到"订单管理"Sheet')
        if err:
            return BatchImportResult(success=False, message=err)
        # 构建产品映射，支持按名称（小写）和条码查找
        all_products = await get_all_products(db)
        product_map = {prod.name.lower().strip(): prod for prod in all_products}
        product_map.update({prod.barcode: prod for prod in all_products if prod.barcode})
        imported = 0
        skipped = 0
        errors = []
        for row_data in data_list:
            try:
                # savepoint 隔离单行：行内异常仅回滚本行，不影响循环内已成功的行
                async with db.begin_nested():
                    deduct_flag = row_data.get('抵扣备货')
                    note = row_data.get('备注')
                    parsed = _parse_import_row(row_data, product_map, '订单数量', '订单数量无效')
                    if parsed is None:
                        skipped += 1
                        continue
                    if parsed[0] is None:
                        errors.append(parsed[1])
                        skipped += 1
                        continue
                    customer, product_id, qty = parsed
                    order_no = await generate_order_number(db)
                    order = Order(
                        order_no=order_no, customer=customer, order_date=datetime.now(),
                        product_id=product_id, quantity=qty,
                        note=str(note).strip() if note else '', status=ORDER_STATUS_PENDING_STOCK,
                    )
                    db.add(order)
                    await db.flush()
                    locked_product = await get_product_for_update(db, product_id)
                    log = InventoryLog(
                        product_id=product_id, change_type='订单', change_quantity=qty,
                        related_id=order_no, note=f'批量导入订单：{order_no}',
                    )
                    db.add(log)
                    if deduct_flag and str(deduct_flag).strip() == '是':
                        await process_order_deduction(db, order, product_id, qty, deduct_stock=True, product=locked_product)
                # savepoint 成功提交后才计数，失败行不计入 imported
                imported += 1
            except (ValueError, TypeError, SQLAlchemyError) as exc:
                # savepoint 已自动回滚本行，不再整体 rollback（避免误伤已成功的行）
                logger.error(f'订单导入 - 行处理失败: {exc}', exc_info=True)
                errors.append('行处理失败')
                skipped += 1
                continue
        # 提交交给请求级事务（get_async_db），服务层不再手动 commit
        return _build_batch_result(imported, skipped, errors, success_msg='成功导入', fail_msg='没有成功导入任何订单')
    except (OSError, ValueError) as exc:
        await db.rollback()  # manual-tx: try/except 内显式事务控制
        logger.error(f'订单批量导入失败: {exc}', exc_info=True)
        return BatchImportResult(success=False, message='导入失败，请稍后重试')


async def import_case_stockouts_service(db: AsyncSession, file: ExcelUpload) -> BatchImportResult:
    """批量导入皮套出库。

    Args:
        file: 上传的 Excel 文件（.xlsx 格式）。
        db: 异步数据库会话（读写主库）。
        current_user: 当前登录用户（仅需通过权限校验）。

    Returns:
        BatchImportResult: 包含导入结果、消息和条数的响应。
    """
    from fastapi_app.services.batch_service import find_case_locked

    if (err := _validate_xlsx_file(file)):
        return err
    try:
        data_list, err = await _read_excel_sheets(file, ['皮套出库', '皮套出货'], '没有找到可用的Sheet')
        if err:
            return BatchImportResult(success=False, message=err)
        imported = 0
        skipped = 0
        errors = []
        for row_data in data_list:
            try:
                # savepoint 隔离单行：行内异常仅回滚本行，不影响循环内已成功的行
                async with db.begin_nested():
                    product_identifier = row_data.get('产品名称') or row_data.get('产品') or row_data.get('皮套名称') or row_data.get('皮套')
                    quantity = row_data.get('出库数量') or row_data.get('数量')
                    customer = row_data.get('客户名称') or row_data.get('客户')
                    stockout_date_val = row_data.get('时间') or row_data.get('出库时间')
                    note = row_data.get('备注')
                    if not product_identifier or not quantity:
                        skipped += 1
                        continue
                    product_identifier = str(product_identifier).strip()
                    customer = str(customer).strip() if customer else ''
                    try:
                        qty = int(quantity)
                        if qty <= 0:
                            errors.append('出库数量必须大于0')
                            skipped += 1
                            continue
                    except ValueError:
                        errors.append('出库数量必须是整数')
                        skipped += 1
                        continue
                    case, case_err = await find_case_locked(db, product_identifier)
                    if case_err:
                        errors.append(case_err)
                        skipped += 1
                        continue
                    if case.current_stock < qty:
                        errors.append(f'库存不足，当前库存: {case.current_stock}')
                        skipped += 1
                        continue
                    stockout_date = parse_date_value(stockout_date_val) or datetime.now()
                    stockout_no = await generate_case_stockout_number(db)
                    stockout = CaseStockOut(
                        stockout_no=stockout_no, stockout_date=stockout_date, case_id=case.id,
                        quantity=qty, customer=customer, note=str(note).strip() if note else '',
                    )
                    db.add(stockout)
                    case.current_stock -= qty
                    log = CaseInventoryLog(
                        case_id=case.id, change_type='出库', change_quantity=-qty,
                        related_id=stockout_no, customer=customer,
                        note=f'批量导入出库：客户{customer}，数量{qty}' if customer else f'批量导入出库：数量{qty}',
                    )
                    db.add(log)
                # savepoint 成功提交后才计数，失败行不计入 imported
                imported += 1
            except (ValueError, TypeError, SQLAlchemyError) as exc:
                # savepoint 已自动回滚本行，不再整体 rollback（避免误伤已成功的行）
                logger.error(f'皮套出库导入 - 行处理失败: {exc}', exc_info=True)
                errors.append('行处理失败')
                skipped += 1
                continue
        # 提交交给请求级事务（get_async_db），服务层不再手动 commit
        return _build_batch_result(imported, skipped, errors, success_msg='成功导入皮套出库', fail_msg='没有成功导入任何皮套出库')
    except (OSError, ValueError) as exc:
        await db.rollback()  # manual-tx: try/except 内显式事务控制
        logger.error(f'皮套出库批量导入失败: {exc}', exc_info=True)
        return BatchImportResult(success=False, message='导入失败，请稍后重试')


async def import_case_stockins_service(db: AsyncSession, file: ExcelUpload) -> BatchImportResult:
    """批量导入皮套入库。

    Args:
        file: 上传的 Excel 文件（.xlsx 格式）。
        db: 异步数据库会话（读写主库）。
        current_user: 当前登录用户（仅需通过权限校验）。

    Returns:
        BatchImportResult: 包含导入结果、消息和条数的响应。
    """
    from fastapi_app.services.batch_service import find_case_locked

    if (err := _validate_xlsx_file(file)):
        return err
    try:
        data_list, err = await _read_excel_sheets(file, ['皮套入库', '皮套进库'], '没有找到可用的Sheet')
        if err:
            return BatchImportResult(success=False, message=err)
        imported = 0
        skipped = 0
        errors = []
        for row_data in data_list:
            try:
                # savepoint 隔离单行：行内异常仅回滚本行，不影响循环内已成功的行
                async with db.begin_nested():
                    product_identifier = row_data.get('产品名称') or row_data.get('产品') or row_data.get('皮套名称') or row_data.get('皮套')
                    quantity = row_data.get('入库数量') or row_data.get('数量')
                    customer = row_data.get('客户名称') or row_data.get('客户')
                    stockin_date_val = row_data.get('时间') or row_data.get('入库时间')
                    note = row_data.get('备注')
                    if not product_identifier or not quantity:
                        skipped += 1
                        continue
                    product_identifier = str(product_identifier).strip()
                    customer = str(customer).strip() if customer else ''
                    try:
                        qty = int(quantity)
                        if qty <= 0:
                            errors.append('入库数量必须大于0')
                            skipped += 1
                            continue
                    except ValueError:
                        errors.append('入库数量必须是整数')
                        skipped += 1
                        continue
                    case, case_err = await find_case_locked(db, product_identifier)
                    if case_err:
                        errors.append(case_err)
                        skipped += 1
                        continue
                    stockin_date = parse_date_value(stockin_date_val) or datetime.now()
                    stockin_no = await generate_case_stockin_number(db)
                    stockin = CaseStockIn(
                        stockin_no=stockin_no, stockin_date=stockin_date, case_id=case.id,
                        quantity=qty, customer=customer, note=str(note).strip() if note else '',
                    )
                    db.add(stockin)
                    case.current_stock += qty
                    log = CaseInventoryLog(
                        case_id=case.id, change_type='入库', change_quantity=qty,
                        related_id=stockin_no, customer=customer,
                        note=f'批量导入入库：客户{customer}，数量{qty}' if customer else f'批量导入入库：数量{qty}',
                    )
                    db.add(log)
                # savepoint 成功提交后才计数，失败行不计入 imported
                imported += 1
            except (ValueError, TypeError, SQLAlchemyError) as exc:
                # savepoint 已自动回滚本行，不再整体 rollback（避免误伤已成功的行）
                logger.error(f'皮套入库导入 - 行处理失败: {exc}', exc_info=True)
                errors.append('行处理失败')
                skipped += 1
                continue
        # 提交交给请求级事务（get_async_db），服务层不再手动 commit
        return _build_batch_result(imported, skipped, errors, success_msg='成功导入皮套入库', fail_msg='没有成功导入任何皮套入库')
    except (OSError, ValueError) as exc:
        await db.rollback()  # manual-tx: try/except 内显式事务控制
        logger.error(f'皮套入库批量导入失败: {exc}', exc_info=True)
        return BatchImportResult(success=False, message='导入失败，请稍后重试')


async def import_stockins_service(db: AsyncSession, file: ExcelUpload) -> BatchImportResult:
    """批量导入备货 - 支持统一导入模板。

    Args:
        file: 上传的 Excel 文件（.xlsx 格式）。
        db: 异步数据库会话（读写主库）。
        current_user: 当前登录用户（仅需通过权限校验）。

    Returns:
        BatchImportResult: 包含导入结果、消息和条数的响应。
    """
    from fastapi_app.services.batch_service import get_all_products

    if (err := _validate_xlsx_file(file)):
        return err
    try:
        data_list, err = await _read_excel_sheets(file, ['备货管理'], '没有找到"备货管理"Sheet')
        if err:
            return BatchImportResult(success=False, message=err)
        # 构建产品映射，支持按名称（小写）和条码查找
        all_products = await get_all_products(db)
        product_map = {prod.name.lower().strip(): prod for prod in all_products}
        product_map.update({prod.barcode: prod for prod in all_products if prod.barcode})
        imported = 0
        skipped = 0
        errors = []
        for row_data in data_list:
            try:
                # savepoint 隔离单行：行内异常仅回滚本行，不影响循环内已成功的行
                async with db.begin_nested():
                    stockin_date_val = row_data.get('时间') or row_data.get('备货时间')
                    note = row_data.get('备注')
                    parsed = _parse_import_row(row_data, product_map, '备货数量', '备货数量无效')
                    if parsed is None:
                        skipped += 1
                        continue
                    if parsed[0] is None:
                        errors.append(parsed[1])
                        skipped += 1
                        continue
                    customer, product_id, qty = parsed
                    stockin_date = parse_date_value(stockin_date_val) or datetime.now()
                    stockin_no = await generate_stockin_number(db)
                    stockin = StockIn(
                        stockin_no=stockin_no, stockin_date=stockin_date, customer=customer,
                        product_id=product_id, quantity=qty, note=str(note).strip() if note else '',
                    )
                    db.add(stockin)
                    locked_product = await get_product_for_update(db, product_id)
                    locked_product.current_stock += qty
                    log = InventoryLog(
                        product_id=product_id, change_type='备货', change_quantity=qty,
                        related_id=stockin_no, note=f'批量导入备货：{stockin_no}',
                    )
                    db.add(log)
                # savepoint 成功提交后才计数，失败行不计入 imported
                imported += 1
            except (ValueError, TypeError, SQLAlchemyError) as exc:
                # savepoint 已自动回滚本行，不再整体 rollback（避免误伤已成功的行）
                logger.error(f'备货导入 - 行处理失败: {exc}', exc_info=True)
                errors.append('行处理失败')
                skipped += 1
                continue
        # 提交交给请求级事务（get_async_db），服务层不再手动 commit
        return _build_batch_result(imported, skipped, errors, success_msg='成功导入备货', fail_msg='没有成功导入任何备货')
    except (OSError, ValueError) as exc:
        await db.rollback()  # manual-tx: try/except 内显式事务控制
        logger.error(f'备货批量导入失败: {exc}', exc_info=True)
        return BatchImportResult(success=False, message='导入失败，请稍后重试')


async def import_stockouts_service(db: AsyncSession, file: ExcelUpload) -> BatchImportResult:
    """批量导入出库。

    Args:
        file: 上传的 Excel 文件（.xlsx 格式）。
        db: 异步数据库会话（读写主库）。
        current_user: 当前登录用户（仅需通过权限校验）。

    Returns:
        BatchImportResult: 包含导入结果、消息和条数的响应。
    """
    from fastapi_app.services.batch_service import get_product_by_identifier

    if (err := _validate_xlsx_file(file)):
        return err
    try:
        data_list, err = await _read_excel_sheets(file, ['出货管理'], '没有找到"出货管理"Sheet')
        if err:
            return BatchImportResult(success=False, message=err)
        imported = 0
        skipped = 0
        errors = []
        for row_data in data_list:
            try:
                # savepoint 隔离单行：行内异常仅回滚本行，不影响循环内已成功的行
                async with db.begin_nested():
                    product_identifier = row_data.get('产品名称') or row_data.get('产品')
                    quantity = row_data.get('出货数量') or row_data.get('数量')
                    customer = row_data.get('客户名称') or row_data.get('客户')
                    stockout_date_val = row_data.get('时间') or row_data.get('出货时间')
                    note = row_data.get('备注')
                    country_val = row_data.get('国家') or row_data.get('国家名称')
                    country_parsed = _parse_country_value(country_val)
                    order_type_parsed = 'custom' if country_parsed else 'regular'
                    if not product_identifier or not quantity:
                        skipped += 1
                        continue
                    product_identifier = str(product_identifier).strip()
                    customer = str(customer).strip() if customer else ''
                    if not customer:
                        errors.append('出货必须选择客户')
                        skipped += 1
                        continue
                    product = await get_product_by_identifier(db, product_identifier)
                    if not product:
                        errors.append(f'产品 {product_identifier} 不存在')
                        skipped += 1
                        continue
                    product = await get_product_for_update(db, product.id)
                    try:
                        qty = int(quantity)
                        if qty <= 0:
                            errors.append('出库数量必须大于0')
                            skipped += 1
                            continue
                    except ValueError:
                        errors.append('出库数量必须是整数')
                        skipped += 1
                        continue
                    if product.current_stock < qty:
                        errors.append(f'库存不足，当前库存: {product.current_stock}')
                        skipped += 1
                        continue
                    # 校验可出货量（基于订单支持）
                    shipment_info = await calculate_available_shipment_quantity(
                        db, product.id, customer, order_type=order_type_parsed, country=country_parsed or None,
                    )
                    if shipment_info['available_quantity'] <= 0:
                        errors.append(f'客户{customer}没有可用的订单支持出货')
                        skipped += 1
                        continue
                    if qty > shipment_info['available_quantity']:
                        errors.append(f"出货数量{qty}超过可出货量{shipment_info['available_quantity']}")
                        skipped += 1
                        continue
                    stockout_date = parse_date_value(stockout_date_val) or datetime.now()
                    # 按订单可用量分配出货，直到出货数量耗尽
                    await _allocate_stockout_to_orders(db, product, qty, customer, stockout_date, note, shipment_info)
                    product.current_stock -= qty
                    log = InventoryLog(
                        product_id=product.id, change_type='出库', change_quantity=-qty,
                        related_id='', note=f'批量导入出库：客户{customer}，数量{qty}',
                    )
                    db.add(log)
                # savepoint 成功提交后才计数，失败行不计入 imported
                imported += 1
            except (ValueError, TypeError, SQLAlchemyError) as exc:
                # savepoint 已自动回滚本行，不再整体 rollback（避免误伤已成功的行）
                logger.error(f'出库导入 - 行处理失败: {exc}', exc_info=True)
                errors.append('行处理失败')
                skipped += 1
                continue
        # 提交交给请求级事务（get_async_db），服务层不再手动 commit
        return _build_batch_result(imported, skipped, errors, success_msg='成功导入出货', fail_msg='没有成功导入任何出货')
    except (OSError, ValueError) as exc:
        await db.rollback()  # manual-tx: try/except 内显式事务控制
        logger.error(f'出库批量导入失败: {exc}', exc_info=True)
        return BatchImportResult(success=False, message='导入失败，请稍后重试')


async def import_products_service(db: AsyncSession, file: ExcelUpload) -> BatchImportResult:
    """批量导入产品 - 支持统一模板格式。

    Args:
        file: 上传的 Excel 文件（.xlsx 格式）。
        db: 异步数据库会话（读写主库）。
        current_user: 当前登录用户（仅需通过权限校验）。

    Returns:
        BatchImportResult: 包含导入结果、消息和条数的响应。
    """
    from fastapi_app.services.batch_service import get_product_by_name_ci

    if (err := _validate_xlsx_file(file)):
        return err
    try:
        data_list, err = await _read_excel_sheets(file, ['产品管理'], '没有找到"产品管理"Sheet')
        if err:
            return BatchImportResult(success=False, message=err)
        imported = 0
        skipped = 0
        errors = []
        for row_data in data_list:
            try:
                # savepoint 隔离单行：行内异常仅回滚本行，不影响循环内已成功的行
                async with db.begin_nested():
                    name = row_data.get('产品名称') or row_data.get('名称')
                    barcode = row_data.get('69码') or row_data.get('条码')
                    price = row_data.get('产品价格') or row_data.get('价格')
                    initial_stock = row_data.get('初始库存') or 0
                    if not name:
                        skipped += 1
                        continue
                    name = str(name).strip()
                    # 检查产品是否已存在（按名称忽略大小写）
                    existing = await get_product_by_name_ci(db, name)
                    if existing:
                        skipped += 1
                        continue
                    try:
                        stock = int(initial_stock) if initial_stock else 0
                    except ValueError:
                        stock = 0
                    try:
                        # Decimal(str(...)) 直转：避免 float 二进制近似值进入 Numeric 列
                        from decimal import Decimal, InvalidOperation

                        price_val = Decimal(str(price)) if price else Decimal('0')
                    except (ValueError, TypeError, InvalidOperation):
                        price_val = Decimal('0')
                    product = Product(
                        name=name, barcode=str(barcode).strip() if barcode else '',
                        price=price_val, initial_stock=stock, current_stock=stock,
                    )
                    db.add(product)
                # savepoint 成功提交后才计数，失败行不计入 imported
                imported += 1
            except (ValueError, TypeError, SQLAlchemyError) as exc:
                # savepoint 已自动回滚本行，不再整体 rollback（避免误伤已成功的行）
                logger.error(f'产品导入 - 行处理失败: {exc}', exc_info=True)
                errors.append('行处理失败')
                skipped += 1
                continue
        # 提交交给请求级事务（get_async_db），服务层不再手动 commit
        return _build_batch_result(imported, skipped, errors, success_msg='成功导入产品', fail_msg='没有找到需要导入的产品数据（可能都已存在）')
    except (OSError, ValueError) as exc:
        await db.rollback()  # manual-tx: try/except 内显式事务控制
        logger.error(f'产品批量导入失败: {exc}', exc_info=True)
        return BatchImportResult(success=False, message='导入失败，请稍后重试')


async def import_comprehensive_service(db: AsyncSession, file: ExcelUpload) -> ComprehensiveImportResult:
    """综合批量导入 - 支持4个Sheet自动识别。

    自动识别 Sheet 类型：产品管理、订单管理、备货管理、出货管理。
    每个 Sheet 独立处理，单个 Sheet 失败不影响其他 Sheet。

    Args:
        file: 上传的 Excel 文件（.xlsx 格式）。
        db: 异步数据库会话（读写主库）。
        current_user: 当前登录用户（仅需通过权限校验）。

    Returns:
        ComprehensiveImportResult: 包含各类型导入数量和错误列表的响应。
    """
    if not file.filename or not file.filename.endswith('.xlsx'):
        return ComprehensiveImportResult(success=False, message='只支持 Excel 文件格式 (.xlsx)，.xls 已不再支持')
    try:
        async with _save_uploaded_file(file) as temp_path:
            success, sheets, err = await read_excel_sheets_async(temp_path)
            if not success:
                return ComprehensiveImportResult(success=False, message=f'Excel读取失败: {err}')
            # ⚠️ 全部 Sheet 解析必须在本 async with 块内完成：
            # _save_uploaded_file 是 @asynccontextmanager，finally 会 os.unlink(temp_path)，
            # 一旦出块 temp_path 即失效，再读会得到 'no workbook found at path'。
            results = ComprehensiveImportResult(success=True)
            # Sheet 名称到类型的映射
            sheet_mapping = {'产品管理': 'product', '订单管理': 'order', '备货管理': 'stockin', '出货管理': 'stockout'}
            for sheet_name in sheets:
                sheet_type = _identify_sheet_type(sheet_name, sheet_mapping)
                if not sheet_type:
                    continue
                success, data_list, err = await parse_excel_file_async(temp_path, sheet_name)
                if not success:
                    results.errors.append(f'Sheet {sheet_name} 读取失败: {err}')
                    continue
                if not data_list:
                    continue
                await _process_comprehensive_sheet(db, sheet_type, sheet_name, data_list, results)
            results.message = '导入完成！'
        # 提交交给请求级事务（get_async_db）：全部 Sheet 在同一事务内原子落库，
        # 单 Sheet 失败已被 savepoint 隔离，无需在此手动 commit
        return results
    except (OSError, ValueError) as exc:
        await db.rollback()  # manual-tx: try/except 内显式事务控制
        logger.error(f'综合批量导入失败: {exc}', exc_info=True)
        return ComprehensiveImportResult(success=False, message='操作失败，请稍后重试')


# ==================== re-export 兼容层 ====================
# 从子模块导入全部被迁移的函数，保持 from fastapi_app.services.batch_import_service import X 兼容
# （X 为任意原公开/私有函数名）。调用方无需修改导入路径。
from fastapi_app.services.batch_import_core import (  # noqa: F401
    _import_data_generic,
    _pre_load_product_map,
    import_orders_from_data,
    import_products_from_data,
    import_stockins_from_data,
    import_stockouts_from_data,
)
from fastapi_app.services.batch_import_parser import (  # noqa: F401
    _build_batch_result,
    _find_target_sheet,
    _identify_sheet_type,
    _parse_country_value,
    _parse_import_row,
    _read_excel_sheets,
    _save_uploaded_file,
    _validate_xlsx_file,
    cleanup_temp_file,
    parse_date_value,
    parse_excel_file_async,
    read_excel_sheets_async,
)

# ==================== Sheet 类型分派注册表（OCP） ====================
# 定义在 re-export 之后，确保引用的导入函数已解析。
# 新增 Sheet 类型时：注册一行即可，_process_comprehensive_sheet 主流程无需改动。
_SHEET_IMPORTERS: dict[str, tuple[Callable, str]] = {
    'product': (import_products_from_data, 'products'),
    'order': (import_orders_from_data, 'orders'),
    'stockin': (import_stockins_from_data, 'stockins'),
    'stockout': (import_stockouts_from_data, 'stockouts'),
}
