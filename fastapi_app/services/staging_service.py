"""
暂存区业务逻辑服务

从 Flask staging_order.py / staging_stockin.py / staging_stockout.py 提取的核心业务逻辑，适配异步 SQLAlchemy。
"""
import contextlib
import logging
import os
import tempfile
from datetime import datetime

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from fastapi_app.services.batch_service import (
    calculate_available_shipment_quantity,
    generate_order_number,
    generate_stockin_number,
    generate_stockout_number,
    parse_excel_file_async,
    process_order_deduction,
    read_excel_sheets_async,
)
from fastapi_app.shared_models import (
    InventoryLog,
    Order,
    Product,
    StagingOrder,
    StagingStockIn,
    StagingStockOut,
    StockIn,
    StockOut,
)
from fastapi_app.utils import parse_date_value, validate_customer_name

logger = logging.getLogger(__name__)


# ==================== 工具函数 ====================

async def _find_product_by_name_or_barcode(db: AsyncSession, name_or_barcode: str):
    """通过名称或条码查找产品"""
    result = await db.execute(
        select(Product).where(
            (Product.name == name_or_barcode) | (Product.barcode == name_or_barcode)
        )
    )
    return result.scalar_one_or_none()



# ==================== 暂存订单服务 ====================

async def get_staging_orders(db: AsyncSession, session_id: str) -> list[dict]:
    """获取指定会话的暂存订单列表"""
    result = await db.execute(
        select(StagingOrder)
        .where(StagingOrder.session_id == session_id, StagingOrder.status == 'pending')
        .order_by(StagingOrder.created_at.desc())
    )
    orders = result.scalars().all()
    return [order.to_dict() for order in orders]


async def clear_staging_orders_by_session(db: AsyncSession, session_id: str) -> int:
    """清空指定会话的暂存订单，返回删除数量"""
    result = await db.execute(
        delete(StagingOrder).where(StagingOrder.session_id == session_id)
    )
    await db.commit()
    return result.rowcount


async def clear_staging_orders(db: AsyncSession, session_id: str):
    """清空当前会话的暂存订单"""
    await clear_staging_orders_by_session(db, session_id)


async def delete_staging_order(db: AsyncSession, order_id: int):
    """删除单个暂存订单"""
    result = await db.execute(select(StagingOrder).where(StagingOrder.id == order_id))
    order = result.scalar_one_or_none()
    if not order:
        raise ValueError(f"暂存订单 {order_id} 不存在")
    await db.delete(order)
    await db.commit()


async def update_staging_order(db: AsyncSession, order_id: int, data: dict) -> dict:
    """更新暂存订单"""
    result = await db.execute(select(StagingOrder).where(StagingOrder.id == order_id))
    order = result.scalar_one_or_none()
    if not order:
        raise ValueError(f"暂存订单 {order_id} 不存在")

    if 'customer' in data:
        order.customer = data['customer']
    if 'product_name' in data:
        order.product_name = data['product_name']
        product = await _find_product_by_name_or_barcode(db, data['product_name'])
        if product:
            order.is_validated = True
            order.product_id = product.id
            order.validation_error = ''
        else:
            order.is_validated = False
            order.product_id = None
            order.validation_error = f'产品"{data["product_name"]}"不存在'
    if 'quantity' in data:
        qty = int(data['quantity'])
        if qty <= 0 or qty > 9999999:
            raise ValueError('数量必须在1-9999999之间')
        order.quantity = qty
    if 'deduct_stock' in data:
        order.deduct_stock = bool(data['deduct_stock'])
    if 'deduct_quantity' in data:
        deduct_qty = int(data['deduct_quantity'])
        if deduct_qty < 0:
            raise ValueError('抵扣数量不能为负数')
        order.deduct_quantity = deduct_qty
        order.deduct_stock = deduct_qty > 0
    if 'note' in data:
        order.note = data['note']

    await db.commit()
    await db.refresh(order)
    return order.to_dict()


