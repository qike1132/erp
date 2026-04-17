"""
批量导入业务逻辑服务

从 Flask batch.py 提取的核心业务逻辑，适配异步 SQLAlchemy。
"""
import os
import tempfile
import shutil
import logging
import asyncio
from datetime import datetime
from typing import Tuple, Optional

from sqlalchemy import select, func, and_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from sqlalchemy.exc import SQLAlchemyError

from fastapi_app.shared_models import Product, Order, StockIn, StockOut, InventoryLog

logger = logging.getLogger(__name__)


# ==================== 编号生成 ====================

class AsyncNumberGenerator:
    """异步编号生成器，在批量操作中维护序号计数器"""
    _instance = None
    _counters = {}
    _initialized = {}
    _lock = asyncio.Lock()
    _last_cleanup_date = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    @classmethod
    def _cleanup_old_entries(cls):
        """清理非当日的计数器条目，防止内存泄漏"""
        today_str = datetime.now().strftime('%Y%m%d')
        if cls._last_cleanup_date == today_str:
            return
        expired_keys = [k for k in cls._counters if not k.endswith(today_str)]
        for k in expired_keys:
            cls._counters.pop(k, None)
            cls._initialized.pop(k, None)
        cls._last_cleanup_date = today_str

    def is_initialized(self, prefix, date_str):
        key = f"{prefix}:{date_str}"
        return self._initialized.get(key, False)

    def set_initialized(self, prefix, date_str):
        key = f"{prefix}:{date_str}"
        self._initialized[key] = True

    def reset_counter(self, prefix, date_str):
        key = f"{prefix}:{date_str}"
        self._counters[key] = 0
        self._initialized[key] = False

    def get_next_seq(self, prefix, date_str, current_max):
        key = f"{prefix}:{date_str}"
        if key not in self._counters:
            self._counters[key] = current_max
        else:
            self._counters[key] = max(self._counters[key], current_max)
        self._counters[key] += 1
        result = self._counters[key]
        self._initialized[key] = True
        return result


_async_number_generator = AsyncNumberGenerator()


async def generate_number_async(prefix: str, model, date_field: str, number_field: str, db: AsyncSession) -> str:
    """
    异步编号生成器

    Args:
        prefix: 编号前缀 (如 'PO', 'SI', 'SO')
        model: 数据模型类
        date_field: 日期字段名称
        number_field: 编号字段名称
        db: 异步数据库会话

    Returns:
        str: 生成的编号,格式为 PREFIX-YYYYMMDD-XXXX
    """
    today = datetime.now()
    date_str = today.strftime('%Y%m%d')

    async with _async_number_generator._lock:
        _async_number_generator._cleanup_old_entries()

        if not _async_number_generator.is_initialized(prefix, date_str):
            result = await db.execute(
                select(model)
                .where(func.date(getattr(model, date_field)) == today.date())
                .order_by(getattr(model, number_field).desc())
                .limit(1)
            )
            record = result.scalar_one_or_none()

            db_max = 0
            if record:
                last_number = getattr(record, number_field)
                try:
                    db_max = int(last_number.split('-')[-1])
                except (ValueError, IndexError):
                    pass

            _async_number_generator.get_next_seq(prefix, date_str, db_max)

        current_seq = _async_number_generator.get_next_seq(prefix, date_str, 0)
        return f"{prefix}-{date_str}-{str(current_seq).zfill(4)}"


async def generate_order_number(db: AsyncSession) -> str:
    """生成订单编号 PO-YYYYMMDD-XXXX"""
    return await generate_number_async('PO', Order, 'order_date', 'order_no', db)


async def generate_stockin_number(db: AsyncSession) -> str:
    """生成备货编号 SI-YYYYMMDD-XXXX"""
    return await generate_number_async('SI', StockIn, 'stockin_date', 'stockin_no', db)


async def generate_stockout_number(db: AsyncSession) -> str:
    """生成出货编号 SO-YYYYMMDD-XXXX"""
    return await generate_number_async('SO', StockOut, 'stockout_date', 'stockout_no', db)


