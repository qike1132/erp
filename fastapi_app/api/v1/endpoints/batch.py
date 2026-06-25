"""
批量导入 FastAPI 端点

从 Flask batch.py 迁移的批量导入功能。

职责：
- 提供统一导入模板下载接口
- 提供订单、备货、出库、皮套出库/入库、产品的批量导入接口
- 提供综合批量导入接口（支持4个Sheet自动识别）
"""
import asyncio
import logging
import os
import tempfile
from contextlib import asynccontextmanager, suppress
from datetime import datetime

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from fastapi_app.core.database import get_async_db
from fastapi_app.core.deps import require_permission
from fastapi_app.schemas.batch import BatchImportResult, ComprehensiveImportResult
from fastapi_app.services.batch_service import (
    calculate_available_shipment_quantity,
    import_orders_from_data,
    import_products_from_data,
    import_stockins_from_data,
    import_stockouts_from_data,
    parse_date_value,
    parse_excel_file_async,
    process_order_deduction,
    read_excel_sheets_async,
    validate_customer_name,
)
from fastapi_app.services.numbering import (
    generate_case_stockin_number,
    generate_case_stockout_number,
    generate_order_number,
    generate_stockin_number,
    generate_stockout_number,
)
from fastapi_app.shared.stock_concurrency import get_product_for_update
from fastapi_app.shared_models import (
    Case,
    CaseInventoryLog,
    CaseStockIn,
    CaseStockOut,
    InventoryLog,
    Order,
    Product,
    StockIn,
    StockOut,
    User,
)

# 批量上传文件大小上限（5MB）
MAX_BATCH_UPLOAD_SIZE = 5 * 1024 * 1024
logger = logging.getLogger(__name__)
router = APIRouter()


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
                await db.rollback()
                await db.begin_nested()
                logger.error(f'综合导入 - 订单Sheet {sheet_name} 导入失败: {order_e}', exc_info=True)
                results.errors.append(f'Sheet {sheet_name} 导入失败')
        elif sheet_type == 'stockin':
            try:
                count, _ = await import_stockins_from_data(db, data_list)
                results.imported['stockins'] += count
            except (ValueError, TypeError, SQLAlchemyError) as stockin_e:
                await db.rollback()
                await db.begin_nested()
                logger.error(f'综合导入 - 备货Sheet {sheet_name} 导入失败: {stockin_e}', exc_info=True)
                results.errors.append(f'Sheet {sheet_name} 导入失败')
        elif sheet_type == 'stockout':
            try:
                count, _ = await import_stockouts_from_data(db, data_list)
                results.imported['stockouts'] += count
            except (ValueError, TypeError, SQLAlchemyError) as stockout_e:
                await db.rollback()
                await db.begin_nested()
                logger.error(f'综合导入 - 出货Sheet {sheet_name} 导入失败: {stockout_e}', exc_info=True)
                results.errors.append(f'Sheet {sheet_name} 导入失败')
    except (ValueError, TypeError, SQLAlchemyError) as exc:
        await db.rollback()
        await db.begin_nested()
        logger.error(f'综合导入 - Sheet {sheet_name} 处理失败: {exc}', exc_info=True)
        results.errors.append(f'Sheet {sheet_name} 导入失败')


@router.get('/download-template', summary='下载统一导入模板')
async def download_template(
    current_user: User = Depends(require_permission('batch_import')),
) -> 'Response':
    """下载统一导入模板 - 直接读取静态文件。

    Args:
        current_user: 当前登录用户（仅需通过权限校验）。

    Returns:
        Response: Excel 文件流响应。

    Raises:
        HTTPException: 模板文件不存在时抛出 404；读取失败时抛出 500。
    """
    from urllib.parse import quote

    from fastapi.responses import Response
    template_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))),
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


