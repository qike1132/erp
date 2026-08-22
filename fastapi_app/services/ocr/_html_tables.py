"""出货单 HTML 表格解析

从 ocr_service.py 按职责拆出,行为与原实现完全一致。
"""
import logging
import re

from fastapi_app.services.ocr._text_parsers import (
    _parse_key_value_format,
    _parse_line_by_line,
    _parse_ocr_table_format,
    _parse_quantity,
    _parse_table_format,
)

logger = logging.getLogger(__name__)


def parse_html_shipping_tables(table_pages: list[dict]) -> list[dict]:
    """
    解析 RapidTable 输出的 HTML 表格，提取出货项

    与 parse_shipping_document 不同，本函数直接解析 HTML 表格结构，
    无需猜测行列关系，准确率远高于正则方案。
    """
    all_items = []
    for page in table_pages:
        html = page.get('html', '')
        if not html or '<td' not in html:
            continue
        rows = _html_table_to_rows(html)
        if len(rows) < 2:
            continue
        col_map = _detect_column_mapping(rows[0])
        if 'product_name' not in col_map and 'quantity' not in col_map:
            continue
        customer = _extract_customer_from_header_text(page.get('text', ''))
        for row in rows[1:]:
            item = _extract_item_from_row(row, col_map, customer)
            if item:
                all_items.append(item)
    return all_items

def _html_table_to_rows(html: str) -> list[list[str]]:
    """将 HTML 表格解析为二维列表"""
    rows = []
    tr_pat = re.compile('<tr[^>]*>(.*?)</tr>', re.DOTALL | re.IGNORECASE)
    td_pat = re.compile('<t[dh][^>]*>(.*?)</t[dh]>', re.DOTALL | re.IGNORECASE)
    for tr_match in tr_pat.finditer(html):
        cells = []
        for td_match in td_pat.finditer(tr_match.group(1)):
            cell_text = td_match.group(1).strip()
            cell_text = re.sub('<[^>]+>', '', cell_text)
            cell_text = cell_text.replace('&nbsp;', ' ').replace('&amp;', '&')
            cell_text = cell_text.strip()
            cells.append(cell_text)
        if cells:
            rows.append(cells)
    return rows

def _detect_column_mapping(header_row: list[str]) -> dict[str, int]:
    """根据表头关键词检测列名到列索引的映射"""
    col_map = {}
    header_keywords = {'product_name': ['产品名称', '产品', '品名', '商品', '物料名称', '物料', '货品'], 'quantity': ['出货数量', '数量', '数', 'qty', 'QTY', '出库数量'], 'customer': ['客户名称', '客户', '收货单位', '买方', '收货'], 'note': ['备注', '说明', '摘要', 'Remark', '备注说明']}
    for col_idx, cell in enumerate(header_row):
        for col_name, keywords in header_keywords.items():
            if col_name in col_map:
                continue
            for kw in keywords:
                if kw in cell:
                    col_map[col_name] = col_idx
                    break
    return col_map

def _extract_item_from_row(row: list[str], col_map: dict[str, int], default_customer: str='') -> dict | None:
    """从一行数据中提取出货项"""

    def _get_col(name: str) -> str:
        idx = col_map.get(name)
        if idx is not None and idx < len(row):
            return row[idx].strip()
        return ''
    product_name = _get_col('product_name')
    quantity_str = _get_col('quantity')
    if not product_name or not quantity_str:
        return None
    if re.match('^\\d+\\.?\\d*$', product_name):
        return None
    quantity = _parse_quantity(quantity_str)
    if quantity <= 0:
        return None
    customer = _get_col('customer') or default_customer
    note = _get_col('note')
    return {'customer': customer, 'product_name': product_name, 'quantity': quantity, 'note': note}

def _extract_customer_from_header_text(text: str) -> str:
    """从文档文本的前部提取客户名"""
    match = re.search('客\\s*户[：:]\\s*([^\\n,，\\s]+)', text[:500])
    if match:
        return match.group(1).strip()
    match2 = re.search('([\\u4e00-\\u9fa5]{2,}(公司|集团|科技|有限))', text[:500])
    if match2:
        return match2.group(1).strip()
    return ''

def parse_shipping_document(pages: list[dict]) -> list[dict]:
    """
    解析出货单 PDF 提取的文本，抽取关键字段

    支持的出货单格式:
    - 表格型出货单（含产品/数量/客户等列）
    - 简单出货单（含"产品"/"数量"等关键字）

    Args:
        pages: OCR 提取的页面文本列表

    Returns:
        解析后的出货项列表，每项包含:
        - customer: 客户名称
        - product_name: 产品名称
        - quantity: 出货数量
        - note: 备注
    """
    all_text = '\n'.join(p['text'] for p in pages)
    lines = [line.strip() for line in all_text.split('\n') if line.strip()]
    items = []
    ocr_table_items = _parse_ocr_table_format(lines, all_text)
    if ocr_table_items:
        items.extend(ocr_table_items)
        return items
    table_items = _parse_table_format(lines, all_text)
    if table_items:
        items.extend(table_items)
        return items
    kv_items = _parse_key_value_format(lines, all_text)
    if kv_items:
        items.extend(kv_items)
        return items
    line_items = _parse_line_by_line(lines)
    if line_items:
        items.extend(line_items)
    return items