"""
批量 Excel 导入业务逻辑服务

从 batch_service.py 提取的核心导入逻辑，适配异步 SQLAlchemy。
包含通用导入框架、产品/订单/备货/出货导入函数及文件解析辅助。
"""
import asyncio
import logging
import os
import tempfile
from contextlib import asynccontextmanager, suppress
from datetime import UTC, datetime

from fastapi import HTTPException, Response, UploadFile
from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from fastapi_app.schemas.batch import BatchImportResult, ComprehensiveImportResult
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
from fastapi_app.utils import parse_date_value as _shared_parse_date_value
from fastapi_app.utils import validate_customer_name as _shared_validate_customer_name

logger = logging.getLogger(__name__)


# ==================== 数据验证 ====================

# 使用 fastapi_app.utils 中的统一验证函数
validate_customer_name = _shared_validate_customer_name


# ==================== Excel 解析辅助 ====================

async def parse_excel_file_async(file_path: str, sheet_name: str | None = None) -> tuple[bool, list, str]:
    """异步解析 Excel 文件（Polars 引擎，比 pandas 快 5x）"""
    loop = asyncio.get_running_loop()

    def _sync_parse():
        try:
            import math

            import polars as pl
            if sheet_name:
                df = pl.read_excel(file_path, sheet_name=sheet_name)
            else:
                df = pl.read_excel(file_path)
                if df is None or df.is_empty():
                    return False, [], "Excel 文件为空"

            data_list = df.to_dicts()
            for row in data_list:
                for key, value in row.items():
                    if isinstance(value, str):
                        row[key] = value.strip() if value else None
                    elif isinstance(value, float) and math.isnan(value):
                        row[key] = None
            return True, data_list, ""
        except (ValueError, TypeError, OSError) as e:
            return False, [], str(e)

    return await loop.run_in_executor(None, _sync_parse)


async def read_excel_sheets_async(file_path: str) -> tuple[bool, list, str]:
    """读取 Excel 文件的所有 Sheet 名称"""
    loop = asyncio.get_running_loop()

    def _sync_read():
        try:
            from openpyxl import load_workbook
            wb = load_workbook(filename=file_path, read_only=True)
            sheets = wb.sheetnames
            wb.close()
            return True, sheets, ""
        except (ValueError, TypeError, OSError) as e:
            return False, [], str(e)

    return await loop.run_in_executor(None, _sync_read)


def parse_date_value(date_value) -> datetime | None:
    """解析日期值（支持多种格式），解析失败返回None - 委托给共享工具函数"""
    return _shared_parse_date_value(date_value)


# ==================== 综合导入子函数 ====================

async def _pre_load_product_map(db: AsyncSession) -> dict:
    """预加载产品字典（按名称小写与条码双重索引）。

    订单导入与备货导入共用此预加载逻辑，避免重复实现。
    """
    result = await db.execute(select(Product))
    all_products = result.scalars().all()
    product_map = {p.name.lower().strip(): p for p in all_products}
    product_map.update({p.barcode: p for p in all_products if p.barcode})
    return {'product_map': product_map}


async def _import_data_generic(
    db: AsyncSession,
    data_list: list,
    row_handler,
    pre_load=None,
    use_savepoint: bool = True,
    has_debug_messages: bool = True,
    label: str = "导入",
):
    """
    通用导入数据框架

    Args:
        db: 数据库会话
        data_list: 数据行列表
        row_handler: 异步回调 async (db, row_data, idx, context, debug_messages) -> bool
            返回 True 表示该行成功导入，False 表示跳过
        pre_load: 异步回调 async (db) -> dict，预加载数据
        use_savepoint: 是否使用 savepoint 包裹每行处理
        has_debug_messages: 是否收集调试消息
        label: 导入类型标签，用于日志和完成消息
    """
    count = 0
    debug_messages = [] if has_debug_messages else None

    context = await pre_load(db) if pre_load else {}

    for idx, row_data in enumerate(data_list, start=2):
        try:
            if use_savepoint:
                async with db.begin_nested():
                    if await row_handler(db, row_data, idx, context, debug_messages):
                        count += 1
            else:
                if await row_handler(db, row_data, idx, context, debug_messages):
                    count += 1
        except (ValueError, TypeError, SQLAlchemyError) as e:
            if debug_messages is not None:
                debug_messages.append(f"行{idx}: 异常 - {e!s}")
            logger.error(f"{label} - 行{idx}: 异常 - {e!s}", exc_info=True)
            continue

    await db.flush()

    completion_msg = f"{label}完成: 共导入 {count} 条"
    logger.info(completion_msg)
    if debug_messages is not None:
        debug_messages.append(completion_msg)

    if has_debug_messages:
        return count, debug_messages
    return count


