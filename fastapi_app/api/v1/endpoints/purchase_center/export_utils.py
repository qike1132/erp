"""
采购中心 — Excel 导出工具函数

包含 HTML 打印模板生成和 Excel 工作簿创建逻辑。
"""

import html
import os
from datetime import datetime

import openpyxl
from openpyxl import Workbook
from openpyxl.styles import Alignment as Al
from openpyxl.styles import Border as Bd
from openpyxl.styles import Font as Ft
from openpyxl.styles import Side as Sd

from fastapi_app.core.float_utils import round_qty
from fastapi_app.core.logger import logger
from utils.report_exporter import _sanitize_excel_value


def _h(value) -> str:
    """打印模板插值的**唯一**出口：Excel 首字符打断 + HTML 转义（Z06-R3 / F2-3）。

    打印页是 HTML，但用户会「另存后用 Excel 打开」，此时 `<td>`/`<div>` 里的文本
    落到单元格，首字符为 `= + - @` 即被当公式/DDE 载荷解析 —— 与 xlsx 导出同风险面，
    故复用权威清洗器 `utils.report_exporter._sanitize_excel_value`，不另立口径。

    只打断 `str` 输入：数量列是 `Numeric`，负数是合法退货/冲抵口径，Excel 对纯数字
    按数值解析、本就不是注入面；若一并加前缀会把 `-5` 变成文本，破坏合计列可计算性。
    """
    if value is None:
        text = ''
    elif isinstance(value, str):
        text = _sanitize_excel_value(value)
    else:
        text = str(value)
    return html.escape(text)

# 模板文件路径
_PROJECT_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), '..', '..', '..', '..', '..'))
_TEMPLATE_PATH = os.path.join(_PROJECT_ROOT, 'static', 'files', 'purchase_order_template.xlsx')

# 供应商采购订单模板的数据区布局（create_supplier_workbook 及其插行 helper 共用）
_TEMPLATE_DATA_ROWS = 6
_DATA_START_ROW = 10
_DATA_ROW_HEIGHT = 20.25
_DATA_COL_MERGES = [
    (1, 2), (3, 13), (14, 18), (19, 21),
    (22, 25), (26, 29), (30, 33), (34, 36), (37, 45),
]


def _validate_template_path(template_path: str) -> str:
    """验证模板文件路径在项目目录内，防止路径遍历"""
    normalized = os.path.normpath(template_path)
    if not normalized.startswith(_PROJECT_ROOT):
        raise ValueError("模板路径超出项目目录范围")
    if not os.path.isfile(normalized):
        raise FileNotFoundError(f"模板文件不存在: {normalized}")
    return normalized


def _copy_font_style(font):
    """复制 Font 对象"""
    return Ft(name=font.name, size=font.size, bold=font.bold, italic=font.italic,
              color=font.color, underline=font.underline, strike=font.strike)


def _copy_align_style(alignment):
    """复制 Alignment 对象"""
    return Al(horizontal=alignment.horizontal, vertical=alignment.vertical,
              wrap_text=alignment.wrap_text, text_rotation=alignment.text_rotation,
              indent=alignment.indent, shrink_to_fit=alignment.shrink_to_fit)


def _copy_border_style(border):
    """复制 Border 对象"""
    def _cp(side):
        return Sd(style=side.style, color=side.color) if side.style else Sd()
    return Bd(left=_cp(border.left), right=_cp(border.right),
              top=_cp(border.top), bottom=_cp(border.bottom))


def _fill_cell(ws, row, col, value, number_format=None):
    """向模板中的指定单元格填充值，保留原有格式"""
    cell = ws.cell(row=row, column=col)
    cell.value = value
    if number_format:
        cell.number_format = number_format


def _qty_display_text(value) -> str:
    """数量展示文本：整数不带小数位、非整数最多 2 位小数。

    与前端 ``qtyDisplayText`` 同口径，保证导出 Excel 的「数量」与页面逐字一致
    （旧实现直接写 ``str(float)``，整数会渲染成 "20.0"）。
    """
    rounded = round_qty(float(value or 0))
    if rounded == int(rounded):
        return str(int(rounded))
    return f'{rounded:.2f}'.rstrip('0').rstrip('.')