async def confirm_staging_orders(
    db: AsyncSession, session_id: str
) -> tuple[int, list[str]]:
    """
    确认暂存订单 - 转移到正式订单表

    Returns:
        (confirmed_count, error_list)
    """
    from fastapi_app.shared.stock_concurrency import get_product_for_update

    result = await db.execute(
        select(StagingOrder).where(
            StagingOrder.session_id == session_id,
            StagingOrder.status == 'pending',
            StagingOrder.is_validated,
        )
    )
    staging_orders = result.scalars().all()

    if not staging_orders:
        return 0, ["没有可确认的订单"]

    confirmed = 0
    errors = []

    try:
        for staging in staging_orders:
            try:
                # 数量校验
                if staging.quantity <= 0 or staging.quantity > 9999999:
                    errors.append(f'订单{staging.customer}-{staging.product_name}数量无效: {staging.quantity}')
                    staging.status = 'rejected'
                    continue

                order_no = await generate_order_number(db)

                order = Order(
                    order_no=order_no,
                    customer=staging.customer,
                    order_date=staging.order_date or datetime.now(),
                    product_id=staging.product_id,
                    quantity=staging.quantity,
                    note=staging.note,
                    status='待备货',
                    order_type=staging.order_type or 'regular',
                    country=staging.country if staging.order_type == 'custom' else None,
                )
                db.add(order)
                await db.flush()

                # 使用悲观锁更新产品库存，防止并发修改
                product = await get_product_for_update(db, staging.product_id)
                if not product:
                    errors.append(f'订单{staging.customer}-{staging.product_name}产品不存在(ID:{staging.product_id})')
                    staging.status = 'rejected'
                    continue
                product.current_stock += staging.quantity

                log = InventoryLog(
                    product_id=staging.product_id,
                    change_type='订单',
                    change_quantity=staging.quantity,
                    related_id=order_no,
                    note=f'批量导入订单：{order_no}',
                )
                db.add(log)

                # 处理抵扣备货
                if staging.deduct_stock and staging.deduct_quantity and staging.deduct_quantity > 0:
                    try:
                        await process_order_deduction(
                            db, order,
                            staging.product_id,
                            staging.quantity,
                            deduct_stock=True,
                            custom_deduct_quantity=staging.deduct_quantity,
                            product=product,
                        )
                    except (ValueError, TypeError, OSError) as ded_err:
                        errors.append(
                            f'订单{staging.customer}-{staging.product_name}抵扣处理失败: {str(ded_err)}'
                        )

                staging.status = 'approved'
                confirmed += 1

            except (ValueError, TypeError, OSError) as e:
                errors.append(f'订单{staging.customer}-{staging.product_name}确认失败: {str(e)}')
                staging.status = 'rejected'

        # 删除被拒绝的暂存记录
        await db.execute(
            delete(StagingOrder).where(
                StagingOrder.session_id == session_id,
                StagingOrder.status == 'rejected',
            )
        )
        await db.commit()

    except (ValueError, TypeError, OSError) as e:
        await db.rollback()
        logger.error(f'确认暂存订单时发生错误: {str(e)}', exc_info=True)
        raise

    return confirmed, errors