async def import_products_from_data(db: AsyncSession, data_list: list) -> int:
    """从数据列表导入产品"""
    async def _pre_load(db):
        existing_result = await db.execute(select(func.lower(Product.name)))
        existing_names = {row[0] for row in existing_result.all()}
        return {'existing_names': existing_names}

    async def _row_handler(db, row_data, idx, context, debug_messages):
        existing_names = context['existing_names']
        name = row_data.get('产品名称') or row_data.get('产品名') or row_data.get('名称')
        barcode = row_data.get('69码') or row_data.get('条码') or row_data.get('条形码')
        price = row_data.get('产品价格') or row_data.get('价格')
        initial_stock = row_data.get('初始库存') or row_data.get('库存') or 0

        if not name:
            return False

        name = str(name).strip()

        if name.lower() in existing_names:
            return False

        try:
            stock = int(initial_stock) if initial_stock else 0
        except ValueError:
            logger.warning("产品导入：initial_stock 解析失败，使用默认值 0 (name=%s, value=%r)", name, initial_stock)
            stock = 0

        try:
            price_val = float(price) if price else 0
        except (ValueError, TypeError):
            logger.warning("产品导入：price 解析失败，使用默认值 0 (name=%s, value=%r)", name, price)
            price_val = 0

        product = Product(
            name=name,
            barcode=str(barcode).strip() if barcode else '',
            price=price_val,
            initial_stock=stock,
            current_stock=stock
        )
        db.add(product)
        return True

    return await _import_data_generic(
        db, data_list, _row_handler,
        pre_load=_pre_load,
        use_savepoint=False,
        has_debug_messages=False,
        label="产品导入",
    )


async def import_orders_from_data(db: AsyncSession, data_list: list) -> tuple[int, list]:
    """从数据列表导入订单"""
    async def _row_handler(db, row_data, idx, context, debug_messages):
        product_map = context['product_map']
        customer = row_data.get('客户名称') or row_data.get('客户')
        product_name = row_data.get('产品名称') or row_data.get('产品')
        quantity = row_data.get('数量') or row_data.get('订单数量')
        note = row_data.get('备注') or ''
        deduct_flag = row_data.get('抵扣备货') or row_data.get('是否抵扣备货') or row_data.get('抵扣')

        if not customer or not product_name or not quantity:
            return False

        customer = str(customer).strip()
        product_name = str(product_name).strip()

        is_valid, error_msg = validate_customer_name(customer)
        if not is_valid:
            debug_messages.append(f"行{idx}: 客户验证失败 - {error_msg}")
            return False

        # 使用预加载的产品字典查找
        product = product_map.get(product_name.lower().strip())
        product = product or product_map.get(product_name)
        if not product:
            debug_messages.append(f"行{idx}: 产品不存在 - {product_name}")
            return False
        product_id = product.id

        try:
            qty = int(quantity)
            if qty <= 0:
                return False
        except ValueError:
            logger.warning("订单导入：quantity 解析失败，跳过该行 (product=%s, customer=%s, value=%r)", product_name, customer, quantity)
            return False

        order_no = await generate_order_number(db)
        order = Order(
            order_no=order_no,
            customer=customer,
            order_date=datetime.now(UTC).replace(tzinfo=None),
            product_id=product_id,
            quantity=qty,
            note=str(note).strip() if note else '',
            status='待备货'
        )
        db.add(order)
        await db.flush()

        # 使用悲观锁更新产品库存，防止并发修改
        locked_product = await get_product_for_update(db, product_id)
        locked_product.current_stock += qty

        log = InventoryLog(
            product_id=product_id,
            change_type='订单',
            change_quantity=qty,
            related_id=order_no,
            note='综合导入订单：' + order_no
        )
        db.add(log)

        # 处理抵扣备货逻辑
        if deduct_flag:
            try:
                deduct_flag_str = str(deduct_flag).strip()
                deduct_value = 0
                if deduct_flag_str.isdigit():
                    deduct_value = int(deduct_flag_str)
                elif deduct_flag_str.lower() in ['是', 'yes']:
                    deduct_value = 1

                if deduct_value > 0:
                    await process_order_deduction(db, order, product_id, deduct_value, deduct_stock=True, product=product)
            except (ValueError, TypeError, SQLAlchemyError) as e:
                logger.error(f"订单导入 - 行{idx}: 抵扣处理异常: {e}", exc_info=True)

        return True

    count, debug_messages = await _import_data_generic(
        db, data_list, _row_handler,
        pre_load=_pre_load_product_map,
        use_savepoint=True,
        has_debug_messages=True,
        label="订单导入",
    )
    debug_messages.insert(0, f"开始处理订单数据，共{len(data_list)}行")
    return count, debug_messages


