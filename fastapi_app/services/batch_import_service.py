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
from datetime import UTC, datetime
from zipfile import BadZipFile

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from fastapi_app.core.cache_invalidation import schedule_post_commit_invalidation
from fastapi_app.core.exceptions import BusinessError, NotFoundError
from fastapi_app.schemas.batch import (
    BatchImportResult,
    ComprehensiveImportResult,
    ExcelUpload,
    ProductImportPreviewResult,
    ProductImportPreviewRow,
    ProductImportPreviewSummary,
)
from fastapi_app.services.batch_import_cache import invalidate_batch_import_caches
from fastapi_app.services.batch_import_core import (
    _backfill_empty_product_fields,
    _fmt_money,
    _import_idem_key,
    _parse_product_price,
    _resolve_import_customer_id,
    _row_failure_message,
    _save_imported_image,
)
from fastapi_app.services.inventory_service import calculate_available_shipment_quantity
from fastapi_app.services.numbering import (
    generate_case_stockin_number,
    generate_case_stockout_number,
    generate_order_number,
    generate_stockin_number,
    generate_stockout_number,
)
from fastapi_app.services.order_deduction_service import process_order_deduction
from fastapi_app.services.xlsx_cell_images import (
    extract_cell_images,
    guess_image_extension,
    parse_dispimg_id,
)
from fastapi_app.shared.stock_concurrency import (
    apply_stock_delta_locked,
    check_stock_available,
    get_product_for_update,
)
from fastapi_app.shared_models import (
    CaseMovement,
    InventoryLog,
    Order,
    Product,
    ProductCustomer,
    StockIn,
    StockOut,
)
from fastapi_app.shared_models.order import ORDER_STATUS_PENDING_STOCK
from fastapi_app.utils import validate_customer_name as _shared_validate_customer_name

logger = logging.getLogger(__name__)

#: 产品 Sheet 的名称关键词。模板自 2026-10-12 起改名为「新品录入」（表头同步改为
#: ``客户 | 产品名称 | 工厂 | 69码 | 产品价格 | 图片``），旧名「产品管理」继续识别，
#: 使存量文件与用户手上的旧模板都还能导入。
PRODUCT_SHEET_KEYWORDS = ['产品管理', '新品录入']


def _require_not_none[T](value: T | None, source: str) -> T:
    """把「失败时为 None」的解析结果收窄为非 None，否则抛 ValueError。

    为什么不用 `assert`（S101，生产代码禁用 assert）：`-O` 下 assert 会被剥掉，
    helper 契约一破就带着 None 继续往下跑；而裸 AssertionError 不在本模块
    except (OSError, ValueError) 的捕获范围内 —— 会一路冒到端点变成 500。
    改抛 ValueError 后恰好落回既有的解析错误分支，与「文件损坏 / Sheet 不存在」
    返回同一种 success=False 结果（见各 import_*_service 末尾的 except）。
    """
    if value is None:
        raise ValueError(f'{source}未返回数据')
    return value


# ==================== 单 Sheet 导入共享骨架 ====================

async def _run_sheet_rows(
    db: AsyncSession,
    data_list: list,
    row_writer,
    success_msg: str,
    fail_msg: str,
    *,
    log_label: str,
) -> BatchImportResult:
    """单 Sheet 批量导入的共享行循环（2026-10-15 抽取）。

    此前 5 个 ``import_*_service`` 各持一份逐字相同的骨架：行循环（savepoint
    隔离单行）→ 计数 → post-commit 缓存失效 → 结果构建 → 异常兜底。改导入
    规则要同步 5 处（2026-08-10 的孤儿订单事故正是 core 路径改了、单 Sheet
    端点漏改），故收敛为一份。文件校验与读 Sheet 由调用方先行完成（订单/
    备货路径要在循环前预加载产品映射与客户名单，读 Sheet 的时机归调用方）。

    Args:
        row_writer: ``async (db, row_data) -> tuple[bool, str | None]``。
            在 savepoint 内写一行；返回 ``(True, None)`` 计入 imported；
            ``(False, None)`` 静默跳过；``(False, msg)`` 记录错误消息并跳过
            （消息文案由 row_writer 负责，保持既有用户可见文案不变）。
            行内抛 (ValueError, TypeError, SQLAlchemyError) 由骨架统一回滚
            该行、记异常消息、计 skipped。
        log_label: 行级异常日志前缀（如 '订单导入'）。
    """
    imported = 0
    skipped = 0
    errors: list[str] = []
    for row_data in data_list:
        try:
            # savepoint 隔离单行：行内异常仅回滚本行，不影响循环内已成功的行
            async with db.begin_nested():
                ok, row_err = await row_writer(db, row_data)
            if not ok:
                if row_err is not None:
                    errors.append(row_err)
                skipped += 1
                continue
            # savepoint 成功提交后才计数，失败行不计入 imported
            imported += 1
        except (ValueError, TypeError, SQLAlchemyError) as exc:
            # savepoint 已自动回滚本行，不再整体 rollback（避免误伤已成功的行）
            logger.error(f'{log_label} - 行处理失败: {exc}', exc_info=True)
            errors.append(_row_failure_message(exc))
            skipped += 1
            continue
    # 提交交给请求级事务（get_async_db），服务层不再手动 commit
    if imported > 0:
        schedule_post_commit_invalidation(db, invalidate_batch_import_caches)
    return _build_batch_result(imported, skipped, errors, success_msg=success_msg, fail_msg=fail_msg)