async def import_staging_orders_from_excel(
    db: AsyncSession, file_content: bytes, session_id: str
) -> tuple[int, str, list[str]]:
    """
    从 Excel 文件导入订单到暂存区

    Args:
        db: 异步会话
        file_content: 上传文件的字节内容
        session_id: 会话ID

    Returns:
        (imported_count, message, errors)
    """
    # 清空当前会话暂存
    await db.execute(
        delete(StagingOrder).where(StagingOrder.session_id == session_id)
    )
    await db.commit()

    temp_path = None
    try:
        temp_fd, temp_path = tempfile.mkstemp(suffix='.xlsx')
        os.close(temp_fd)
        with open(temp_path, 'wb') as f:
            f.write(file_content)

        # 读取 Sheet 名称
        success, sheets, err = await read_excel_sheets_async(temp_path)
        if not success:
            return 0, f'Excel读取失败: {err}', []

        target_sheet = None
        for sheet in sheets:
            if '订单管理' in sheet:
                target_sheet = sheet
                break

        if not target_sheet:
            return 0, '没有找到"订单管理"Sheet', []

        # 解析数据
        success, data_list, err = await parse_excel_file_async(temp_path, target_sheet)
        if not success:
            return 0, f'数据解析失败: {err}', []

        # 预加载所有产品
        result = await db.execute(select(Product))
        all_products = result.scalars().all()
        product_map = {p.name.lower().strip(): p for p in all_products}
        product_map.update({p.barcode: p for p in all_products if p.barcode})

        imported = 0
        errors = []

        for idx, row_data in enumerate(data_list, start=2):
            try:
                customer = row_data.get('客户名称') or row_data.get('客户')
                product_name = row_data.get('产品名称') or row_data.get('产品')
                quantity = row_data.get('订单数量') or row_data.get('数量')
                deduct_flag = row_data.get('抵扣备货')
                note = row_data.get('备注')

                if not customer or not product_name or not quantity:
                    continue

                customer = str(customer).strip()
                product_name = str(product_name).strip()

                # 查找产品
                product = product_map.get(product_name.lower().strip())
                product = product or product_map.get(product_name)
                is_validated = False
                validation_error = ''
                product_id = None
                if product:
                    is_validated = True
                    product_id = product.id
                else:
                    validation_error = f'产品"{product_name}"不存在'

                try:
                    qty = int(quantity)
                except (ValueError, TypeError):
                    qty = 0

                # 解析抵扣标志
                deduct_quantity = 0
                deduct_stock_flag = False
                if deduct_flag:
                    deduct_str = str(deduct_flag).strip()
                    if deduct_str.isdigit():
                        deduct_quantity = int(deduct_str)
                        deduct_stock_flag = deduct_quantity > 0
                    elif deduct_str.lower() in ['是', 'yes', 'y']:
                        deduct_stock_flag = True
                        deduct_quantity = qty

                staging_order = StagingOrder(
                    session_id=session_id,
                    customer=customer,
                    product_name=product_name,
                    product_barcode='',
                    product_id=product_id,
                    quantity=qty,
                    deduct_stock=deduct_stock_flag,
                    deduct_quantity=deduct_quantity,
                    note=str(note).strip() if note else '',
                    is_validated=is_validated,
                    validation_error=validation_error,
                    status='pending',
                )
                db.add(staging_order)
                imported += 1

            except (ValueError, TypeError, OSError) as e:
                errors.append(f'第{idx}行处理失败: {str(e)}')
                continue

        await db.commit()

        result_msg = f'成功导入 {imported} 个订单到暂存区'
        if errors:
            result_msg += f'。错误: {"; ".join(errors[:5])}'
        return imported, result_msg, errors[:10] if errors else []

    except (ValueError, TypeError, OSError) as e:
        await db.rollback()
        logger.error(f'暂存订单导入失败: {str(e)}', exc_info=True)
        return 0, '导入失败，请稍后重试', []
    finally:
        if temp_path and os.path.exists(temp_path):
            with contextlib.suppress(OSError):
                os.unlink(temp_path)


# ==================== 暂存备货服务 ====================

async def get_staging_stockins(db: AsyncSession, session_id: str) -> list[dict]:
    """获取指定会话的暂存备货列表"""
    result = await db.execute(
        select(StagingStockIn)
        .where(StagingStockIn.session_id == session_id, StagingStockIn.status == 'pending')
        .order_by(StagingStockIn.created_at.desc())
    )
    stockins = result.scalars().all()
    return [stockin.to_dict() for stockin in stockins]


async def clear_staging_stockins(db: AsyncSession, session_id: str):
    """清空当前会话的暂存备货"""
    await db.execute(
        delete(StagingStockIn).where(StagingStockIn.session_id == session_id)
    )
    await db.commit()


async def delete_staging_stockin(db: AsyncSession, stockin_id: int):
    """删除单个暂存备货"""
    result = await db.execute(select(StagingStockIn).where(StagingStockIn.id == stockin_id))
    stockin = result.scalar_one_or_none()
    if not stockin:
        raise ValueError(f"暂存备货 {stockin_id} 不存在")
    await db.delete(stockin)
    await db.commit()


async def update_staging_stockin(db: AsyncSession, stockin_id: int, data: dict) -> dict:
    """更新暂存备货"""
    result = await db.execute(select(StagingStockIn).where(StagingStockIn.id == stockin_id))
    stockin = result.scalar_one_or_none()
    if not stockin:
        raise ValueError(f"暂存备货 {stockin_id} 不存在")

    if 'customer' in data:
        stockin.customer = data['customer']
    if 'product_name' in data:
        stockin.product_name = data['product_name']
        product = await _find_product_by_name_or_barcode(db, data['product_name'])
        if product:
            stockin.is_validated = True
            stockin.product_id = product.id
            stockin.validation_error = ''
        else:
            stockin.is_validated = False
            stockin.product_id = None
            stockin.validation_error = f'产品"{data["product_name"]}"不存在'
    if 'quantity' in data:
        stockin.quantity = int(data['quantity'])
    if 'stockin_date' in data:
        stockin.stockin_date = parse_date_value(data['stockin_date']) or datetime.now()
    if 'note' in data:
        stockin.note = data['note']

    await db.commit()
    await db.refresh(stockin)
    return stockin.to_dict()


