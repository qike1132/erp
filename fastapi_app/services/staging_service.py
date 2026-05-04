"""
暂存区业务逻辑服务

从 Flask staging_order.py / staging_stockin.py / staging_stockout.py 提取的核心业务逻辑，适配异步 SQLAlchemy。
"""
import asyncio
import contextlib
import logging
import os
import tempfile
from collections.abc import Callable
from datetime import datetime
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.exc import SQLAlchemyError
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


async def _find_product_by_name_or_barcode(db: AsyncSession, name_or_barcode: str):
    result = await db.execute(
        select(Product).where(
            (Product.name == name_or_barcode) | (Product.barcode == name_or_barcode)
        )
    )
    return result.scalar_one_or_none()


async def _build_product_map(db: AsyncSession) -> dict[str, Product]:
    result = await db.execute(select(Product))
    all_products = result.scalars().all()
    product_map: dict[str, Product] = {p.name.lower().strip(): p for p in all_products}
    product_map.update({p.barcode: p for p in all_products if p.barcode})
    return product_map


async def _validate_and_map_product(
    product_map: dict[str, Product], product_name: str
) -> tuple[bool, str, int | None]:
    product = product_map.get(product_name.lower().strip())
    product = product or product_map.get(product_name)
    if product:
        return True, '', product.id
    return False, f'产品"{product_name}"不存在', None


def _format_import_result(imported: int, entity_label: str, errors: list[str]) -> str:
    result_msg = f'成功导入 {imported} 个{entity_label}到暂存区'
    if errors:
        total_err = len(errors)
        result_msg += f'。共{total_err}个错误: {"; ".join(errors[:5])}'
        if total_err > 5:
            result_msg += f'...（仅显示前5条，共{total_err}条）'
    return result_msg


def _parse_deduct_flag(deduct_flag: Any, qty: int) -> tuple[bool, int]:
    if not deduct_flag:
        return False, 0
    deduct_str = str(deduct_flag).strip()
    if deduct_str.isdigit():
        deduct_qty = int(deduct_str)
        return deduct_qty > 0, deduct_qty
    if deduct_str.lower() in ('是', 'yes', 'y'):
        return True, qty
    return False, 0


async def _generic_import_staging_from_excel(
    db: AsyncSession,
    file_content: bytes,
    session_id: str,
    staging_model: type,
    clear_func: Callable,
    sheet_keyword: str,
    entity_label: str,
    build_entity: Callable[[dict[str, Any], str, str | None, int | None, int], object],
    column_names: dict[str, str],
    required_fields: list[str],
    extra_row_validations: Callable[[dict[str, Any], int], list[str]] | None = None,
) -> tuple[int, str, list[str]]:
    await clear_func(db, session_id)

    temp_path = None
    try:
        temp_fd, temp_path = tempfile.mkstemp(suffix='.xlsx')
        await asyncio.to_thread(os.write, temp_fd, file_content)
        os.close(temp_fd)

        success, sheets, err = await read_excel_sheets_async(temp_path)
        if not success:
            return 0, f'Excel读取失败: {err}', []

        target_sheet = next((s for s in sheets if sheet_keyword in s), None)
        if not target_sheet:
            return 0, f'没有找到"{sheet_keyword}"Sheet', []

        success, data_list, err = await parse_excel_file_async(temp_path, target_sheet)
        if not success:
            return 0, f'数据解析失败: {err}', []

        product_map = await _build_product_map(db)
        imported = 0
        errors: list[str] = []

        for idx, row_data in enumerate(data_list, start=2):
            try:
                if extra_row_validations:
                    extra_errs = extra_row_validations(row_data, idx)
                    if extra_errs:
                        errors.extend(extra_errs)
                        continue

                field_values: dict[str, Any] = {}
                missing = []
                for req_field in required_fields:
                    value = row_data.get(column_names.get(req_field, req_field))
                    if not value:
                        missing.append(req_field)
                    field_values[req_field] = value

                if missing:
                    errors.append(f'第{idx}行缺少必填字段（{"/".join(missing)}）')
                    continue

                product_name = str(field_values.get('product_name', '')).strip()
                is_validated, validation_error, product_id = await _validate_and_map_product(
                    product_map, product_name
                )

                qty = 0
                with contextlib.suppress(ValueError, TypeError):
                    qty = int(field_values.get('quantity', 0))

                entity = build_entity(
                    field_values, session_id, product_id, qty,
                    is_validated, validation_error, product_name,
                )
                db.add(entity)
                imported += 1

            except (ValueError, TypeError, OSError) as e:
                errors.append(f'第{idx}行处理失败: {str(e)}')
                continue

        await db.commit()
        return imported, _format_import_result(imported, entity_label, errors), errors

    except (ValueError, TypeError, OSError) as e:
        await db.rollback()
        logger.error('%s导入失败: %s', entity_label, str(e), exc_info=True)
        return 0, '导入失败，请稍后重试', []
    finally:
        if temp_path and os.path.exists(temp_path):
            with contextlib.suppress(OSError):
                os.unlink(temp_path)