async def import_stockins_from_data(db: AsyncSession, data_list: list) -> tuple[int, list]:
    """从数据列表导入备货"""
    async def _row_handler(db, row_data, idx, context, debug_messages):
        product_map = context['product_map']
        customer = row_data.get('客户名称') or row_data.get('客户')
        product_name = row_data.get('产品名称') or row_data.get('产品')
        quantity = row_data.get('数量') or row_data.get('备货数量')
        stockin_date_val = row_data.get('时间') or row_data.get('备货时间')
        note = row_data.get('备注') or ''

        if not customer or not product_name or not quantity:
            return False

        customer = str(customer).strip()
        product_name = str(product_name).strip()

        is_valid, _error_msg = validate_customer_name(customer)
        if not is_valid:
            return False

        product = product_map.get(product_name.lower().strip())
        product = product or product_map.get(product_name)
        if not product:
            return False
        product_id = product.id

        try:
            qty = int(quantity)
            if qty <= 0:
                return False
        except ValueError:
            logger.warning("备货导入：quantity 解析失败，跳过该行 (product=%s, customer=%s, value=%r)", product_name, customer, quantity)
            return False

        stockin_date = parse_date_value(stockin_date_val) or datetime.now(UTC).replace(tzinfo=None)
        stockin_no = await generate_stockin_number(db)
        stockin = StockIn(
            stockin_no=stockin_no,
            stockin_date=stockin_date,
            customer=customer,
            product_id=product_id,
            quantity=qty,
            note=str(note).strip() if note else ''
        )
        db.add(stockin)

        # 使用悲观锁更新产品库存，防止并发修改
        locked_product = await get_product_for_update(db, product_id)
        locked_product.current_stock += qty

        log = InventoryLog(
            product_id=product_id,
            change_type='备货',
            change_quantity=qty,
            related_id=stockin_no,
            note='综合导入备货：' + stockin_no
        )
        db.add(log)

        return True

    return await _import_data_generic(
        db, data_list, _row_handler,
        pre_load=_pre_load_product_map,
        use_savepoint=True,
        has_debug_messages=True,
        label="备货导入",
    )