async def confirm_staging_stockins(
    db: AsyncSession, session_id: str
) -> tuple[int, list[str]]:
    """确认暂存备货 - 转移到正式备货表"""
    from fastapi_app.shared.stock_concurrency import get_product_for_update

    result = await db.execute(
        select(StagingStockIn).where(
            StagingStockIn.session_id == session_id,
            StagingStockIn.status == 'pending',
            StagingStockIn.is_validated,
        )
    )
    staging_stockins = result.scalars().all()

    if not staging_stockins:
        return 0, ["没有可确认的备货"]

    confirmed = 0
    errors = []

    for staging in staging_stockins:
        try:
            if staging.quantity <= 0:
                errors.append(f'备货{staging.customer}-{staging.product_name}数量无效: {staging.quantity}')
                staging.status = 'rejected'
                continue

            stockin_no = await generate_stockin_number(db)

            stockin = StockIn(
                stockin_no=stockin_no,
                stockin_date=staging.stockin_date or datetime.now(),
                customer=staging.customer,
                product_id=staging.product_id,
                quantity=staging.quantity,
                note=staging.note,
            )
            db.add(stockin)

            # 使用悲观锁更新产品库存
            product = await get_product_for_update(db, staging.product_id)
            if not product:
                errors.append(f'备货{staging.customer}-{staging.product_name}产品不存在(ID:{staging.product_id})')
                staging.status = 'rejected'
                continue
            product.current_stock += staging.quantity

            log = InventoryLog(
                product_id=staging.product_id,
                change_type='备货',
                change_quantity=staging.quantity,
                related_id=stockin_no,
                note=f'批量导入备货：{stockin_no}',
            )
            db.add(log)

            staging.status = 'approved'
            confirmed += 1

        except (ValueError, TypeError, OSError) as e:
            errors.append(f'备货{staging.customer}-{staging.product_name}确认失败: {str(e)}')
            staging.status = 'rejected'

    await db.execute(
        delete(StagingStockIn).where(
            StagingStockIn.session_id == session_id,
            StagingStockIn.status == 'rejected',
        )
    )
    await db.commit()

    return confirmed, errors


