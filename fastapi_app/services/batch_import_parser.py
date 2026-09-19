"""
批量 Excel 导入解析层

从 batch_import_service.py 拆出的 Excel 解析 + 文件工具，无业务依赖。
包含：异步 Excel 解析、sheet 读取、日期解析、临时文件清理、上传文件保存、
sheet 定位/类型识别、行解析与结果构建等辅助函数。
"""
import asyncio
import logging
import os
import tempfile
from contextlib import asynccontextmanager, suppress
from datetime import datetime

from fastapi_app.schemas.batch import BatchImportResult, ExcelUpload
from fastapi_app.utils import parse_date_value as _shared_parse_date_value
from fastapi_app.utils import validate_customer_name as _shared_validate_customer_name

logger = logging.getLogger(__name__)

MAX_BATCH_UPLOAD_SIZE = 5 * 1024 * 1024


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


def cleanup_temp_file(file_path: str) -> None:
    """清理临时上传文件"""
    try:
        if file_path and os.path.exists(file_path):
            os.unlink(file_path)
            logger.debug(f"已清理临时文件: {file_path}")
    except OSError as e:
        logger.warning(f"清理临时文件失败: {file_path}, {e}")


# ==================== 上传文件工具 ====================

@asynccontextmanager
async def _save_uploaded_file(file: ExcelUpload):
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


# ==================== Sheet 定位与类型识别 ====================

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


def _validate_xlsx_file(file: ExcelUpload) -> BatchImportResult | None:
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
    file: ExcelUpload, keywords: list[str], not_found_msg: str,
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