async def import_stockouts_from_data(db: AsyncSession, data_list: list) -> tuple[int, list]:
    """从数据列表导入出货"""
    async def _row_handler(db, row_data, idx, context, debug_messages):
        product_identifier = row_data.get('产品名称') or row_data.get('产品') or row_data.get('69码') or row_data.get('条码')
        quantity = row_data.get('数量') or row_data.get('出货数量')
        customer = row_data.get('客户名称') or row_data.get('客户')
        stockout_date_val = row_data.get('时间') or row_data.get('出货时间')
        note = row_data.get('备注') or ''
        country_val = row_data.get('国家') or row_data.get('国家名称')
        if not country_val or (isinstance(country_val, float) and country_val != country_val):
            country_parsed = ''
        else:
            country_parsed = str(country_val).strip()
        order_type_parsed = 'custom' if country_parsed else 'regular'

        if not product_identifier or not quantity:
            return False

        product_identifier = str(product_identifier).strip()
        customer = str(customer).strip() if customer else ''

        if not customer:
            return False

        # 查找产品
        result = await db.execute(
            select(Product).where(
                (Product.name == product_identifier) | (Product.barcode == product_identifier)
            )
        )
        product = result.scalar_one_or_none()
        if not product:
            return False

        try:
            qty = int(quantity)
            if qty <= 0:
                return False
        except ValueError:
            logger.warning("出货导入：quantity 解析失败，跳过该行 (product=%s, customer=%s, value=%r)", product_identifier, customer, quantity)
            return False

        if product.current_stock < qty:
            return False

        shipment_info = await calculate_available_shipment_quantity(
            db, product.id, customer,
            order_type=order_type_parsed, country=country_parsed or None
        )
        if shipment_info['available_quantity'] <= 0:
            return False

        if qty > shipment_info['available_quantity']:
            return False

        stockout_date = parse_date_value(stockout_date_val) or datetime.now(UTC).replace(tzinfo=None)

        remaining_qty = qty
        for order_detail in shipment_info['orders']:
            if remaining_qty <= 0:
                break
            if order_detail['available'] > 0:
                ship_qty = min(remaining_qty, order_detail['available'])
                stockout_no = await generate_stockout_number(db)
                stockout = StockOut(
                    stockout_no=stockout_no,
                    stockout_date=stockout_date,
                    product_id=product.id,
                    quantity=ship_qty,
                    customer=customer,
                    order_id=order_detail['order_id'],
                    note=str(note).strip() if note else ''
                )
                db.add(stockout)
                remaining_qty -= ship_qty

        # 使用悲观锁更新产品库存，防止并发修改
        locked_product = await get_product_for_update(db, product.id)
        locked_product.current_stock -= qty

        log = InventoryLog(
            product_id=product.id,
            change_type='出库',
            change_quantity=-qty,
            related_id='',
            note=f'综合导入出货：客户{customer}，数量{qty}'
        )
        db.add(log)

        return True

    return await _import_data_generic(
        db, data_list, _row_handler,
        pre_load=None,
        use_savepoint=True,
        has_debug_messages=True,
        label="出货导入",
    )


def cleanup_temp_file(file_path: str) -> None:
    """清理临时上传文件"""
    try:
        if file_path and os.path.exists(file_path):
            os.unlink(file_path)
            logger.debug(f"已清理临时文件: {file_path}")
    except OSError as e:
        logger.warning(f"清理临时文件失败: {file_path}, {e}")


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

MAX_BATCH_UPLOAD_SIZE = 5 * 1024 * 1024


@asynccontextmanager
async def _save_uploaded_file(file: UploadFile):
    """保存上传文件到临时路径，退出时自动清理。

    Args:
        file: 上传的文件对象。

    Yields:
        str: 临时文件路径。

    Raises:
        ValueError: 文件大小超过限制时抛出。
    """
    temp_path = None
    try:
        temp_fd, temp_path = tempfile.mkstemp(suffix='.xlsx')
        os.close(temp_fd)
        content = await file.read(MAX_BATCH_UPLOAD_SIZE + 1)
        if len(content) > MAX_BATCH_UPLOAD_SIZE:
            raise ValueError('文件大小超过5MB限制，请拆分后重新上传')
        with open(temp_path, 'wb') as fh:
            await asyncio.to_thread(fh.write, content)
        yield temp_path
    finally:
        if temp_path and os.path.exists(temp_path):
            with suppress(OSError):
                os.unlink(temp_path)


def _find_target_sheet(sheets: list, keywords: list[str]) -> str | None:
    """按关键词列表匹配 sheet 名称（顺序优先）。

    Args:
        sheets: Excel 中所有 sheet 名称列表。
        keywords: 关键词列表，按优先级排序。

    Returns:
        str | None: 匹配到的 sheet 名称；未匹配到则返回首个 sheet（可能为 None）。
    """
    for sheet in sheets:
        if any(keyword in sheet for keyword in keywords):
            return sheet
    return sheets[0] if sheets else None