def _reject_unknown_customer(customer: str, customer_names: set) -> str | None:
    """客户主数据校验（单一事实来源，2026-10-15 收敛）。

    与 core 路径 ``batch_import_core._resolve_row_identity`` 同一道校验：customer
    是无外键的名字快照，不校验会在库里留下永远关联不到客户的孤儿单据
    （2026-08-10 曾因此产生 19 张孤儿订单）。此前该校验在
    import_orders_service / import_stockins_service 各抄一份 + 事故注释两份。

    Returns:
        客户不在主数据时返回错误消息；通过时返回 None。
    """
    if customer not in customer_names:
        return f'客户"{customer}"不存在于客户主数据，请先在客户管理中创建'
    return None


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
    cell_images: dict[str, bytes] | None = None,
    uploader_id: int | None = None,
) -> None:
    """处理综合导入中的单个 Sheet。

    Args:
        db: 异步数据库会话。
        sheet_type: Sheet 类型（product/order/stockin/stockout）。
        sheet_name: Sheet 名称（用于日志和错误信息）。
        data_list: 解析后的行数据列表。
        results: 综合导入结果对象，原地更新。
        cell_images: 工作簿内的单元格图片（图片 ID → 字节），仅产品 Sheet 使用。
        uploader_id: 图片落库时登记的上传人。
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
            count, messages = await _call_sheet_importer(
                importer, db, data_list, cell_images, uploader_id,
            )
        results.imported[count_key] += count
        if messages:
            # 行级消息（含去重跳过原因）此前被整体丢弃，用户只能看到
            # 「Sheet X 导入失败」却不知道哪一行、为什么。
            results.errors.extend(messages)
    except (ValueError, TypeError, SQLAlchemyError) as e:
        # savepoint 上下文退出时已回滚本 Sheet 的未提交行
        logger.error(f'综合导入 - Sheet {sheet_name} 导入失败: {e}', exc_info=True)
        results.errors.append(f'Sheet {sheet_name} 导入失败')


async def _call_sheet_importer(
    importer, db: AsyncSession, data_list: list,
    cell_images: dict[str, bytes] | None, uploader_id: int | None,
) -> tuple[int, list]:
    """调用 Sheet 导入函数。

    只有产品导入接收单元格图片与上传人（其余 Sheet 无图片列），故在此分派，
    而不是让所有导入函数都背上一组用不到的参数。
    """
    if importer is import_products_from_data:
        return await importer(db, data_list, cell_images=cell_images, uploader_id=uploader_id)
    return await importer(db, data_list)


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

    骨架见 :func:`_run_sheet_rows`；本函数只负责订单行的写入逻辑
    （客户校验经 :func:`_reject_unknown_customer` 与 core 路径同口径）。
    """
    from fastapi_app.services.batch_service import get_all_products

    if (file_err := _validate_xlsx_file(file)):
        return file_err
    try:
        data_list, err = await _read_excel_sheets(file, ['订单管理'], '没有找到"订单管理"Sheet')
        if err:
            return BatchImportResult(success=False, message=err)
        data_list = _require_not_none(data_list, 'Excel 解析')
        # 构建产品映射，支持按名称（小写）和条码查找
        all_products = await get_all_products(db)
        product_map = {prod.name.lower().strip(): prod for prod in all_products}
        product_map.update({prod.barcode: prod for prod in all_products if prod.barcode})
        # 客户必须在客户主数据中（校验经 _reject_unknown_customer，与 core 路径同口径）
        customer_names = await _pre_load_customer_names(db)

        async def _write_order_row(db: AsyncSession, row_data: dict) -> tuple[bool, str | None]:
            deduct_flag = row_data.get('抵扣备货')
            note = row_data.get('备注')
            parsed = _parse_import_row(row_data, product_map, '订单数量', '订单数量无效')
            if parsed is None:
                return False, None
            if parsed[0] is None:
                return False, parsed[1]
            customer, product_id, qty = parsed
            # 客户主数据校验（与 core 的 _resolve_row_identity 同口径）
            if (cust_err := _reject_unknown_customer(customer, customer_names)) is not None:
                return False, cust_err
            order_no = await generate_order_number(db)
            order_date = datetime.now()
            order = Order(
                order_no=order_no, customer=customer, order_date=order_date,
                product_id=product_id, quantity=qty,
                note=str(note).strip() if note else '', status=ORDER_STATUS_PENDING_STOCK,
            )
            db.add(order)
            await db.flush()
            locked_product = await get_product_for_update(db, product_id)
            log = InventoryLog(
                product_id=product_id, change_type='订单', change_quantity=qty,
                related_id=order_no, note=f'批量导入订单：{order_no}',
                idem_key=_import_idem_key('order', customer, product_id, qty, order_date),
            )
            db.add(log)
            # 2026-10-17 审计 P2-02：与 batch_import_core 对齐抵扣语义——
            # 数字 = 抵扣数量；是/yes = 整单数量。此前只认「是」，数字被静默丢弃。
            if deduct_flag:
                deduct_str = str(deduct_flag).strip()
                deduct_value = 0
                # 2026-10-18 OCR 评审：Polars 把整列推断成 Float64 时，整数会以
                # 3.0 形式到达，str(3.0)='3.0' 不是 digit → 抵扣被静默跳过。
                if isinstance(deduct_flag, (int, float)) and not isinstance(deduct_flag, bool) \
                        and float(deduct_flag).is_integer():
                    deduct_value = int(deduct_flag)
                elif deduct_str.isdigit():
                    deduct_value = int(deduct_str)
                elif deduct_str.lower() in ('是', 'yes'):
                    deduct_value = qty
                if deduct_value > 0:
                    await process_order_deduction(
                        db, order, product_id, deduct_value,
                        deduct_stock=True, product=locked_product,
                    )
            return True, None

        return await _run_sheet_rows(
            db, data_list, _write_order_row,
            '成功导入', '没有成功导入任何订单', log_label='订单导入',
        )
    except (OSError, ValueError) as exc:
        await db.rollback()  # manual-tx: try/except 内显式事务控制
        logger.error(f'订单批量导入失败: {exc}', exc_info=True)
        return BatchImportResult(success=False, message='导入失败，请稍后重试')