async def import_staging_stockins_from_excel(
    db: AsyncSession, file_content: bytes, session_id: str
) -> tuple[int, str, list[str]]:
    """从 Excel 文件导入备货到暂存区"""
    # 清空当前会话暂存
    await db.execute(
        delete(StagingStockIn).where(StagingStockIn.session_id == session_id)
    )
    await db.commit()

    temp_path = None
    try:
        temp_fd, temp_path = tempfile.mkstemp(suffix='.xlsx')
        os.close(temp_fd)
        with open(temp_path, 'wb') as f:
            f.write(file_content)

        success, sheets, err = await read_excel_sheets_async(temp_path)
        if not success:
            return 0, f'Excel读取失败: {err}', []

        target_sheet = None
        for sheet in sheets:
            if '备货管理' in sheet:
                target_sheet = sheet
                break

        if not target_sheet:
            return 0, '没有找到"备货管理"Sheet', []

        success, data_list, err = await parse_excel_file_async(temp_path, target_sheet)
        if not success:
            return 0, f'数据解析失败: {err}', []

        # 预加载所有产品
        result = await db.execute(select(Product))
        all_products = result.scalars().all()
        product_map = {p.name.lower().strip(): p for p in all_products}
        product_map.update({p.barcode: p for p in all_products if p.barcode})

        imported = 0
        errors = []

        for idx, row_data in enumerate(data_list, start=2):
            try:
                customer = row_data.get('客户名称') or row_data.get('客户')
                product_name = row_data.get('产品名称') or row_data.get('产品')
                quantity = row_data.get('备货数量') or row_data.get('数量')
                stockin_date_val = row_data.get('时间') or row_data.get('备货时间')
                note = row_data.get('备注')

                if not customer or not product_name or not quantity:
                    continue

                customer = str(customer).strip()
                product_name = str(product_name).strip()

                # 客户名称验证
                is_valid, error_msg = validate_customer_name(customer)
                if not is_valid:
                    errors.append(f'第{idx}行：{error_msg}')
                    continue

                # 查找产品
                product = product_map.get(product_name.lower().strip())
                product = product or product_map.get(product_name)
                is_validated = False
                validation_error = ''
                product_id = None
                if product:
                    is_validated = True
                    product_id = product.id
                else:
                    validation_error = f'产品"{product_name}"不存在'

                try:
                    qty = int(quantity)
                except (ValueError, TypeError):
                    qty = 0

                stockin_date = parse_date_value(stockin_date_val) or datetime.now()

                staging_stockin = StagingStockIn(
                    session_id=session_id,
                    customer=customer,
                    stockin_date=stockin_date or datetime.now(),
                    product_name=product_name,
                    product_barcode='',
                    product_id=product_id,
                    quantity=qty,
                    note=str(note).strip() if note else '',
                    is_validated=is_validated,
                    validation_error=validation_error,
                    status='pending',
                )
                db.add(staging_stockin)
                imported += 1

            except (ValueError, TypeError, OSError) as e:
                errors.append(f'第{idx}行处理失败: {str(e)}')
                continue

        await db.commit()

        result_msg = f'成功导入 {imported} 个备货到暂存区'
        if errors:
            result_msg += f'。错误: {"; ".join(errors[:5])}'
        return imported, result_msg, errors[:10] if errors else []

    except (ValueError, TypeError, OSError) as e:
        await db.rollback()
        logger.error(f'暂存备货导入失败: {str(e)}', exc_info=True)
        return 0, '导入失败，请稍后重试', []
    finally:
        if temp_path and os.path.exists(temp_path):
            with contextlib.suppress(OSError):
                os.unlink(temp_path)


# ==================== 暂存出货服务 ====================

async def get_staging_stockouts(db: AsyncSession, session_id: str) -> list[dict]:
    """获取指定会话的暂存出货列表"""
    result = await db.execute(
        select(StagingStockOut)
        .where(StagingStockOut.session_id == session_id, StagingStockOut.status == 'pending')
        .order_by(StagingStockOut.created_at.desc())
    )
    stockouts = result.scalars().all()
    return [stockout.to_dict() for stockout in stockouts]


async def clear_staging_stockouts(db: AsyncSession, session_id: str):
    """清空当前会话的暂存出货"""
    await db.execute(
        delete(StagingStockOut).where(StagingStockOut.session_id == session_id)
    )
    await db.commit()


async def delete_staging_stockout(db: AsyncSession, stockout_id: int):
    """删除单个暂存出货"""
    result = await db.execute(select(StagingStockOut).where(StagingStockOut.id == stockout_id))
    stockout = result.scalar_one_or_none()
    if not stockout:
        raise ValueError(f"暂存出货 {stockout_id} 不存在")
    await db.delete(stockout)
    await db.commit()


async def update_staging_stockout(db: AsyncSession, stockout_id: int, data: dict) -> dict:
    """更新暂存出货"""
    result = await db.execute(select(StagingStockOut).where(StagingStockOut.id == stockout_id))
    stockout = result.scalar_one_or_none()
    if not stockout:
        raise ValueError(f"暂存出货 {stockout_id} 不存在")

    if 'customer' in data:
        stockout.customer = data['customer']
    if 'product_name' in data:
        stockout.product_name = data['product_name']
        product = await _find_product_by_name_or_barcode(db, data['product_name'])
        if product:
            stockout.is_validated = True
            stockout.product_id = product.id
            stockout.validation_error = ''
        else:
            stockout.is_validated = False
            stockout.product_id = None
            stockout.validation_error = f'产品"{data["product_name"]}"不存在'
    if 'quantity' in data:
        stockout.quantity = int(data['quantity'])
        if stockout.product_id:
            product = await db.get(Product, stockout.product_id)
            if product:
                if product.current_stock >= stockout.quantity:
                    stockout.stock_check_passed = True
                    stockout.stock_check_message = f'库存充足，当前库存: {product.current_stock}'
                else:
                    stockout.stock_check_passed = False
                    stockout.stock_check_message = f'库存不足，当前库存: {product.current_stock}'
    if 'stockout_date' in data:
        stockout.stockout_date = parse_date_value(data['stockout_date']) or datetime.now()
    if 'note' in data:
        stockout.note = data['note']

    await db.commit()
    await db.refresh(stockout)
    return stockout.to_dict()