def _build_batch_result(
    imported: int, skipped: int, errors: list,
    success_msg: str, fail_msg: str,
) -> BatchImportResult:
    """构建统一的批量导入返回结果。

    Args:
        imported: 成功导入条数。
        skipped: 跳过条数。
        errors: 错误信息列表。
        success_msg: 成功时的提示消息前缀。
        fail_msg: 失败时的提示消息。

    Returns:
        BatchImportResult: 统一的批量导入结果响应。
    """
    if imported > 0:
        msg = f'{success_msg} {imported} 条'
        if skipped > 0:
            msg += f'，跳过 {skipped} 行'
        if errors:
            msg += f"。错误: {'; '.join(errors[:5])}"
        return BatchImportResult(success=True, message=msg, imported=imported, skipped=skipped)
    if errors:
        return BatchImportResult(success=False, message=f"{fail_msg}。错误: {'; '.join(errors[:3])}")
    return BatchImportResult(success=False, message=fail_msg)


def _parse_import_row(
    row_data: dict, product_map: dict, quantity_field: str, qty_invalid_msg: str,
) -> tuple[str, int, int] | tuple[None, str] | None:
    """解析批量导入行的客户/产品/数量字段。

    Args:
        row_data: Excel 单行数据。
        product_map: 产品映射（小写名称/条码 → Product）。
        quantity_field: 数量列名（如 '订单数量'/'备货数量'）。
        qty_invalid_msg: 数量非法时的错误消息。

    Returns:
        (customer, product_id, qty): 解析成功
        (None, error_msg): 校验失败（调用方记录错误并跳过）
        None: 关键字段缺失（调用方静默跳过）
    """
    customer = row_data.get('客户名称') or row_data.get('客户')
    product_name = row_data.get('产品名称') or row_data.get('产品')
    quantity = row_data.get(quantity_field) or row_data.get('数量')
    if not customer or not product_name or (not quantity):
        return None
    customer = str(customer).strip()
    product_name = str(product_name).strip()
    is_valid, error_msg = validate_customer_name(customer)
    if not is_valid:
        return None, error_msg
    product = product_map.get(product_name.lower().strip())
    product = product or product_map.get(product_name)
    if not product:
        return None, f'产品不存在 - {product_name}'
    try:
        qty = int(quantity)
    except (ValueError, TypeError):
        return None, qty_invalid_msg
    return str(customer), product.id, qty


def _validate_xlsx_file(file: UploadFile) -> BatchImportResult | None:
    """校验上传文件是否为 .xlsx 格式。

    Args:
        file: 上传的文件对象。

    Returns:
        BatchImportResult | None: 校验失败返回错误结果，校验通过返回 None。
    """
    if not file.filename or not file.filename.endswith('.xlsx'):
        return BatchImportResult(success=False, message='只支持 Excel 文件格式 (.xlsx)，.xls 已不再支持')
    return None


async def _read_excel_sheets(
    file: UploadFile, keywords: list[str], not_found_msg: str,
) -> tuple[list | None, str | None]:
    """读取上传的 Excel 文件并解析目标 sheet 数据。

    Args:
        file: 上传的文件对象。
        keywords: sheet 名称匹配关键词列表。
        not_found_msg: 未找到目标 sheet 时的错误消息。

    Returns:
        tuple[list | None, str | None]: (数据列表, 错误消息)。
            成功时错误消息为 None；失败时数据列表为 None。
    """
    async with _save_uploaded_file(file) as temp_path:
        success, sheets, err = await read_excel_sheets_async(temp_path)
        if not success:
            return None, f'Excel读取失败: {err}'
        target_sheet = _find_target_sheet(sheets, keywords)
        if not target_sheet:
            return None, not_found_msg
        success, data_list, err = await parse_excel_file_async(temp_path, target_sheet)
        if not success:
            return None, f'数据解析失败: {err}'
    return data_list, None


def _parse_country_value(country_val) -> str:
    """解析国家字段，处理 NaN 值（Excel 空单元格可能为 float NaN）。

    Args:
        country_val: 原始国家字段值。

    Returns:
        str: 清理后的国家名称字符串，空值返回空字符串。
    """
    if not country_val or (isinstance(country_val, float) and country_val != country_val):
        return ''
    return str(country_val).strip()


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