async def import_case_stockouts_service(db: AsyncSession, file: ExcelUpload) -> BatchImportResult:
    """批量导入皮套出库（骨架见 :func:`_run_sheet_rows`）。"""
    from fastapi_app.services.batch_service import find_case_locked

    if (file_err := _validate_xlsx_file(file)):
        return file_err
    try:
        data_list, err = await _read_excel_sheets(file, ['皮套出库', '皮套出货'], '没有找到可用的Sheet')
        if err:
            return BatchImportResult(success=False, message=err)
        data_list = _require_not_none(data_list, 'Excel 解析')

        async def _write_case_stockout_row(db: AsyncSession, row_data: dict) -> tuple[bool, str | None]:
            product_identifier = row_data.get('产品名称') or row_data.get('产品') or row_data.get('皮套名称') or row_data.get('皮套')
            quantity = row_data.get('出库数量') or row_data.get('数量')
            customer = row_data.get('客户名称') or row_data.get('客户')
            stockout_date_val = row_data.get('时间') or row_data.get('出库时间')
            note = row_data.get('备注')
            if not product_identifier or not quantity:
                return False, None
            product_identifier = str(product_identifier).strip()
            customer = str(customer).strip() if customer else ''
            try:
                qty = int(quantity)
                if qty <= 0:
                    return False, '出库数量必须大于0'
            except ValueError:
                return False, '出库数量必须是整数'
            case, case_err = await find_case_locked(db, product_identifier)
            if case_err:
                return False, case_err
            case = _require_not_none(case, '皮套查询')
            # 统一负库存校验入口（env ALLOW_NEGATIVE_STOCK，缺省拒绝）
            if reason := check_stock_available(
                case.current_stock, -qty,
                message=f'库存不足，当前库存: {case.current_stock}',
            ):
                return False, reason
            movement_date = parse_date_value(stockout_date_val) or datetime.now(UTC)
            movement_no = await generate_case_stockout_number(db)
            db.add(CaseMovement(
                case_id=case.id, direction='out', movement_no=movement_no,
                quantity=qty, customer=customer, movement_date=movement_date,
                note=str(note).strip() if note else '',
            ))
            case.current_stock -= qty
            case.version += 1
            return True, None

        return await _run_sheet_rows(
            db, data_list, _write_case_stockout_row,
            '成功导入皮套出库', '没有成功导入任何皮套出库', log_label='皮套出库导入',
        )
    except (OSError, ValueError) as exc:
        await db.rollback()  # manual-tx: try/except 内显式事务控制
        logger.error(f'皮套出库批量导入失败: {exc}', exc_info=True)
        return BatchImportResult(success=False, message='导入失败，请稍后重试')