async def generate_case_stockout_number(db: AsyncSession) -> str:
    """生成皮套出库编号 CSO-YYYYMMDD-XXXX"""
    from fastapi_app.shared_models import CaseStockOut
    return await generate_number_async('CSO', CaseStockOut, 'stockout_date', 'stockout_no', db)


async def generate_case_stockin_number(db: AsyncSession) -> str:
    """生成皮套入库编号 CSI-YYYYMMDD-XXXX"""
    from fastapi_app.shared_models import CaseStockIn
    return await generate_number_async('CSI', CaseStockIn, 'stockin_date', 'stockin_no', db)


# ==================== 数据验证 ====================

import re


def validate_customer_name(customer_name: str) -> Tuple[bool, str]:
    """验证客户名称"""
    if not customer_name or not customer_name.strip():
        return False, "客户名称不能为空"

    customer_name = customer_name.strip()
    if len(customer_name) < 2:
        return False, "客户名称至少需要 2 个字符"
    if len(customer_name) > 100:
        return False, "客户名称不能超过 100 个字符"

    pattern = r'^[\u4e00-\u9fa5a-zA-Z0-9\s\-\_\.\,\(\)\（\）]+$'
    if not re.match(pattern, customer_name):
        return False, "客户名称包含非法字符"
    return True, ""


# ==================== 核心业务逻辑 ====================

async def process_order_deduction(
    db: AsyncSession,
    order: Order,
    product_id: int,
    order_quantity: int,
    deduct_stock: bool = True,
    custom_deduct_quantity: Optional[int] = None,
    product: Optional[Product] = None,
) -> Tuple[int, list]:
    """
    处理订单抵扣备货的核心逻辑

    业务规则：
    - 一个订单只能抵扣一个备货（不允许拆分到多个备货）
    - 如果单个备货数量不足订单数量，则部分抵扣
    - 按FIFO原则选择最早的可用备货
    """
    deduction_details = []

    if not deduct_stock:
        return 0, deduction_details

    try:
        # 查询该订单对应产品的所有备货，按时间正序排列
        result = await db.execute(
            select(StockIn)
            .where(
                StockIn.product_id == product_id,
                StockIn.customer == order.customer
            )
            .options(selectinload(StockIn.stockin_stockouts))
            .order_by(StockIn.stockin_date.asc(), StockIn.id.asc())
        )
        stockins = result.scalars().all()

        # 计算每个备货的可用数量
        stockin_available = None
        for stockin in stockins:
            deducted = sum(s.quantity for s in stockin.stockin_stockouts) if stockin.stockin_stockouts else 0
            available = stockin.quantity - deducted
            if available > 0:
                stockin_available = (stockin, available)
                break

        if not stockin_available:
            logger.info(f'订单{order.order_no}无可用备货抵扣')
            order.status = '待备货'
            return 0, deduction_details

        stockin, available = stockin_available

        # 计算要抵扣的数量
        if custom_deduct_quantity is not None and custom_deduct_quantity > 0:
            deduct_amount = min(custom_deduct_quantity, available)
        else:
            deduct_amount = min(order_quantity, available)

        if deduct_amount < order_quantity and deduct_amount < available:
            logger.warning(f'订单{order.order_no}备货不足：需求{order_quantity}，可用{available}')

        # 生成出货编号并创建抵扣记录
        stockout_no = await generate_stockout_number(db)

        stockout = StockOut(
            stockout_no=stockout_no,
            stockout_date=datetime.now(),
            product_id=stockin.product_id,
            quantity=deduct_amount,
            customer=order.customer,
            order_id=order.id,
            stockin_id=stockin.id,
            note=f'[订单抵扣]{order.order_no}'
        )
        db.add(stockout)

        log = InventoryLog(
            product_id=stockin.product_id,
            change_type='订单抵扣',
            change_quantity=-deduct_amount,
            related_id=stockout_no,
            note=f'订单抵扣备货：{stockin.stockin_no}，订单号：{order.order_no}'
        )
        db.add(log)

        deduction_details.append({
            'stockin_id': stockin.id,
            'stockin_no': stockin.stockin_no,
            'deduct_amount': deduct_amount,
            'stockout_no': stockout_no,
            'remaining_in_stockin': available - deduct_amount
        })

        # 更新产品库存
        if product is None:
            result = await db.execute(select(Product).where(Product.id == product_id))
            product = result.scalar_one_or_none()
        if product and deduct_amount > 0:
            product.current_stock -= deduct_amount

        # 更新订单状态
        if deduct_amount >= order_quantity:
            order.status = '已备货'
        elif deduct_amount > 0:
            order.status = '部分备货'
        else:
            order.status = '待备货'

        logger.info(f'订单抵扣处理完成：订单{order.order_no}，抵扣数量{deduct_amount}')
        return deduct_amount, deduction_details

    except SQLAlchemyError as e:
        logger.error(f'订单抵扣数据库错误：{str(e)}', exc_info=True)
        raise
    except Exception as e:
        logger.error(f'订单抵扣处理错误：{str(e)}', exc_info=True)
        raise