def _identify_sheet_type(sheet_name: str, sheet_mapping: dict) -> str | None:
    """根据 Sheet 名称识别导入类型。

    Args:
        sheet_name: Sheet 名称。
        sheet_mapping: 名称关键词到类型的映射字典。

    Returns:
        str | None: 匹配到的类型；未匹配返回 None。
    """
    for key, value in sheet_mapping.items():
        if key in sheet_name:
            return value
    return None


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
    try:
        if sheet_type == 'product':
            count = await import_products_from_data(db, data_list)
            results.imported['products'] += count
        elif sheet_type == 'order':
            try:
                count, _ = await import_orders_from_data(db, data_list)
                results.imported['orders'] += count
            except (ValueError, TypeError, SQLAlchemyError) as order_e:
                await db.rollback()  # manual-tx: try/except 内显式事务控制
                await db.begin_nested()
                logger.error(f'综合导入 - 订单Sheet {sheet_name} 导入失败: {order_e}', exc_info=True)
                results.errors.append(f'Sheet {sheet_name} 导入失败')
        elif sheet_type == 'stockin':
            try:
                count, _ = await import_stockins_from_data(db, data_list)
                results.imported['stockins'] += count
            except (ValueError, TypeError, SQLAlchemyError) as stockin_e:
                await db.rollback()  # manual-tx: try/except 内显式事务控制
                await db.begin_nested()
                logger.error(f'综合导入 - 备货Sheet {sheet_name} 导入失败: {stockin_e}', exc_info=True)
                results.errors.append(f'Sheet {sheet_name} 导入失败')
        elif sheet_type == 'stockout':
            try:
                count, _ = await import_stockouts_from_data(db, data_list)
                results.imported['stockouts'] += count
            except (ValueError, TypeError, SQLAlchemyError) as stockout_e:
                await db.rollback()  # manual-tx: try/except 内显式事务控制
                await db.begin_nested()
                logger.error(f'综合导入 - 出货Sheet {sheet_name} 导入失败: {stockout_e}', exc_info=True)
                results.errors.append(f'Sheet {sheet_name} 导入失败')
    except (ValueError, TypeError, SQLAlchemyError) as exc:
        await db.rollback()  # manual-tx: try/except 内显式事务控制
        await db.begin_nested()
        logger.error(f'综合导入 - Sheet {sheet_name} 处理失败: {exc}', exc_info=True)
        results.errors.append(f'Sheet {sheet_name} 导入失败')


async def download_template_service() -> Response:
    """下载统一导入模板 - 直接读取静态文件。

    Args:
        current_user: 当前登录用户（仅需通过权限校验）。

    Returns:
        Response: Excel 文件流响应。

    Raises:
        HTTPException: 模板文件不存在时抛出 404；读取失败时抛出 500。
    """
    from urllib.parse import quote

    template_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
        'static', 'files', '统一导入模板.xlsx',
    )
    if not os.path.exists(template_path):
        raise HTTPException(status_code=404, detail='模板文件不存在')
    try:

        def _read_file():
            with open(template_path, 'rb') as fh:
                return fh.read()
        file_content = await asyncio.to_thread(_read_file)
        if not file_content:
            raise HTTPException(status_code=500, detail='模板文件为空')
        filename = '统一导入模板.xlsx'
        encoded_filename = quote(filename)
        return Response(
            content=file_content,
            media_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            headers={
                'Content-Disposition': f"attachment; filename*=UTF-8''{encoded_filename}",
                'Content-Length': str(len(file_content)),
                'Cache-Control': 'no-cache, no-store, must-revalidate',
            },
        )
    except HTTPException:
        raise
    except (OSError, ValueError) as exc:
        logger.error(f'模板读取失败: {exc}', exc_info=True)
        raise HTTPException(status_code=500, detail='模板读取失败，请稍后重试') from exc