async def import_case_stockins_service(db: AsyncSession, file: ExcelUpload) -> BatchImportResult:
    """批量导入皮套入库（骨架见 :func:`_run_sheet_rows`）。"""
    from fastapi_app.services.batch_service import find_case_locked

    if (file_err := _validate_xlsx_file(file)):
        return file_err
    try:
        data_list, err = await _read_excel_sheets(file, ['皮套入库', '皮套进库'], '没有找到可用的Sheet')
        if err:
            return BatchImportResult(success=False, message=err)
        data_list = _require_not_none(data_list, 'Excel 解析')

        async def _write_case_stockin_row(db: AsyncSession, row_data: dict) -> tuple[bool, str | None]:
            product_identifier = row_data.get('产品名称') or row_data.get('产品') or row_data.get('皮套名称') or row_data.get('皮套')
            quantity = row_data.get('入库数量') or row_data.get('数量')
            customer = row_data.get('客户名称') or row_data.get('客户')
            stockin_date_val = row_data.get('时间') or row_data.get('入库时间')
            note = row_data.get('备注')
            if not product_identifier or not quantity:
                return False, None
            product_identifier = str(product_identifier).strip()
            customer = str(customer).strip() if customer else ''
            try:
                qty = int(quantity)
                if qty <= 0:
                    return False, '入库数量必须大于0'
            except ValueError:
                return False, '入库数量必须是整数'
            case, case_err = await find_case_locked(db, product_identifier)
            if case_err:
                return False, case_err
            case = _require_not_none(case, '皮套查询')
            stockin_date = parse_date_value(stockin_date_val) or datetime.now(UTC)  # aware UTC：movement_date 列为 timestamptz
            movement_no = await generate_case_stockin_number(db)
            db.add(CaseMovement(
                case_id=case.id, direction='in', movement_no=movement_no,
                quantity=qty, customer=customer, movement_date=stockin_date,
                note=str(note).strip() if note else '',
            ))
            case.current_stock += qty
            case.version += 1
            return True, None

        return await _run_sheet_rows(
            db, data_list, _write_case_stockin_row,
            '成功导入皮套入库', '没有成功导入任何皮套入库', log_label='皮套入库导入',
        )
    except (OSError, ValueError) as exc:
        await db.rollback()  # manual-tx: try/except 内显式事务控制
        logger.error(f'皮套入库批量导入失败: {exc}', exc_info=True)
        return BatchImportResult(success=False, message='导入失败，请稍后重试')


async def import_stockins_service(db: AsyncSession, file: ExcelUpload) -> BatchImportResult:
    """批量导入备货 - 支持统一导入模板（骨架见 :func:`_run_sheet_rows`）。"""
    from fastapi_app.services.batch_service import get_all_products

    if (file_err := _validate_xlsx_file(file)):
        return file_err
    try:
        data_list, err = await _read_excel_sheets(file, ['备货管理'], '没有找到"备货管理"Sheet')
        if err:
            return BatchImportResult(success=False, message=err)
        data_list = _require_not_none(data_list, 'Excel 解析')
        # 构建产品映射，支持按名称（小写）和条码查找
        all_products = await get_all_products(db)
        product_map = {prod.name.lower().strip(): prod for prod in all_products}
        product_map.update({prod.barcode: prod for prod in all_products if prod.barcode})
        # 客户必须在客户主数据中（校验经 _reject_unknown_customer，与 core 路径同口径）
        customer_names = await _pre_load_customer_names(db)

        async def _write_stockin_row(db: AsyncSession, row_data: dict) -> tuple[bool, str | None]:
            stockin_date_val = row_data.get('时间') or row_data.get('备货时间')
            note = row_data.get('备注')
            parsed = _parse_import_row(row_data, product_map, '备货数量', '备货数量无效')
            if parsed is None:
                return False, None
            if parsed[0] is None:
                return False, parsed[1]
            customer, product_id, qty = parsed
            # 客户主数据校验（与 core 的 _resolve_row_identity 同口径）
            if (cust_err := _reject_unknown_customer(customer, customer_names)) is not None:
                return False, cust_err
            stockin_date = parse_date_value(stockin_date_val) or datetime.now(UTC)  # aware UTC：stockin_date 列为 timestamptz
            stockin_no = await generate_stockin_number(db)
            stockin = StockIn(
                stockin_no=stockin_no, stockin_date=stockin_date, customer=customer,
                product_id=product_id, quantity=qty, note=str(note).strip() if note else '',
            )
            db.add(stockin)
            locked_product = await get_product_for_update(db, product_id)
            # 2026-10-17 审计 F-BE-SVC-STOCK-01：原为 `locked_product.current_stock += qty` 直写
            # （不递增 version，并发丢失更新），改走统一写入口。
            await apply_stock_delta_locked(db, locked_product, qty)
            log = InventoryLog(
                product_id=product_id, change_type='备货', change_quantity=qty,
                related_id=stockin_no, note=f'批量导入备货：{stockin_no}',
                idem_key=_import_idem_key('stockin', customer, product_id, qty, stockin_date),
            )
            db.add(log)
            return True, None

        return await _run_sheet_rows(
            db, data_list, _write_stockin_row,
            '成功导入备货', '没有成功导入任何备货', log_label='备货导入',
        )
    except (OSError, ValueError) as exc:
        await db.rollback()  # manual-tx: try/except 内显式事务控制
        logger.error(f'备货批量导入失败: {exc}', exc_info=True)
        return BatchImportResult(success=False, message='导入失败，请稍后重试')


