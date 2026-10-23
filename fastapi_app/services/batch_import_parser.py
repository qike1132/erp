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
from typing import Any
from zipfile import BadZipFile

from fastapi_app.schemas.batch import BatchImportResult, ExcelUpload
from fastapi_app.services.xlsx_cell_images import extract_cell_images
from fastapi_app.utils import parse_date_value as _shared_parse_date_value
from fastapi_app.utils import validate_customer_name as _shared_validate_customer_name

try:  # Polars 的 Excel 引擎异常不是 ValueError/OSError，必须显式纳入解析失败口径
    from fastexcel import CalamineError
except ImportError:  # pragma: no cover - 生产环境随 polars 安装，仅防最小环境缺包
    class CalamineError(Exception):  # type: ignore[no-redef]
        """fastexcel 未安装时的占位（不会命中真实异常）。"""

logger = logging.getLogger(__name__)

_XLSX_SUFFIXES = ('.xlsx', '.xlsm')


def _looks_like_xlsx(file_path: str) -> bool:
    """xlsx/xlsm 本质是 zip：先验魔数，改名/截断文件在进解析器前就转友好错误。"""
    try:
        with open(file_path, 'rb') as fh:
            return fh.read(4) in (b'PK\x03\x04', b'PK\x05\x06', b'PK\x07\x08')
    except OSError:
        return False


def _bad_xlsx_message() -> str:
    return '文件无法解析，请确认是有效的 .xlsx 文件（可重新下载模板填写）'

#: 上传文件大小上限。产品导入模板可内嵌 WPS 单元格图片，工作簿体积随图片数量增长
#: （实测 33 张图 ≈ 2.3MB），5MB 很快就成为瓶颈；10MB 与 nginx
#: ``client_max_body_size 10m``（config/nginx-windows.conf）对齐，使后端的友好报错
#: 与反向代理的硬限制一致，不会出现「nginx 先 413、用户看不到原因」。
MAX_BATCH_UPLOAD_SIZE = 10 * 1024 * 1024
MAX_BATCH_UPLOAD_SIZE_MB = MAX_BATCH_UPLOAD_SIZE // 1024 // 1024


# ==================== 数据验证 ====================

# 使用 fastapi_app.utils 中的统一验证函数
validate_customer_name = _shared_validate_customer_name


# ==================== Excel 解析辅助 ====================

async def parse_excel_file_async(file_path: str, sheet_name: str | None = None) -> tuple[bool, list, str]:
    """异步解析 Excel 文件（Polars 引擎，比 pandas 快 5x）"""
    if file_path.lower().endswith(_XLSX_SUFFIXES) and not _looks_like_xlsx(file_path):
        return False, [], _bad_xlsx_message()
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
        except (ValueError, TypeError, OSError, BadZipFile, CalamineError) as e:
            return False, [], str(e)

    return await loop.run_in_executor(None, _sync_parse)


async def read_excel_sheets_async(file_path: str) -> tuple[bool, list, str]:
    """读取 Excel 文件的所有 Sheet 名称"""
    if file_path.lower().endswith(_XLSX_SUFFIXES) and not _looks_like_xlsx(file_path):
        return False, [], _bad_xlsx_message()
    loop = asyncio.get_running_loop()

    def _sync_read():
        try:
            from openpyxl import load_workbook
            wb = load_workbook(filename=file_path, read_only=True)
            sheets = wb.sheetnames
            wb.close()
            return True, sheets, ""
        except (ValueError, TypeError, OSError, BadZipFile, CalamineError) as e:
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
            raise ValueError(f'文件大小超过{MAX_BATCH_UPLOAD_SIZE_MB}MB限制，请拆分后重新上传')
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
    # 小数一律拒绝而不是静默截断（与 batch_import_core._parse_positive_quantity 同口径）：
    # Excel 数值单元格的 1.9 会被读成 float，int(1.9) 得 1 悄悄入库；而同样内容以文本
    # "1.9" 输入时 int() 抛错被拒 —— 同一输入因单元格类型不同结果不同。
    if isinstance(quantity, float) and not quantity.is_integer():
        return None, qty_invalid_msg
    try:
        qty = int(quantity)
    except (ValueError, TypeError):
        return None, qty_invalid_msg
    # P1（2026-10-24）：数量下界。综合导入走 batch_import_core._parse_positive_quantity
    # （qty>0 才收），单 Sheet 这条链原先漏了同一个下界 → 负数/0 数量订单直接落库，
    # 报表与 order_agg 被负数抵减。此处与 core 同口径。
    if qty <= 0:
        return None, qty_invalid_msg
    return str(customer), product.id, qty


