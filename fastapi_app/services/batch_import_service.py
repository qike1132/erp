"""
批量 Excel 导入业务逻辑服务

从 batch_service.py 提取的核心导入逻辑，适配异步 SQLAlchemy。
包含通用导入框架、产品/订单/备货/出货导入函数及文件解析辅助。
"""
import asyncio
import logging
import os
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from fastapi_app.services.inventory_service import calculate_available_shipment_quantity
from fastapi_app.services.numbering import (
    generate_order_number,
    generate_stockin_number,
    generate_stockout_number,
)
from fastapi_app.services.order_deduction_service import process_order_deduction
from fastapi_app.shared.stock_concurrency import get_product_for_update
from fastapi_app.shared_models import InventoryLog, Order, Product, StockIn, StockOut
from fastapi_app.utils import parse_date_value as _shared_parse_date_value
from fastapi_app.utils import validate_customer_name as _shared_validate_customer_name

logger = logging.getLogger(__name__)


# ==================== 数据验证 ====================

# 使用 fastapi_app.utils 中的统一验证函数
validate_customer_name = _shared_validate_customer_name


# ==================== Excel 解析辅助 ====================

async def parse_excel_file_async(file_path: str, sheet_name: str = None) -> tuple[bool, list, str]:
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
                debug_messages.append(f"行{idx}: 异常 - {str(e)}")
            logger.error(f"{label} - 行{idx}: 异常 - {str(e)}", exc_info=True)
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
            stock = 0

        try:
            price_val = float(price) if price else 0
        except (ValueError, TypeError):
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
            return False

        order_no = await generate_order_number(db)
        order = Order(
            order_no=order_no,
            customer=customer,
            order_date=datetime.now(timezone.utc).replace(tzinfo=None),
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

        is_valid, error_msg = validate_customer_name(customer)
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
            return False

        stockin_date = parse_date_value(stockin_date_val) or datetime.now(timezone.utc).replace(tzinfo=None)
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

        stockout_date = parse_date_value(stockout_date_val) or datetime.now(timezone.utc).replace(tzinfo=None)

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