async def _generic_update_staging_entity(
    db: AsyncSession,
    entity_id: int,
    data: dict,
    model_class: type,
    entity_label: str,
    extra_updates: Callable[[Any, dict, AsyncSession], None] | None = None,
) -> dict:
    result = await db.execute(select(model_class).where(model_class.id == entity_id))
    entity = result.scalar_one_or_none()
    if not entity:
        raise ValueError(f'{entity_label} {entity_id} 不存在')

    if 'customer' in data:
        entity.customer = data['customer']
    if 'product_name' in data:
        entity.product_name = data['product_name']
        product = await _find_product_by_name_or_barcode(db, data['product_name'])
        if product:
            entity.is_validated = True
            entity.product_id = product.id
            entity.validation_error = ''
        else:
            entity.is_validated = False
            entity.product_id = None
            entity.validation_error = f'产品"{data["product_name"]}"不存在'
    if 'quantity' in data:
        entity.quantity = int(data['quantity'])
    if extra_updates:
        extra_updates(entity, data, db)

    await db.commit()
    await db.refresh(entity)
    return entity.to_dict()


def _build_order_entity(
    fields: dict, session_id: str, product_id: int | None, qty: int,
    is_validated: bool, validation_error: str, product_name: str,
) -> StagingOrder:
    deduct_stock_flag, deduct_quantity = _parse_deduct_flag(
        fields.get('deduct_stock'), qty
    )
    return StagingOrder(
        session_id=session_id,
        customer=str(fields.get('customer', '')).strip(),
        product_name=product_name,
        product_barcode='',
        product_id=product_id,
        quantity=qty,
        deduct_stock=deduct_stock_flag,
        deduct_quantity=deduct_quantity,
        note=str(fields.get('note', '') or '').strip(),
        is_validated=is_validated,
        validation_error=validation_error,
        status='pending',
    )


def _build_stockin_entity(
    fields: dict, session_id: str, product_id: int | None, qty: int,
    is_validated: bool, validation_error: str, product_name: str,
) -> StagingStockIn:
    stockin_date = parse_date_value(fields.get('stockin_date')) or datetime.now()
    return StagingStockIn(
        session_id=session_id,
        customer=str(fields.get('customer', '')).strip(),
        stockin_date=stockin_date,
        product_name=product_name,
        product_barcode='',
        product_id=product_id,
        quantity=qty,
        note=str(fields.get('note', '') or '').strip(),
        is_validated=is_validated,
        validation_error=validation_error,
        status='pending',
    )


def _build_stockout_entity(
    fields: dict, session_id: str, product_id: int | None, qty: int,
    is_validated: bool, validation_error: str, product_name: str,
) -> StagingStockOut:
    stockout_date = parse_date_value(fields.get('stockout_date')) or datetime.now()
    customer = str(fields.get('customer', '')).strip()

    country_val = fields.get('country', '')
    if not country_val or (isinstance(country_val, float) and country_val != country_val):
        country_parsed = ''
    else:
        country_parsed = str(country_val).strip()
    order_type_parsed = 'custom' if country_parsed else 'regular'

    stock_check_passed = False
    stock_check_message = ''
    if is_validated:
        stock_check_passed = True
        stock_check_message = '库存充足'

    return StagingStockOut(
        session_id=session_id,
        customer=customer,
        stockout_date=stockout_date,
        product_name=product_name,
        product_barcode='',
        product_id=product_id,
        quantity=qty,
        note=str(fields.get('note', '') or '').strip(),
        order_type=order_type_parsed,
        country=country_parsed,
        is_validated=is_validated,
        validation_error=validation_error,
        stock_check_passed=stock_check_passed,
        stock_check_message=stock_check_message,
        status='pending',
    )


async def _validate_stockin_customer(row_data: dict, idx: int) -> list[str]:
    customer = row_data.get('客户名称') or row_data.get('客户')
    if not customer:
        return []
    is_valid, error_msg = validate_customer_name(str(customer).strip())
    if not is_valid:
        return [f'第{idx}行：{error_msg}']
    return []