async def import_stockouts_service(db: AsyncSession, file: ExcelUpload) -> BatchImportResult:
    """批量导入出库（骨架见 :func:`_run_sheet_rows`）。"""
    from fastapi_app.services.batch_service import get_product_by_identifier

    if (file_err := _validate_xlsx_file(file)):
        return file_err
    try:
        data_list, err = await _read_excel_sheets(file, ['出货管理'], '没有找到"出货管理"Sheet')
        if err:
            return BatchImportResult(success=False, message=err)
        data_list = _require_not_none(data_list, 'Excel 解析')

        async def _write_stockout_row(db: AsyncSession, row_data: dict) -> tuple[bool, str | None]:
            product_identifier = row_data.get('产品名称') or row_data.get('产品')
            quantity = row_data.get('出货数量') or row_data.get('数量')
            customer = row_data.get('客户名称') or row_data.get('客户')
            stockout_date_val = row_data.get('时间') or row_data.get('出货时间')
            note = row_data.get('备注')
            if not product_identifier or not quantity:
                return False, None
            product_identifier = str(product_identifier).strip()
            customer = str(customer).strip() if customer else ''
            if not customer:
                return False, '出货必须选择客户'
            product = await get_product_by_identifier(db, product_identifier)
            if not product:
                return False, f'产品 {product_identifier} 不存在'
            product = await get_product_for_update(db, product.id)
            try:
                qty = int(quantity)
                if qty <= 0:
                    return False, '出库数量必须大于0'
            except ValueError:
                return False, '出库数量必须是整数'
            # 统一负库存校验入口（env ALLOW_NEGATIVE_STOCK，缺省拒绝）
            if reason := check_stock_available(
                product.current_stock, -qty,
                message=f'库存不足，当前库存: {product.current_stock}',
            ):
                return False, reason
            # 校验可出货量（基于订单支持）
            shipment_info = await calculate_available_shipment_quantity(
                db, product.id, customer,
            )
            if shipment_info['available_quantity'] <= 0:
                return False, f'客户{customer}没有可用的订单支持出货'
            if qty > shipment_info['available_quantity']:
                return False, f"出货数量{qty}超过可出货量{shipment_info['available_quantity']}"
            stockout_date = parse_date_value(stockout_date_val) or datetime.now()
            # 按订单可用量分配出货，直到出货数量耗尽
            await _allocate_stockout_to_orders(db, product, qty, customer, stockout_date, note, shipment_info)
            # 2026-10-17 审计 F-BE-SVC-STOCK-01：原为 `product.current_stock -= qty` 直写，改走统一写入口。
            await apply_stock_delta_locked(db, product, -qty)
            log = InventoryLog(
                product_id=product.id, change_type='出库', change_quantity=-qty,
                related_id='', note=f'批量导入出库：客户{customer}，数量{qty}',
                idem_key=_import_idem_key('stockout', customer, product.id, qty, stockout_date),
            )
            db.add(log)
            return True, None

        return await _run_sheet_rows(
            db, data_list, _write_stockout_row,
            '成功导入出货', '没有成功导入任何出货', log_label='出库导入',
        )
    except (OSError, ValueError) as exc:
        await db.rollback()  # manual-tx: try/except 内显式事务控制
        logger.error(f'出库批量导入失败: {exc}', exc_info=True)
        return BatchImportResult(success=False, message='导入失败，请稍后重试')