def _order_breakdown_text(item: dict) -> str:
    """Excel「备注」列用的逐单明细文本：``PO-001×10；PO-002×5``。"""
    parts = item.get('order_breakdown') or []
    return '；'.join(
        f'{part["order_no"]}×{_qty_display_text(part["quantity"])}'
        for part in parts
    )


def _insert_supplier_data_rows(ws, extra_rows: int) -> None:
    """在模板数据区下方插入 extra_rows 行，并保持页脚（合计/签名区）的样式与合并。

    模板固定 6 行数据，供应商物料超出时必须插行；插行会顶掉下方的页脚，
    因此先把页脚的合并区域、单元格内容/样式、行高整体 snapshot，清空后插行，
    再按新行号原样还原。抽成独立函数是为了控制 create_supplier_workbook 长度
    （2026-10-18：该函数 125 行，超出 function_length 棘轮基线 1）。
    """
    DATA_START_ROW = _DATA_START_ROW
    TEMPLATE_DATA_ROWS = _TEMPLATE_DATA_ROWS
    insert_pos = DATA_START_ROW + TEMPLATE_DATA_ROWS
    footer_start = insert_pos

    footer_merges = []
    for m in list(ws.merged_cells.ranges):
        if m.min_row >= footer_start:
            footer_merges.append((m.min_row, m.min_col, m.max_row, m.max_col))
            ws.unmerge_cells(start_row=m.min_row, start_column=m.min_col,
                             end_row=m.max_row, end_column=m.max_col)

    footer_cells = {}
    for r in range(footer_start, ws.max_row + 1):
        for c in range(1, ws.max_column + 1):
            cell = ws.cell(row=r, column=c)
            if cell.value is not None:
                footer_cells[(r, c)] = {
                    'value': cell.value,
                    'font': _copy_font_style(cell.font),
                    'alignment': _copy_align_style(cell.alignment),
                    'border': _copy_border_style(cell.border),
                    'number_format': cell.number_format,
                }

    footer_heights = {}
    for r in range(footer_start, ws.max_row + 1):
        h = ws.row_dimensions[r].height
        if h:
            footer_heights[r] = h

    for r in range(footer_start, ws.max_row + 1):
        for c in range(1, ws.max_column + 1):
            ws.cell(row=r, column=c).value = None

    ws.insert_rows(insert_pos, amount=extra_rows)

    for min_r, min_c, max_r, max_c in footer_merges:
        ws.merge_cells(start_row=min_r + extra_rows, start_column=min_c,
                       end_row=max_r + extra_rows, end_column=max_c)

    for (r, c), info in footer_cells.items():
        new_r = r + extra_rows
        cell = ws.cell(row=new_r, column=c)
        cell.value = info['value']
        cell.font = info['font']
        cell.alignment = info['alignment']
        cell.border = info['border']
        if info['number_format']:
            cell.number_format = info['number_format']

    for r, h in footer_heights.items():
        ws.row_dimensions[r + extra_rows].height = h

    ref_row = _DATA_START_ROW
    ref_font = _copy_font_style(ws.cell(row=ref_row, column=1).font)
    ref_align = _copy_align_style(ws.cell(row=ref_row, column=1).alignment)
    full_border = Bd(left=Sd(style='thin'), right=Sd(style='thin'),
                     top=Sd(style='thin'), bottom=Sd(style='thin'))

    for i in range(extra_rows):
        new_row = insert_pos + i
        ws.row_dimensions[new_row].height = _DATA_ROW_HEIGHT

        for c in range(1, 46):
            cell = ws.cell(row=new_row, column=c)
            cell.border = full_border
            cell.font = ref_font
            cell.alignment = ref_align

        for c1, c2 in _DATA_COL_MERGES:
            ws.merge_cells(start_row=new_row, start_column=c1, end_row=new_row, end_column=c2)

        for c1, _ in _DATA_COL_MERGES:
            ws.cell(row=new_row, column=c1).value = None