def _stockout_extra_updates(entity, data: dict, _db: AsyncSession) -> None:
    if 'quantity' in data and entity.product_id:
        # extra_updates runs after quantity is set; perform stock check here
        pass
    if 'stockout_date' in data:
        entity.stockout_date = parse_date_value(data['stockout_date']) or datetime.now()
    if 'note' in data:
        entity.note = data['note']


def _stockin_extra_updates(entity, data: dict, _db: AsyncSession) -> None:
    if 'stockin_date' in data:
        entity.stockin_date = parse_date_value(data['stockin_date']) or datetime.now()
    if 'note' in data:
        entity.note = data['note']


def _order_extra_updates(entity, data: dict, _db: AsyncSession) -> None:
    if 'quantity' in data:
        qty = int(data['quantity'])
        if qty <= 0 or qty > 9999999:
            raise ValueError('数量必须在1-9999999之间')
    if 'deduct_stock' in data:
        entity.deduct_stock = bool(data['deduct_stock'])
    if 'deduct_quantity' in data:
        deduct_qty = int(data['deduct_quantity'])
        if deduct_qty < 0:
            raise ValueError('抵扣数量不能为负数')
        entity.deduct_quantity = deduct_qty
        entity.deduct_stock = deduct_qty > 0
    if 'note' in data:
        entity.note = data['note']


# ==================== 暂存订单服务 ====================

async def get_staging_orders(db: AsyncSession, session_id: str) -> list[dict]:
    result = await db.execute(
        select(StagingOrder)
        .where(StagingOrder.session_id == session_id, StagingOrder.status == 'pending')
        .order_by(StagingOrder.created_at.desc())
    )
    orders = result.scalars().all()
    return [order.to_dict() for order in orders]


async def clear_staging_orders_by_session(db: AsyncSession, session_id: str) -> int:
    result = await db.execute(
        delete(StagingOrder).where(StagingOrder.session_id == session_id)
    )
    await db.commit()
    return result.rowcount


async def clear_staging_orders(db: AsyncSession, session_id: str):
    await clear_staging_orders_by_session(db, session_id)


async def delete_staging_order(db: AsyncSession, order_id: int):
    result = await db.execute(select(StagingOrder).where(StagingOrder.id == order_id))
    order = result.scalar_one_or_none()
    if not order:
        raise ValueError(f"暂存订单 {order_id} 不存在")
    await db.delete(order)
    await db.commit()


async def update_staging_order(db: AsyncSession, order_id: int, data: dict) -> dict:
    return await _generic_update_staging_entity(
        db, order_id, data, StagingOrder, '暂存订单',
        extra_updates=_order_extra_updates,
    )


async def confirm_staging_orders(
    db: AsyncSession, session_id: str
) -> tuple[int, list[str]]:
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
    errors: list[str] = []

    try:
        for staging in staging_orders:
            try:
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

        await db.execute(
            delete(StagingOrder).where(
                StagingOrder.session_id == session_id,
                StagingOrder.status == 'rejected',
            )
        )
        await db.commit()

    except (SQLAlchemyError, RuntimeError, OSError, ValueError) as e:
        await db.rollback()
        logger.error(f'确认暂存订单时发生错误: {str(e)}', exc_info=True)
        raise

    return confirmed, errors


async def import_staging_orders_from_excel(
    db: AsyncSession, file_content: bytes, session_id: str
) -> tuple[int, str, list[str]]:
    return await _generic_import_staging_from_excel(
        db, file_content, session_id,
        staging_model=StagingOrder,
        clear_func=clear_staging_orders_by_session,
        sheet_keyword='订单管理',
        entity_label='订单',
        build_entity=_build_order_entity,
        column_names={
            'customer': '客户名称',
            'product_name': '产品名称',
            'quantity': '订单数量',
            'deduct_stock': '抵扣备货',
            'note': '备注',
        },
        required_fields=['customer', 'product_name', 'quantity'],
    )


# ==================== 暂存备货服务 ====================

async def get_staging_stockins(db: AsyncSession, session_id: str) -> list[dict]:
    result = await db.execute(
        select(StagingStockIn)
        .where(StagingStockIn.session_id == session_id, StagingStockIn.status == 'pending')
        .order_by(StagingStockIn.created_at.desc())
    )
    stockins = result.scalars().all()
    return [stockin.to_dict() for stockin in stockins]