async def _read_product_sheet(
    file: ExcelUpload,
) -> tuple[list, dict, str | None]:
    """读「新品录入」Sheet 的行数据与单元格图片。

    Returns:
        ``(data_list, cell_images, err)``；``err`` 非 None 时 ``data_list`` 为空列表
        （调用方应先判 ``err``，不必再处理 ``None``）。
    """
    try:
        data_list, err, cell_images = await _read_excel_sheets_with_cell_images(
            file, PRODUCT_SHEET_KEYWORDS, '没有找到"新品录入"Sheet',
        )
    except (OSError, ValueError, BadZipFile) as exc:
        # 扩展名对但内容不是 zip/工作簿（改名、下载损坏、手改二进制）：给出可读提示，
        # 而不是把 BadZipFile 漏到 500。导入与预览共用本入口，两边行为一致。
        logger.warning('产品导入：Excel 解析失败: %s', exc)
        return [], {}, '文件无法解析，请确认是有效的 .xlsx 文件（可重新下载模板填写）'
    if err:
        return [], {}, err
    return _require_not_none(data_list, 'Excel 解析'), cell_images or {}, None


async def _classify_product_row(
    db: AsyncSession, row_data: dict, idx: int, context: dict,
) -> ProductImportPreviewRow:
    """把一行 Excel 分类成「新增 / 补全 / 跳过 / 错误」，**不写库**。

    判定与 :func:`import_products_service` 的导入循环同源：已存在的行走
    :func:`_backfill_empty_product_fields` 的 ``dry_run`` 模式（同一段代码只算不写），
    因此预览看到的改动等于导入会做的改动。

    ``context`` 持有跨行状态：``customer_cache``（客户名 → id 缓存）与
    ``seen_names``（本文件内已出现过的产品名，用于批内去重）。

    **批内同名重复行**：第二行起按「跳过」处置（``seen_names``），与导入路径的批内
    去重同口径 —— 导入侧同样跳过它、不把该行的字段并进上一行刚建的产品。因此预览的
    「写入 / 跳过」计数与真实导入一致（由 ``tests/test_product_import_preview.py`` 的
    哨兵用例锁住）。

    已知边界：预览**看不到库级约束**（名称超 100 字、价格超 ``Numeric(10,2)`` 上限、
    工厂超 50 字等），这类行会显示为「新增」而导入时整行失败。导入侧会如实回显该行
    的错误，不会静默 —— 若将来这类输入变常见，应在 ``_parse_product_price`` /
    字段校验处收口，而不是把列长抄一份到预览里。
    """
    from fastapi_app.services.batch_service import get_product_by_name_ci

    name = row_data.get('产品名称') or row_data.get('名称')
    barcode = row_data.get('69码') or row_data.get('条码')
    price = row_data.get('产品价格') or row_data.get('价格')
    factory = row_data.get('工厂')
    customer_name = row_data.get('客户') or row_data.get('客户名称')
    image_id = parse_dispimg_id(row_data.get('图片') or row_data.get('产品图片'))
    image_bytes = context['cell_images'].get(image_id) if image_id else None

    if not name:
        return ProductImportPreviewRow(
            row_no=idx, action='error', messages=['缺少产品名称，本行无法导入'])

    name = str(name).strip()
    name_key = name.casefold()
    is_duplicate = name_key in context['seen_names']
    messages: list[str] = []
    # 重复行按「跳过」处置，与导入侧同口径：不为它播报客户警告（导入侧的去重判断也在
    # 解析客户之前）。仍解析一次，好在表里给出准确的客户匹配态供人工核对。
    customer_id = await _resolve_import_customer_id(
        db, customer_name, context['customer_cache'], idx,
        [] if is_duplicate else messages)
    customer_display = str(customer_name).strip() if customer_name else ''

    action = 'skip'
    changes: list[str] = []
    if is_duplicate:
        messages.append('产品名称在文件内重复，已跳过')
    else:
        context['seen_names'].add(name_key)
        existing = await get_product_by_name_ci(db, name)
        if existing is None:
            action = 'create'
            changes = ['新建产品']
        else:
            changed, changes = await _backfill_empty_product_fields(
                db, existing, price=price, factory=factory, customer_id=customer_id,
                customer_name=customer_display, dry_run=True)
            if image_bytes is not None:
                # 图片按模板覆盖（与导入同口径），但**必须先过同一道可落库判定**：
                # `_save_imported_image` 认不出魔数（EMF/BMP/TIFF 等 WPS 单元格图片）
                # 就跳过该图、该行因此不算改动。这里不预判，预览就会把「更新图片」
                # 算进写入数，而导入实际跳过 —— 预览高估，正是那条哨兵要拦的漂移。
                if guess_image_extension(image_bytes) is None:
                    messages.append('该行图片格式无法识别，导入时将跳过图片')
                else:
                    changes.append('更新图片')
                    changed = True
            action = 'backfill' if changed else 'skip'

    return ProductImportPreviewRow(
        row_no=idx, action=action, name=name,
        barcode=str(barcode).strip() if barcode else '',
        price=_fmt_money(_parse_product_price(price, name)) if price else '',
        price_raw='' if price is None else str(price),
        factory=str(factory).strip() if factory else '',
        customer_name=customer_display,
        customer_matched=customer_id is not None,
        has_image=image_bytes is not None,
        changes=changes,
        messages=messages,
    )