def create_supplier_workbook(supplier: dict) -> Workbook:
    """基于模板文件为单个供应商创建采购订单 Excel 工作簿"""
    template_path = _validate_template_path(os.path.normpath(_TEMPLATE_PATH))
    wb = openpyxl.load_workbook(template_path)
    ws = wb.active

    supplier_name = supplier['supplier_name']
    items = supplier['items']
    supplier_address = supplier.get('address', '') or ''
    supplier_phone = supplier.get('phone', '') or ''
    supplier_contact = supplier.get('contact_person', '') or ''

    # Z06-R3：Excel 文本统一走权威公式清洗（=+-@\t\r 六字符），防 DDE 注入
    _fill_cell(ws, 4, 1, _sanitize_excel_value(f'供应商名称:{supplier_name}'))
    if not supplier_address and not supplier_phone and not supplier_contact:
        logger.warning(f"供应商'{supplier_name}'的地址/电话/联系人信息均缺失")
    _fill_cell(ws, 5, 1, _sanitize_excel_value(f'供应商地址:{supplier_address}' if supplier_address else '供应商地址:'))
    _fill_cell(ws, 6, 1, _sanitize_excel_value(f'电话:{supplier_phone}' if supplier_phone else '电话:'))
    _fill_cell(ws, 7, 1, _sanitize_excel_value(f'联系人:{supplier_contact}' if supplier_contact else '联系人:'))

    today = datetime.now()
    _fill_cell(ws, 2, 36, today, number_format='YYYY-M-D')

    ws.page_setup.fitToWidth = 1
    ws.page_setup.fitToHeight = 999
    ws.sheet_properties.pageSetUpPr = openpyxl.worksheet.properties.PageSetupProperties(fitToPage=True)
    ws.print_area = None

    # 数据区布局用模块级常量（_insert_supplier_data_rows 共用）；此处起本地别名
    # 只为让下方填充逻辑保持可读。
    TEMPLATE_DATA_ROWS = _TEMPLATE_DATA_ROWS
    DATA_START_ROW = _DATA_START_ROW

    total_rows = max(len(items), TEMPLATE_DATA_ROWS)
    extra_rows = total_rows - TEMPLATE_DATA_ROWS

    if extra_rows > 0:
        _insert_supplier_data_rows(ws, extra_rows)

    for idx in range(total_rows):
        row = DATA_START_ROW + idx
        if idx < len(items):
            item = items[idx]
            name_val = item['material_name']
            if item.get('specification'):
                name_val = f"{item['material_name']}（{item['specification']}）"
            name_val = _sanitize_excel_value(name_val)
            qty = _qty_display_text(item['quantity'])

            _fill_cell(ws, row, 1, idx + 1)
            _fill_cell(ws, row, 3, name_val)
            _fill_cell(ws, row, 14, qty, number_format='@')
            _fill_cell(ws, row, 19, _sanitize_excel_value(item.get('unit') or ''))
            _fill_cell(ws, row, 22, None)
            _fill_cell(ws, row, 26, '含')
            _fill_cell(ws, row, 30, f'=N{row}*V{row}', number_format='#,##0.00')
            _fill_cell(ws, row, 34, None)
            # AK 列（模板「备注」）承载来源订单逐单明细；无明细（旧结构）保持空白
            note = _order_breakdown_text(item)
            _fill_cell(ws, row, 37, _sanitize_excel_value(note) if note else None)
        else:
            _fill_cell(ws, row, 1, idx + 1)
            _fill_cell(ws, row, 3, None)
            _fill_cell(ws, row, 14, None)
            _fill_cell(ws, row, 19, None)
            _fill_cell(ws, row, 22, None)
            _fill_cell(ws, row, 26, '含')
            _fill_cell(ws, row, 30, f'=N{row}*V{row}', number_format='#,##0.00')
            _fill_cell(ws, row, 34, None)
            _fill_cell(ws, row, 37, None)

    summary_row = DATA_START_ROW + total_rows
    last_data_row = DATA_START_ROW + total_rows - 1

    _fill_cell(ws, summary_row, 30, f'=SUM(AD{DATA_START_ROW}:AD{last_data_row})', number_format='#,##0.00')
    _fill_cell(ws, summary_row + 1, 30, None, number_format='0%')
    _fill_cell(ws, summary_row + 2, 30, f'=AD{summary_row}*(1+AD{summary_row+1})', number_format='#,##0.00')

    return wb