async def calculate_available_shipment_quantity(db: AsyncSession, product_id: int, customer: str) -> dict:
    """
    计算指定客户和产品的可出货量

    业务规则：
    1. 出货量严格受限于订单量
    2. 备货量只能通过订单抵扣使用，不能直接出货
    3. 可出货量 = 订单总量 - 已出货量（非抵扣出货）
    """
    result = await db.execute(
        select(Order)
        .where(Order.product_id == product_id, Order.customer == customer)
        .order_by(Order.order_date.asc())
    )
    orders = result.scalars().all()

    if not orders:
        return {
            'order_quantity': 0,
            'shipped_quantity': 0,
            'available_quantity': 0,
            'orders': []
        }

    # 单次查询获取所有订单的已出货量，替代N+1循环查询
    order_ids = [o.id for o in orders]
    shipped_result = await db.execute(
        select(StockOut.order_id, func.sum(StockOut.quantity))
        .where(
            StockOut.order_id.in_(order_ids),
            StockOut.stockin_id.is_(None)
        )
        .group_by(StockOut.order_id)
    )
    shipped_map = dict(shipped_result.all())

    total_order_quantity = 0
    order_details = []

    for order in orders:
        total_order_quantity += order.quantity
        non_deduction_shipped = shipped_map.get(order.id, 0)

        order_details.append({
            'order_id': order.id,
            'order_no': order.order_no,
            'quantity': order.quantity,
            'shipped': non_deduction_shipped,
            'available': order.quantity - non_deduction_shipped
        })

    total_shipped = sum(shipped_map.values())

    available_quantity = max(0, total_order_quantity - total_shipped)

    return {
        'order_quantity': total_order_quantity,
        'shipped_quantity': total_shipped,
        'available_quantity': available_quantity,
        'orders': order_details
    }


# ==================== Excel 解析辅助 ====================

async def parse_excel_file_async(file_path: str, sheet_name: str = None) -> Tuple[bool, list, str]:
    """
    异步解析 Excel 文件（使用 run_in_executor 避免 CPU 密集操作阻塞事件循环）
    """
    loop = asyncio.get_running_loop()

    def _sync_parse():
        try:
            import pandas as pd
            if sheet_name:
                df = pd.read_excel(file_path, sheet_name=sheet_name)
            else:
                excel_file = pd.ExcelFile(file_path)
                first_sheet = excel_file.sheet_names[0]
                df = pd.read_excel(file_path, sheet_name=first_sheet)

            data_list = df.to_dict(orient='records')
            for row in data_list:
                for key, value in row.items():
                    if isinstance(value, str):
                        row[key] = value.strip() if value else None
                    elif pd.isna(value) if isinstance(value, float) else False:
                        row[key] = None
            return True, data_list, ""
        except Exception as e:
            return False, [], str(e)

    return await loop.run_in_executor(None, _sync_parse)


async def read_excel_sheets_async(file_path: str) -> Tuple[bool, list, str]:
    """读取 Excel 文件的所有 Sheet 名称"""
    loop = asyncio.get_running_loop()

    def _sync_read():
        try:
            import pandas as pd
            excel_file = pd.ExcelFile(file_path)
            return True, excel_file.sheet_names, ""
        except Exception as e:
            return False, [], str(e)

    return await loop.run_in_executor(None, _sync_read)