async def confirm_staging_stockouts(
    db: AsyncSession, session_id: str
) -> tuple[int, list[str]]:
    """确认暂存出货 - 转移到正式出货表"""
    from fastapi_app.shared.stock_concurrency import get_product_for_update

    result = await db.execute(
        select(StagingStockOut).where(
            StagingStockOut.session_id == session_id,
            StagingStockOut.status == 'pending',
            StagingStockOut.is_validated,
            StagingStockOut.stock_check_passed,
        )
    )
    staging_stockouts = result.scalars().all()

    if not staging_stockouts:
        return 0, ["没有可确认的出货（请确保所有出货库存检查通过）"]

    confirmed = 0
    errors = []

    for staging in staging_stockouts:
        try:
            if not staging.customer:
                errors.append(f'出货{staging.product_name}确认失败: 必须选择客户，需要有订单支持')
                staging.status = 'rejected'
                continue

            product = await get_product_for_update(db, staging.product_id)
            if not product:
                errors.append(f'出货{staging.customer}-{staging.product_name}确认失败: 产品不存在')
                staging.status = 'rejected'
                continue

            if product.current_stock < staging.quantity:
                errors.append(f'出货{staging.customer}-{staging.product_name}确认失败: 库存不足')
                staging.status = 'rejected'
                continue

            shipment_info = await calculate_available_shipment_quantity(
                db, staging.product_id, staging.customer,
                order_type=staging.order_type or 'regular',
                country=staging.country or None
            )
            if shipment_info['available_quantity'] <= 0:
                errors.append(f'出货{staging.customer}-{staging.product_name}确认失败: 没有可用的订单支持出货')
                staging.status = 'rejected'
                continue

            if staging.quantity > shipment_info['available_quantity']:
                errors.append(
                    f'出货{staging.customer}-{staging.product_name}确认失败: '
                    f'出货数量{staging.quantity}超过可出货量{shipment_info["available_quantity"]}'
                )
                staging.status = 'rejected'
                continue

            # 创建出货记录（按订单拆分）
            remaining_qty = staging.quantity
            affected_order_ids = set()
            for order_detail in shipment_info['orders']:
                if remaining_qty <= 0:
                    break
                if order_detail['available'] > 0:
                    ship_qty = min(remaining_qty, order_detail['available'])
                    stockout_no = await generate_stockout_number(db)
                    stockout = StockOut(
                        stockout_no=stockout_no,
                        stockout_date=staging.stockout_date or datetime.now(),
                        product_id=staging.product_id,
                        quantity=ship_qty,
                        customer=staging.customer,
                        order_id=order_detail['order_id'],
                        note=staging.note,
                    )
                    db.add(stockout)
                    affected_order_ids.add(order_detail['order_id'])
                    remaining_qty -= ship_qty

            product.current_stock -= staging.quantity

            # 更新关联订单状态：已备货/部分备货 -> 待出货
            for oid in affected_order_ids:
                order = await db.get(Order, oid)
                if order and order.status in ('已备货', '部分备货', '待备货'):
                    order.transition_to('待出货')

            log = InventoryLog(
                product_id=staging.product_id,
                change_type='出库',
                change_quantity=-staging.quantity,
                related_id='',
                note=f'批量导入出货：客户{staging.customer}，数量{staging.quantity}',
            )
            db.add(log)

            staging.status = 'approved'
            confirmed += 1

        except (ValueError, TypeError, OSError) as e:
            errors.append(f'出货{staging.customer}-{staging.product_name}确认失败: {str(e)}')
            staging.status = 'rejected'

    await db.execute(
        delete(StagingStockOut).where(
            StagingStockOut.session_id == session_id,
            StagingStockOut.status == 'rejected',
        )
    )
    await db.commit()

    return confirmed, errors