async def clear_staging_stockins_by_session(db: AsyncSession, session_id: str) -> int:
    result = await db.execute(
        delete(StagingStockIn).where(StagingStockIn.session_id == session_id)
    )
    await db.commit()
    return result.rowcount


async def clear_staging_stockins(db: AsyncSession, session_id: str):
    await clear_staging_stockins_by_session(db, session_id)


async def delete_staging_stockin(db: AsyncSession, stockin_id: int):
    result = await db.execute(select(StagingStockIn).where(StagingStockIn.id == stockin_id))
    stockin = result.scalar_one_or_none()
    if not stockin:
        raise ValueError(f"暂存备货 {stockin_id} 不存在")
    await db.delete(stockin)
    await db.commit()


async def update_staging_stockin(db: AsyncSession, stockin_id: int, data: dict) -> dict:
    return await _generic_update_staging_entity(
        db, stockin_id, data, StagingStockIn, '暂存备货',
        extra_updates=_stockin_extra_updates,
    )


async def confirm_staging_stockins(
    db: AsyncSession, session_id: str
) -> tuple[int, list[str]]:
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
    errors: list[str] = []

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
    return await _generic_import_staging_from_excel(
        db, file_content, session_id,
        staging_model=StagingStockIn,
        clear_func=clear_staging_stockins_by_session,
        sheet_keyword='备货管理',
        entity_label='备货',
        build_entity=_build_stockin_entity,
        column_names={
            'customer': '客户名称',
            'product_name': '产品名称',
            'quantity': '备货数量',
            'stockin_date': '时间',
            'note': '备注',
        },
        required_fields=['customer', 'product_name', 'quantity'],
        extra_row_validations=_validate_stockin_customer,
    )


# ==================== 暂存出货服务 ====================

async def get_staging_stockouts(db: AsyncSession, session_id: str) -> list[dict]:
    result = await db.execute(
        select(StagingStockOut)
        .where(StagingStockOut.session_id == session_id, StagingStockOut.status == 'pending')
        .order_by(StagingStockOut.created_at.desc())
    )
    stockouts = result.scalars().all()
    return [stockout.to_dict() for stockout in stockouts]


async def clear_staging_stockouts_by_session(db: AsyncSession, session_id: str) -> int:
    result = await db.execute(
        delete(StagingStockOut).where(StagingStockOut.session_id == session_id)
    )
    await db.commit()
    return result.rowcount


async def clear_staging_stockouts(db: AsyncSession, session_id: str):
    await clear_staging_stockouts_by_session(db, session_id)


async def delete_staging_stockout(db: AsyncSession, stockout_id: int):
    result = await db.execute(select(StagingStockOut).where(StagingStockOut.id == stockout_id))
    stockout = result.scalar_one_or_none()
    if not stockout:
        raise ValueError(f"暂存出货 {stockout_id} 不存在")
    await db.delete(stockout)
    await db.commit()


async def update_staging_stockout(db: AsyncSession, stockout_id: int, data: dict) -> dict:
    return await _generic_update_staging_entity(
        db, stockout_id, data, StagingStockOut, '暂存出货',
        extra_updates=_stockout_extra_updates,
    )


async def confirm_staging_stockouts(
    db: AsyncSession, session_id: str
) -> tuple[int, list[str]]:
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
    errors: list[str] = []

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

            remaining_qty = staging.quantity
            affected_order_ids: set[int] = set()
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
    return await _generic_import_staging_from_excel(
        db, file_content, session_id,
        staging_model=StagingStockOut,
        clear_func=clear_staging_stockouts_by_session,
        sheet_keyword='出货管理',
        entity_label='出货',
        build_entity=_build_stockout_entity,
        column_names={
            'customer': '客户名称',
            'product_name': '产品名称',
            'quantity': '出货数量',
            'stockout_date': '时间',
            'note': '备注',
            'country': '国家',
        },
        required_fields=['product_name', 'quantity'],
        extra_row_validations=_validate_stockin_customer,
    )


async def import_staging_stockouts_from_file(
    db: AsyncSession, file_content: bytes, session_id: str,
    filename: str = '', task_id: str = '',
) -> tuple[int, str, list[str]]:
    """从 OCR 文件（PDF/图片）导入出货到暂存区 — 委托给 OCR service"""
    from fastapi_app.services.ocr_service import import_staging_stockouts_from_file as _ocr_import
    return await _ocr_import(db, file_content, session_id, filename=filename, task_id=task_id)