def parse_date_value(date_value) -> Optional[datetime]:
    """解析日期值（支持多种格式），解析失败返回None"""
    if date_value is None:
        return None
    if isinstance(date_value, datetime):
        return date_value
    if isinstance(date_value, (int, float)):
        try:
            from datetime import timedelta
            base_date = datetime(1899, 12, 30)
            return base_date + timedelta(days=date_value)
        except Exception:
            return None
    try:
        date_str = str(date_value).strip()
        for fmt in ["%Y-%m-%d", "%Y/%m/%d", "%Y-%m-%d %H:%M:%S", "%Y/%m/%d %H:%M:%S"]:
            try:
                return datetime.strptime(date_str, fmt)
            except ValueError:
                continue
    except Exception:
        pass
    return None


# ==================== 综合导入子函数 ====================

async def import_products_from_data(db: AsyncSession, data_list: list) -> int:
    """从数据列表导入产品"""
    count = 0
    for idx, row_data in enumerate(data_list, start=2):
        try:
            name = row_data.get('产品名称') or row_data.get('产品名') or row_data.get('名称')
            barcode = row_data.get('69码') or row_data.get('条码') or row_data.get('条形码')
            price = row_data.get('产品价格') or row_data.get('价格')
            initial_stock = row_data.get('初始库存') or row_data.get('库存') or 0

            if not name:
                continue

            name = str(name).strip()

            # 检查重复
            result = await db.execute(
                select(Product).where(func.lower(Product.name) == func.lower(name))
            )
            existing = result.scalar_one_or_none()
            if existing:
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
                name=name,
                barcode=str(barcode).strip() if barcode else '',
                price=price_val,
                initial_stock=stock,
                current_stock=stock
            )
            db.add(product)
            count += 1
        except Exception as e:
            logger.error(f"产品导入 - 行{idx}: 异常 - {str(e)}")
            continue

    await db.commit()
    logger.info(f"产品导入完成: 共导入 {count} 条")
    return count


async def import_orders_from_data(db: AsyncSession, data_list: list) -> Tuple[int, list]:
    """从数据列表导入订单"""
    count = 0
    debug_messages = []
    debug_messages.append(f"开始处理订单数据，共{len(data_list)}行")

    # 预加载所有产品
    result = await db.execute(select(Product))
    all_products = result.scalars().all()
    product_map = {p.name.lower().strip(): p for p in all_products}
    product_map.update({p.barcode: p for p in all_products if p.barcode})

    for idx, row_data in enumerate(data_list, start=2):
        try:
            customer = row_data.get('客户名称') or row_data.get('客户')
            product_name = row_data.get('产品名称') or row_data.get('产品')
            quantity = row_data.get('数量') or row_data.get('订单数量')
            note = row_data.get('备注') or ''
            deduct_flag = row_data.get('抵扣备货') or row_data.get('是否抵扣备货') or row_data.get('抵扣')

            if not customer or not product_name or not quantity:
                continue

            customer = str(customer).strip()
            product_name = str(product_name).strip()

            is_valid, error_msg = validate_customer_name(customer)
            if not is_valid:
                debug_messages.append(f"行{idx}: 客户验证失败 - {error_msg}")
                continue

            # 使用预加载的产品字典查找
            product = product_map.get(product_name.lower().strip())
            product = product or product_map.get(product_name)
            if not product:
                debug_messages.append(f"行{idx}: 产品不存在 - {product_name}")
                continue
            product_id = product.id

            try:
                qty = int(quantity)
                if qty <= 0:
                    continue
            except ValueError:
                continue

            order_no = await generate_order_number(db)
            order = Order(
                order_no=order_no,
                customer=customer,
                order_date=datetime.now(),
                product_id=product_id,
                quantity=qty,
                note=str(note).strip() if note else '',
                status='待备货'
            )
            db.add(order)
            await db.flush()

            # 更新产品库存
            product.current_stock += qty

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
                except Exception as e:
                    logger.error(f"订单导入 - 行{idx}: 抵扣处理异常: {e}", exc_info=True)

            count += 1
        except Exception as e:
            logger.error(f"订单导入 - 行{idx}: 处理异常: {e}", exc_info=True)
            continue

    await db.commit()
    debug_messages.append(f"订单导入完成: 共导入 {count} 条")
    return count, debug_messages