async def preview_products_service(
    db: AsyncSession, file: ExcelUpload,
) -> ProductImportPreviewResult:
    """产品导入预览 —— 逐行分类，**不写库、不落图片**。

    用户在确认前看到的就是「导入将要做什么」：每行标出 新增/补全/跳过/错误，并给出
    解析出的客户、价格、工厂与将改动的字段。确认由前端把同一文件重发给
    ``POST /batch/batch-import`` 完成（本函数不做任何写入）。

    Args:
        db: 数据库会话（**只读**使用）。
        file: 上传的 Excel 文件（.xlsx 格式）。

    Returns:
        ProductImportPreviewResult: 逐行结果与汇总计数。
    """
    filename = getattr(file, 'filename', '') or ''
    if (file_err := _validate_xlsx_file(file)):
        return ProductImportPreviewResult(success=False, message=file_err.message, filename=filename)
    try:
        data_list, cell_images, err = await _read_product_sheet(file)
    except (OSError, ValueError) as exc:
        logger.error(f'产品导入预览失败: {exc}', exc_info=True)
        return ProductImportPreviewResult(success=False, message='解析失败，请稍后重试', filename=filename)
    if err:
        return ProductImportPreviewResult(success=False, message=err, filename=filename)

    context: dict = {'cell_images': cell_images, 'customer_cache': {}, 'seen_names': set()}
    rows: list[ProductImportPreviewRow] = []
    counts = {'create': 0, 'backfill': 0, 'skip': 0, 'error': 0}
    for idx, row_data in enumerate(data_list, start=2):
        try:
            row = await _classify_product_row(db, row_data, idx, context)
        except (ValueError, TypeError, SQLAlchemyError) as exc:
            # 单行分类失败不拖垮整份预览（与导入循环同口径）：标为错误行，其余照常。
            logger.warning('产品导入预览 - 行%s 分类失败: %s', idx, exc)
            row = ProductImportPreviewRow(
                row_no=idx, action='error', messages=[_row_failure_message(exc, idx)])
        rows.append(row)
        counts[row.action] = counts.get(row.action, 0) + 1

    summary = ProductImportPreviewSummary(**counts)
    writable = summary.create + summary.backfill
    if writable:
        message = (f'将写入 {writable} 条（新增 {summary.create} + 补全 {summary.backfill}），'
                   f'跳过 {summary.skip + summary.error} 条')
    else:
        message = '没有可导入的数据（可能都已存在或格式有误）'
    return ProductImportPreviewResult(
        success=writable > 0, message=message, filename=filename,
        row_count=len(rows), summary=summary, rows=rows,
    )