@router.post('/import-orders', response_model=BatchImportResult, summary='批量导入订单')
async def batch_import_orders(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(require_permission('batch_import')),
) -> BatchImportResult:
    """批量导入订单 - 支持统一模板格式。

    Args:
        file: 上传的 Excel 文件（.xlsx 格式）。
        db: 异步数据库会话（读写主库）。
        current_user: 当前登录用户（仅需通过权限校验）。

    Returns:
        BatchImportResult: 包含导入结果、消息和条数的响应。
    """
    if (err := _validate_xlsx_file(file)):
        return err
    try:
        data_list, err = await _read_excel_sheets(file, ['订单管理'], '没有找到"订单管理"Sheet')
        if err:
            return BatchImportResult(success=False, message=err)
        # 构建产品映射，支持按名称（小写）和条码查找
        result = await db.execute(select(Product))
        all_products = result.scalars().all()
        product_map = {prod.name.lower().strip(): prod for prod in all_products}
        product_map.update({prod.barcode: prod for prod in all_products if prod.barcode})
        imported = 0
        skipped = 0
        errors = []
        for row_data in data_list:
            try:
                customer = row_data.get('客户名称') or row_data.get('客户')
                product_name = row_data.get('产品名称') or row_data.get('产品')
                quantity = row_data.get('订单数量') or row_data.get('数量')
                deduct_flag = row_data.get('抵扣备货')
                note = row_data.get('备注')
                if not customer or not product_name or (not quantity):
                    skipped += 1
                    continue
                customer = str(customer).strip()
                product_name = str(product_name).strip()
                is_valid, error_msg = validate_customer_name(customer)
                if not is_valid:
                    errors.append(error_msg)
                    skipped += 1
                    continue
                product = product_map.get(product_name.lower().strip())
                product = product or product_map.get(product_name)
                if not product:
                    errors.append(f'产品不存在 - {product_name}')
                    skipped += 1
                    continue
                product_id = product.id
                try:
                    qty = int(quantity)
                except (ValueError, TypeError):
                    errors.append('订单数量无效')
                    skipped += 1
                    continue
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
                imported += 1
            except (ValueError, TypeError, SQLAlchemyError) as exc:
                await db.rollback()
                logger.error(f'订单导入 - 行处理失败: {exc}', exc_info=True)
                errors.append('行处理失败')
                skipped += 1
                continue
        if imported > 0:
            await db.commit()
        return _build_batch_result(imported, skipped, errors, success_msg='成功导入', fail_msg='没有成功导入任何订单')
    except (OSError, ValueError) as exc:
        await db.rollback()
        logger.error(f'订单批量导入失败: {exc}', exc_info=True)
        return BatchImportResult(success=False, message='导入失败，请稍后重试')


@router.post('/import-case-stockouts', response_model=BatchImportResult, summary='批量导入皮套出库')
async def batch_import_case_stockouts(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(require_permission('case_manage')),
) -> BatchImportResult:
    """批量导入皮套出库。

    Args:
        file: 上传的 Excel 文件（.xlsx 格式）。
        db: 异步数据库会话（读写主库）。
        current_user: 当前登录用户（仅需通过权限校验）。

    Returns:
        BatchImportResult: 包含导入结果、消息和条数的响应。
    """
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
                # 先按产品名称/条码查找关联的皮套，再按皮套名称/条码查找
                result = await db.execute(select(Product).where((Product.name == product_identifier) | (Product.barcode == product_identifier)))
                product = result.scalar_one_or_none()
                case = None
                if product:
                    result = await db.execute(select(Case).where(Case.product_id == product.id))
                    case = result.scalar_one_or_none()
                if not case:
                    result = await db.execute(select(Case).where((Case.name == product_identifier) | (Case.barcode == product_identifier)))
                    case = result.scalar_one_or_none()
                if not case:
                    errors.append(f'皮套 {product_identifier} 不存在')
                    skipped += 1
                    continue
                # 行锁确保并发安全
                result = await db.execute(select(Case).where(Case.id == case.id).with_for_update())
                case = result.scalar_one_or_none()
                if not case:
                    errors.append(f'皮套 {product_identifier} 加锁失败')
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
                imported += 1
            except (ValueError, TypeError, SQLAlchemyError) as exc:
                await db.rollback()
                logger.error(f'皮套出库导入 - 行处理失败: {exc}', exc_info=True)
                errors.append('行处理失败')
                skipped += 1
                continue
        if imported > 0:
            await db.commit()
        return _build_batch_result(imported, skipped, errors, success_msg='成功导入皮套出库', fail_msg='没有成功导入任何皮套出库')
    except (OSError, ValueError) as exc:
        await db.rollback()
        logger.error(f'皮套出库批量导入失败: {exc}', exc_info=True)
        return BatchImportResult(success=False, message='导入失败，请稍后重试')