async def import_stockins_from_data(db: AsyncSession, data_list: list) -> Tuple[int, list]:
    """从数据列表导入备货"""
    count = 0
    debug_messages = []

    # 预加载所有产品
    result = await db.execute(select(Product))
    all_products = result.scalars().all()
    product_map = {p.name.lower().strip(): p for p in all_products}
    product_map.update({p.barcode: p for p in all_products if p.barcode})

    for idx, row_data in enumerate(data_list, start=2):
        try:
            customer = row_data.get('客户名称') or row_data.get('客户')
            product_name = row_data.get('产品名称') or row_data.get('产品')
            quantity = row_data.get('数量') or row_data.get('备货数量')
            stockin_date_val = row_data.get('时间') or row_data.get('备货时间')
            note = row_data.get('备注') or ''

            if not customer or not product_name or not quantity:
                continue

            customer = str(customer).strip()
            product_name = str(product_name).strip()

            is_valid, error_msg = validate_customer_name(customer)
            if not is_valid:
                continue

            product = product_map.get(product_name.lower().strip())
            product = product or product_map.get(product_name)
            if not product:
                continue
            product_id = product.id

            try:
                qty = int(quantity)
                if qty <= 0:
                    continue
            except ValueError:
                continue

            stockin_date = parse_date_value(stockin_date_val) or datetime.now()
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

            product.current_stock += qty

            log = InventoryLog(
                product_id=product_id,
                change_type='备货',
                change_quantity=qty,
                related_id=stockin_no,
                note='综合导入备货：' + stockin_no
            )
            db.add(log)

            count += 1
        except Exception as e:
            debug_messages.append(f"行{idx}: 异常 - {str(e)}")
            continue

    await db.commit()
    debug_messages.append(f"备货导入完成: 共导入 {count} 条")
    return count, debug_messages


async def import_stockouts_from_data(db: AsyncSession, data_list: list) -> Tuple[int, list]:
    """从数据列表导入出货"""
    count = 0
    debug_messages = []

    for idx, row_data in enumerate(data_list, start=2):
        try:
            product_identifier = row_data.get('产品名称') or row_data.get('产品') or row_data.get('69码') or row_data.get('条码')
            quantity = row_data.get('数量') or row_data.get('出货数量')
            customer = row_data.get('客户名称') or row_data.get('客户')
            stockout_date_val = row_data.get('时间') or row_data.get('出货时间')
            note = row_data.get('备注') or ''

            if not product_identifier or not quantity:
                continue

            product_identifier = str(product_identifier).strip()
            customer = str(customer).strip() if customer else ''

            if not customer:
                continue

            # 查找产品
            result = await db.execute(
                select(Product).where(
                    (Product.name == product_identifier) | (Product.barcode == product_identifier)
                )
            )
            product = result.scalar_one_or_none()
            if not product:
                continue

            try:
                qty = int(quantity)
                if qty <= 0:
                    continue
            except ValueError:
                continue

            if product.current_stock < qty:
                continue

            shipment_info = await calculate_available_shipment_quantity(db, product.id, customer)
            if shipment_info['available_quantity'] <= 0:
                continue

            if qty > shipment_info['available_quantity']:
                continue

            stockout_date = parse_date_value(stockout_date_val) or datetime.now()

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

            product.current_stock -= qty

            log = InventoryLog(
                product_id=product.id,
                change_type='出库',
                change_quantity=-qty,
                related_id='',
                note=f'综合导入出货：客户{customer}，数量{qty}'
            )
            db.add(log)

            count += 1
        except Exception as e:
            debug_messages.append(f"行{idx}: 异常 - {str(e)}")
            continue

    await db.commit()
    debug_messages.append(f"出货导入完成: 共导入 {count} 条")
    return count, debug_messages