async def import_products_service(
    db: AsyncSession, file: ExcelUpload, *, uploader_id: int | None = None,
) -> BatchImportResult:
    """批量导入产品 - 支持统一模板格式（含 WPS 单元格图片）。

    「图片」列由 WPS 写成 ``=DISPIMG("ID_xxx",1)``，图片字节集中在工作簿的
    ``xl/cellimages.xml`` 里，故解析 sheet 之外还要把图片一并取出来落库。

    Args:
        file: 上传的 Excel 文件（.xlsx 格式）。
        db: 异步数据库会话（读写主库）。
        uploader_id: 图片落库时登记的上传人（由端点传入当前用户 id）。

    Returns:
        BatchImportResult: 包含导入结果、消息和条数的响应。
    """
    from fastapi_app.services.batch_service import get_product_by_name_ci

    if (file_err := _validate_xlsx_file(file)):
        return file_err
    try:
        data_list, cell_images, err = await _read_product_sheet(file)
        if err:
            return BatchImportResult(success=False, message=err)
        imported = 0
        skipped = 0
        errors: list[str] = []
        customer_cache: dict = {}
        seen_names: set[str] = set()
        # 行号从 2 起：Excel 第 1 行是表头，与用户看到的行号一致（与 core 那条实现同口径）
        for idx, row_data in enumerate(data_list, start=2):
            try:
                # savepoint 隔离单行：行内异常仅回滚本行，不影响循环内已成功的行
                async with db.begin_nested():
                    name = row_data.get('产品名称') or row_data.get('名称')
                    barcode = row_data.get('69码') or row_data.get('条码')
                    price = row_data.get('产品价格') or row_data.get('价格')
                    factory = row_data.get('工厂')
                    customer_name = row_data.get('客户') or row_data.get('客户名称')
                    initial_stock = row_data.get('初始库存') or 0
                    image_id = parse_dispimg_id(row_data.get('图片') or row_data.get('产品图片'))
                    image_bytes = cell_images.get(image_id) if image_id else None
                    if not name:
                        skipped += 1
                        continue
                    name = str(name).strip()
                    name_key = name.casefold()
                    if name_key in seen_names:
                        # 文件内同名重复行 → 跳过。与 core 路径的去重同口径，也与导入
                        # 预览的判定一致：本行若落进下面的「已存在」分支，会把上一行刚建
                        # 的同名产品补全并计数，而预览说它是「跳过」—— 预览说写入 N 条、
                        # 导入写 N+1 条，正是那条哨兵测试要拦的漂移。
                        skipped += 1
                        errors.append(f'行{idx}: 产品名称在文件内重复，已跳过: {name}')
                        continue
                    seen_names.add(name_key)
                    customer_id = await _resolve_import_customer_id(
                        db, customer_name, customer_cache, idx, errors)
                    # 检查产品是否已存在（按名称忽略大小写）
                    existing = await get_product_by_name_ci(db, name)
                    if existing:
                        # 已存在 → 只补空值（价格/工厂/客户归属）；图片仍按模板覆盖
                        changed, _ = await _backfill_empty_product_fields(
                            db, existing, price=price, factory=factory, customer_id=customer_id,
                            customer_name=str(customer_name).strip() if customer_name else '')
                        if image_bytes is not None:
                            image_key = await _save_imported_image(db, image_bytes, name, uploader_id)
                            if image_key:
                                existing.image = image_key
                                changed = True
                        if changed:
                            imported += 1
                        else:
                            skipped += 1
                            errors.append(f'行{idx}: 产品名称与已有数据重复，已存在且无可补字段，未改动: {name}')
                        continue
                    try:
                        stock = int(initial_stock) if initial_stock else 0
                    except ValueError:
                        stock = 0
                    product = Product(
                        name=name, barcode=str(barcode).strip() if barcode else '',
                        price=_parse_product_price(price, name),
                        factory=str(factory).strip() if factory else '',
                        initial_stock=stock, current_stock=stock,
                    )
                    if image_bytes is not None:
                        product.image = await _save_imported_image(db, image_bytes, name, uploader_id)
                    db.add(product)
                    if customer_id is not None:
                        await db.flush()  # 挂归属需要 product.id
                        db.add(ProductCustomer(product_id=product.id, customer_id=customer_id))
                # savepoint 成功提交后才计数，失败行不计入 imported
                imported += 1
            except (ValueError, TypeError, SQLAlchemyError) as exc:
                # savepoint 已自动回滚本行，不再整体 rollback（避免误伤已成功的行）
                logger.error(f'产品导入 - 行处理失败: {exc}', exc_info=True)
                errors.append(_row_failure_message(exc, idx))
                skipped += 1
                continue
        # 提交交给请求级事务（get_async_db），服务层不再手动 commit
        if imported > 0:
            schedule_post_commit_invalidation(db, invalidate_batch_import_caches)
        return _build_batch_result(imported, skipped, errors, success_msg='成功导入产品', fail_msg='没有找到需要导入的产品数据（可能都已存在）')
    except (OSError, ValueError) as exc:
        await db.rollback()  # manual-tx: try/except 内显式事务控制
        logger.error(f'产品批量导入失败: {exc}', exc_info=True)
        return BatchImportResult(success=False, message='导入失败，请稍后重试')


async def import_comprehensive_service(
    db: AsyncSession, file: ExcelUpload, *, uploader_id: int | None = None,
) -> ComprehensiveImportResult:
    """综合批量导入 - 支持4个Sheet自动识别。

    自动识别 Sheet 类型：新品录入、订单管理、备货管理、出货管理。
    每个 Sheet 独立处理，单个 Sheet 失败不影响其他 Sheet。
    「新品录入」Sheet 的 WPS 单元格图片（``=DISPIMG(...)``）会一并落库。

    Args:
        file: 上传的 Excel 文件（.xlsx 格式）。
        db: 异步数据库会话（读写主库）。
        uploader_id: 图片落库时登记的上传人（由端点传入当前用户 id）。

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
            sheet_mapping = {
                '新品录入': 'product', '产品管理': 'product', '订单管理': 'order',
                '备货管理': 'stockin', '出货管理': 'stockout',
            }
            # 单元格图片只与产品 Sheet 相关；工作簿里没有 cellimages.xml 时立刻返回空字典
            cell_images = await asyncio.to_thread(extract_cell_images, temp_path)
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
                await _process_comprehensive_sheet(
                    db, sheet_type, sheet_name, data_list, results,
                    cell_images=cell_images, uploader_id=uploader_id,
                )
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
    _pre_load_customer_names,
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
    _parse_import_row,
    _read_excel_sheets,
    _read_excel_sheets_with_cell_images,
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