async def import_orders_service(db: AsyncSession, file: UploadFile) -> BatchImportResult:
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
                        note=str(note).strip() if note else '', status='待备货',
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
        if imported > 0:
            await db.commit()  # manual-tx: try/except 内显式事务控制
        return _build_batch_result(imported, skipped, errors, success_msg='成功导入', fail_msg='没有成功导入任何订单')
    except (OSError, ValueError) as exc:
        await db.rollback()  # manual-tx: try/except 内显式事务控制
        logger.error(f'订单批量导入失败: {exc}', exc_info=True)
        return BatchImportResult(success=False, message='导入失败，请稍后重试')


async def import_case_stockouts_service(db: AsyncSession, file: UploadFile) -> BatchImportResult:
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
        if imported > 0:
            await db.commit()  # manual-tx: try/except 内显式事务控制
        return _build_batch_result(imported, skipped, errors, success_msg='成功导入皮套出库', fail_msg='没有成功导入任何皮套出库')
    except (OSError, ValueError) as exc:
        await db.rollback()  # manual-tx: try/except 内显式事务控制
        logger.error(f'皮套出库批量导入失败: {exc}', exc_info=True)
        return BatchImportResult(success=False, message='导入失败，请稍后重试')


async def import_case_stockins_service(db: AsyncSession, file: UploadFile) -> BatchImportResult:
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
        if imported > 0:
            await db.commit()  # manual-tx: try/except 内显式事务控制
        return _build_batch_result(imported, skipped, errors, success_msg='成功导入皮套入库', fail_msg='没有成功导入任何皮套入库')
    except (OSError, ValueError) as exc:
        await db.rollback()  # manual-tx: try/except 内显式事务控制
        logger.error(f'皮套入库批量导入失败: {exc}', exc_info=True)
        return BatchImportResult(success=False, message='导入失败，请稍后重试')


async def import_stockins_service(db: AsyncSession, file: UploadFile) -> BatchImportResult:
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
        if imported > 0:
            await db.commit()  # manual-tx: try/except 内显式事务控制
        return _build_batch_result(imported, skipped, errors, success_msg='成功导入备货', fail_msg='没有成功导入任何备货')
    except (OSError, ValueError) as exc:
        await db.rollback()  # manual-tx: try/except 内显式事务控制
        logger.error(f'备货批量导入失败: {exc}', exc_info=True)
        return BatchImportResult(success=False, message='导入失败，请稍后重试')


async def import_stockouts_service(db: AsyncSession, file: UploadFile) -> BatchImportResult:
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
        if imported > 0:
            await db.commit()  # manual-tx: try/except 内显式事务控制
        return _build_batch_result(imported, skipped, errors, success_msg='成功导入出货', fail_msg='没有成功导入任何出货')
    except (OSError, ValueError) as exc:
        await db.rollback()  # manual-tx: try/except 内显式事务控制
        logger.error(f'出库批量导入失败: {exc}', exc_info=True)
        return BatchImportResult(success=False, message='导入失败，请稍后重试')


async def import_products_service(db: AsyncSession, file: UploadFile) -> BatchImportResult:
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
                        price_val = float(price) if price else 0
                    except (ValueError, TypeError):
                        price_val = 0
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
        if imported > 0:
            await db.commit()  # manual-tx: try/except 内显式事务控制
        return _build_batch_result(imported, skipped, errors, success_msg='成功导入产品', fail_msg='没有找到需要导入的产品数据（可能都已存在）')
    except (OSError, ValueError) as exc:
        await db.rollback()  # manual-tx: try/except 内显式事务控制
        logger.error(f'产品批量导入失败: {exc}', exc_info=True)
        return BatchImportResult(success=False, message='导入失败，请稍后重试')


async def import_comprehensive_service(db: AsyncSession, file: UploadFile) -> ComprehensiveImportResult:
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
        results = ComprehensiveImportResult()
        # Sheet 名称到类型的映射
        sheet_mapping = {'产品管理': 'product', '订单管理': 'order', '备货管理': 'stockin', '出货管理': 'stockout'}
        await db.begin_nested()
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
        await db.commit()  # manual-tx: try/except 内显式事务控制
        return results
    except (OSError, ValueError) as exc:
        await db.rollback()  # manual-tx: try/except 内显式事务控制
        logger.error(f'综合批量导入失败: {exc}', exc_info=True)
        return ComprehensiveImportResult(success=False, message='操作失败，请稍后重试')