def _parse_deduct_flag(deduct_flag: Any, qty: int) -> tuple[bool, int]:
    """解析「是否抵扣备货」列 → (是否抵扣, 抵扣数量)。

    全仓唯一实现（审计 Z04-R3③）：暂存区导入（staging）与两条订单导入路径
    （batch_import_core 的综合导入 / batch_import_service 的单 Sheet 端点）原先
    各持一份，同一列三种语义 —— 「是」在一处折算 1 件、另两处折算整单量，
    数字 '3.0' 在两处被静默丢弃。语义统一为：**数字 = 抵扣件数，是/yes/y = 整单量**，
    非整数与无法解析的内容一律不抵扣（与 `_parse_import_row` 的「小数拒绝」同口径）。

    openpyxl/Polars 把整列推断成 Float64 时整数以 3.0 到达，故走 `float()` 而不是
    `str.isdigit()`（审计 P1-8）。
    """
    if not deduct_flag:
        return False, 0
    deduct_str = str(deduct_flag).strip()
    if deduct_str.lower() in ('是', 'yes', 'y'):
        return True, qty
    try:
        numeric = float(deduct_str)
    except ValueError:
        return False, 0
    if not numeric.is_integer():
        return False, 0
    deduct_qty = int(numeric)
    return (True, deduct_qty) if deduct_qty > 0 else (False, 0)


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
    """读取上传的 Excel 文件并解析目标 sheet 数据（不提取单元格图片）。

    Args:
        file: 上传的文件对象。
        keywords: sheet 名称匹配关键词列表。
        not_found_msg: 未找到目标 sheet 时的错误消息。

    Returns:
        tuple[list | None, str | None]: (数据列表, 错误消息)。
            成功时错误消息为 None；失败时数据列表为 None。
    """
    data_list, err, _images = await _read_excel_sheets_with_cell_images(
        file, keywords, not_found_msg, with_images=False,
    )
    return data_list, err


async def _read_excel_sheets_with_cell_images(
    file: ExcelUpload, keywords: list[str], not_found_msg: str, *, with_images: bool = True,
) -> tuple[list | None, str | None, dict[str, bytes]]:
    """读取目标 sheet 数据，并（可选）提取工作簿内的单元格图片。

    产品导入模板的「图片」列由 WPS 写成 ``=DISPIMG("ID_xxx",1)``，图片字节并不在
    单元格里，而是集中在 ``xl/cellimages.xml``（见 :mod:`.xlsx_cell_images`）。
    故解析 sheet 之外还要把 ID→图片字节 取出来，交给行处理器落库。

    Args:
        file: 上传的文件对象。
        keywords: sheet 名称匹配关键词列表。
        not_found_msg: 未找到目标 sheet 时的错误消息。
        with_images: 是否提取单元格图片。默认 True；不需要图片的导入传 False，
            避免为一个不含图片的文件白白解压。

    Returns:
        tuple[list | None, str | None, dict[str, bytes]]:
            (数据列表, 错误消息, 图片ID→图片字节)。失败时数据列表为 None，
            错误消息非 None；图片提取失败只记日志，不影响数据解析结果。
    """
    async with _save_uploaded_file(file) as temp_path:
        success, sheets, err = await read_excel_sheets_async(temp_path)
        if not success:
            return None, f'Excel读取失败: {err}', {}
        target_sheet = _find_target_sheet(sheets, keywords)
        if not target_sheet:
            return None, not_found_msg, {}
        success, data_list, err = await parse_excel_file_async(temp_path, target_sheet)
        if not success:
            return None, f'数据解析失败: {err}', {}
        images = await asyncio.to_thread(extract_cell_images, temp_path) if with_images else {}
    return data_list, None, images