@router.post('/import-case-stockins', response_model=BatchImportResult, summary='批量导入皮套入库')
async def batch_import_case_stockins(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(require_permission('case_manage')),
) -> BatchImportResult:
    """批量导入皮套入库。

    Args:
        file: 上传的 Excel 文件（.xlsx 格式）。
        db: 异步数据库会话（读写主库）。
        current_user: 当前登录用户（仅需通过权限校验）。

    Returns:
        BatchImportResult: 包含导入结果、消息和条数的响应。
    """
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
                # 先按产品名称/条码查找关联的皮套，再按皮套名称/条码查找
                result = await db.execute(select(Product).where((Product.name == product_identifier) | (Product.barcode == product_identifier)))
                product = result.scalar_one_or_none()
                case = None
                if product:
                    result = await db.execute(select(Case).where(Case.product_id == product.id))
                    case = result.scalar_one_or_none()
                if not case:
                    result = await db.execute(select(Case).where((Case.name == product_identifier) | (Case.barcode == product_identifier)))
                    case = result.scalar_one_or_none()
                if not case:
                    errors.append(f'皮套 {product_identifier} 不存在')
                    skipped += 1
                    continue
                # 行锁确保并发安全
                result = await db.execute(select(Case).where(Case.id == case.id).with_for_update())
                case = result.scalar_one_or_none()
                if not case:
                    errors.append(f'皮套 {product_identifier} 加锁失败')
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
                imported += 1
            except (ValueError, TypeError, SQLAlchemyError) as exc:
                await db.rollback()
                logger.error(f'皮套入库导入 - 行处理失败: {exc}', exc_info=True)
                errors.append('行处理失败')
                skipped += 1
                continue
        if imported > 0:
            await db.commit()
        return _build_batch_result(imported, skipped, errors, success_msg='成功导入皮套入库', fail_msg='没有成功导入任何皮套入库')
    except (OSError, ValueError) as exc:
        await db.rollback()
        logger.error(f'皮套入库批量导入失败: {exc}', exc_info=True)
        return BatchImportResult(success=False, message='导入失败，请稍后重试')


@router.post('/import-stockins', response_model=BatchImportResult, summary='批量导入备货')
async def batch_import_stockins(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(require_permission('batch_import')),
) -> BatchImportResult:
    """批量导入备货 - 支持统一导入模板。

    Args:
        file: 上传的 Excel 文件（.xlsx 格式）。
        db: 异步数据库会话（读写主库）。
        current_user: 当前登录用户（仅需通过权限校验）。

    Returns:
        BatchImportResult: 包含导入结果、消息和条数的响应。
    """
    if (err := _validate_xlsx_file(file)):
        return err
    try:
        data_list, err = await _read_excel_sheets(file, ['备货管理'], '没有找到"备货管理"Sheet')
        if err:
            return BatchImportResult(success=False, message=err)
        # 构建产品映射，支持按名称（小写）和条码查找
        result = await db.execute(select(Product))
        all_products = result.scalars().all()
        product_map = {prod.name.lower().strip(): prod for prod in all_products}
        product_map.update({prod.barcode: prod for prod in all_products if prod.barcode})
        imported = 0
        skipped = 0
        errors = []
        for row_data in data_list:
            try:
                customer = row_data.get('客户名称') or row_data.get('客户')
                product_name = row_data.get('产品名称') or row_data.get('产品')
                quantity = row_data.get('备货数量') or row_data.get('数量')
                stockin_date_val = row_data.get('时间') or row_data.get('备货时间')
                note = row_data.get('备注')
                if not customer or not product_name or (not quantity):
                    skipped += 1
                    continue
                customer = str(customer).strip()
                product_name = str(product_name).strip()
                is_valid, error_msg = validate_customer_name(customer)
                if not is_valid:
                    errors.append(error_msg)
                    skipped += 1
                    continue
                product = product_map.get(product_name.lower().strip())
                product = product or product_map.get(product_name)
                if not product:
                    errors.append(f'产品不存在 - {product_name}')
                    skipped += 1
                    continue
                product_id = product.id
                try:
                    qty = int(quantity)
                except (ValueError, TypeError):
                    errors.append('备货数量无效')
                    skipped += 1
                    continue
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
                imported += 1
            except (ValueError, TypeError, SQLAlchemyError) as exc:
                await db.rollback()
                logger.error(f'备货导入 - 行处理失败: {exc}', exc_info=True)
                errors.append('行处理失败')
                skipped += 1
                continue
        if imported > 0:
            await db.commit()
        return _build_batch_result(imported, skipped, errors, success_msg='成功导入备货', fail_msg='没有成功导入任何备货')
    except (OSError, ValueError) as exc:
        await db.rollback()
        logger.error(f'备货批量导入失败: {exc}', exc_info=True)
        return BatchImportResult(success=False, message='导入失败，请稍后重试')