async def import_staging_stockouts_from_excel(
    db: AsyncSession, file_content: bytes, session_id: str
) -> tuple[int, str, list[str]]:
    """从 Excel 文件导入出货到暂存区"""
    # 清空当前会话暂存
    await db.execute(
        delete(StagingStockOut).where(StagingStockOut.session_id == session_id)
    )
    await db.commit()

    temp_path = None
    try:
        temp_fd, temp_path = tempfile.mkstemp(suffix='.xlsx')
        os.close(temp_fd)
        with open(temp_path, 'wb') as f:
            f.write(file_content)

        success, sheets, err = await read_excel_sheets_async(temp_path)
        if not success:
            return 0, f'Excel读取失败: {err}', []

        target_sheet = None
        for sheet in sheets:
            if '出货管理' in sheet:
                target_sheet = sheet
                break

        if not target_sheet:
            return 0, '没有找到"出货管理"Sheet', []

        success, data_list, err = await parse_excel_file_async(temp_path, target_sheet)
        if not success:
            return 0, f'数据解析失败: {err}', []

        # 预加载所有产品
        result = await db.execute(select(Product))
        all_products = result.scalars().all()
        product_map = {p.name.lower().strip(): p for p in all_products}
        product_map.update({p.barcode: p for p in all_products if p.barcode})

        imported = 0
        errors = []

        for idx, row_data in enumerate(data_list, start=2):
            try:
                product_identifier = row_data.get('产品名称') or row_data.get('产品')
                quantity = row_data.get('出货数量') or row_data.get('数量')
                customer = row_data.get('客户名称') or row_data.get('客户')
                stockout_date_val = row_data.get('时间') or row_data.get('出货时间')
                note = row_data.get('备注')
                country_val = row_data.get('国家') or row_data.get('国家名称')

                # 国家列有值=定制订单，空值/NaN=常规订单
                if not country_val or (isinstance(country_val, float) and country_val != country_val):
                    country_parsed = ''
                else:
                    country_parsed = str(country_val).strip()
                order_type_parsed = 'custom' if country_parsed else 'regular'

                if not product_identifier or not quantity:
                    continue

                product_identifier = str(product_identifier).strip()
                customer = str(customer).strip() if customer else ''

                # 查找产品
                product = product_map.get(product_identifier.lower().strip())
                product = product or product_map.get(product_identifier)
                is_validated = False
                validation_error = ''
                product_id = None
                product_name = product_identifier
                stock_check_passed = False
                stock_check_message = ''

                if product:
                    is_validated = True
                    product_id = product.id
                    product_name = product.name

                    try:
                        qty = int(quantity)
                        if qty <= 0:
                            stock_check_message = '出货数量必须大于0'
                        elif product.current_stock < qty:
                            stock_check_message = f'库存不足，当前库存: {product.current_stock}'
                        else:
                            stock_check_passed = True
                            stock_check_message = f'库存充足，当前库存: {product.current_stock}'
                    except ValueError:
                        stock_check_message = '数量格式错误'
                else:
                    validation_error = f'产品"{product_identifier}"不存在'

                try:
                    qty = int(quantity)
                except (ValueError, TypeError):
                    qty = 0

                stockout_date = parse_date_value(stockout_date_val) or datetime.now()

                # order_type 已由 country 列决定

                staging_stockout = StagingStockOut(
                    session_id=session_id,
                    customer=customer,
                    stockout_date=stockout_date or datetime.now(),
                    product_name=product_name,
                    product_barcode='',
                    product_id=product_id,
                    quantity=qty,
                    note=str(note).strip() if note else '',
                    order_type=order_type_parsed,
                    country=country_parsed,
                    is_validated=is_validated,
                    validation_error=validation_error,
                    stock_check_passed=stock_check_passed,
                    stock_check_message=stock_check_message,
                    status='pending',
                )
                db.add(staging_stockout)
                imported += 1

            except (ValueError, TypeError, OSError) as e:
                errors.append(f'第{idx}行处理失败: {str(e)}')
                continue

        await db.commit()

        result_msg = f'成功导入 {imported} 个出货到暂存区'
        if errors:
            result_msg += f'。错误: {"; ".join(errors[:5])}'
        return imported, result_msg, errors[:10] if errors else []

    except (ValueError, TypeError, OSError) as e:
        await db.rollback()
        logger.error(f'暂存出货导入失败: {str(e)}', exc_info=True)
        return 0, '导入失败，请稍后重试', []
    finally:
        if temp_path and os.path.exists(temp_path):
            with contextlib.suppress(OSError):
                os.unlink(temp_path)