@router.post('/import-stockouts', response_model=BatchImportResult, summary='批量导入出库')
async def batch_import_stockouts(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(require_permission('batch_import')),
) -> BatchImportResult:
    """批量导入出库。

    Args:
        file: 上传的 Excel 文件（.xlsx 格式）。
        db: 异步数据库会话（读写主库）。
        current_user: 当前登录用户（仅需通过权限校验）。

    Returns:
        BatchImportResult: 包含导入结果、消息和条数的响应。
    """
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
                result = await db.execute(select(Product).where((Product.name == product_identifier) | (Product.barcode == product_identifier)))
                product = result.scalar_one_or_none()
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
                imported += 1
            except (ValueError, TypeError, SQLAlchemyError) as exc:
                await db.rollback()
                logger.error(f'出库导入 - 行处理失败: {exc}', exc_info=True)
                errors.append('行处理失败')
                skipped += 1
                continue
        if imported > 0:
            await db.commit()
        return _build_batch_result(imported, skipped, errors, success_msg='成功导入出货', fail_msg='没有成功导入任何出货')
    except (OSError, ValueError) as exc:
        await db.rollback()
        logger.error(f'出库批量导入失败: {exc}', exc_info=True)
        return BatchImportResult(success=False, message='导入失败，请稍后重试')


@router.post('/batch-import', response_model=BatchImportResult, summary='批量导入产品')
async def batch_import_products(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(require_permission('batch_import')),
) -> BatchImportResult:
    """批量导入产品 - 支持统一模板格式。

    Args:
        file: 上传的 Excel 文件（.xlsx 格式）。
        db: 异步数据库会话（读写主库）。
        current_user: 当前登录用户（仅需通过权限校验）。

    Returns:
        BatchImportResult: 包含导入结果、消息和条数的响应。
    """
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
                name = row_data.get('产品名称') or row_data.get('名称')
                barcode = row_data.get('69码') or row_data.get('条码')
                price = row_data.get('产品价格') or row_data.get('价格')
                initial_stock = row_data.get('初始库存') or 0
                if not name:
                    skipped += 1
                    continue
                name = str(name).strip()
                # 检查产品是否已存在（按名称忽略大小写）
                result = await db.execute(select(Product).where(func.lower(Product.name) == func.lower(name)))
                existing = result.scalar_one_or_none()
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
                imported += 1
            except (ValueError, TypeError, SQLAlchemyError) as exc:
                await db.rollback()
                logger.error(f'产品导入 - 行处理失败: {exc}', exc_info=True)
                errors.append('行处理失败')
                skipped += 1
                continue
        if imported > 0:
            await db.commit()
        return _build_batch_result(imported, skipped, errors, success_msg='成功导入产品', fail_msg='没有找到需要导入的产品数据（可能都已存在）')
    except (OSError, ValueError) as exc:
        await db.rollback()
        logger.error(f'产品批量导入失败: {exc}', exc_info=True)
        return BatchImportResult(success=False, message='导入失败，请稍后重试')


@router.post('/import-comprehensive', response_model=ComprehensiveImportResult, summary='综合批量导入')
async def batch_import_comprehensive(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(require_permission('batch_import')),
) -> ComprehensiveImportResult:
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
        await db.commit()
        return results
    except (OSError, ValueError) as exc:
        await db.rollback()
        logger.error(f'综合批量导入失败: {exc}', exc_info=True)
        return ComprehensiveImportResult(success=False, message='操作失败，请稍后重试')
