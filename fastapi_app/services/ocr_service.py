"""
离线 OCR 出货单识别服务

使用 RapidOCR 对 PDF / 图片出货单进行离线文本提取与字段解析，
将解析后的结构化数据写入暂存区（staging_stock_out）。

支持格式：
- PDF 文件（文本型 / 图片型）
- 图片文件（PNG, JPG, JPEG, BMP, TIFF, WEBP）
"""
import asyncio
import contextlib
import logging
import os
import re
import threading
import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from fastapi_app.services.ocr_fuzzy_match import (
    fuzzy_match_customer,
    fuzzy_match_product,
)
from fastapi_app.shared_models import Customer, Product, StagingStockOut

logger = logging.getLogger(__name__)
_progress_store: dict[str, dict] = {}
_progress_lock = threading.Lock()
_PROGRESS_MAX_AGE = 3600

def _cleanup_progress_store():
    import time
    now = time.time()
    with _progress_lock:
        expired_keys = [k for k, v in _progress_store.items() if now - v.get('_created_at', 0) > _PROGRESS_MAX_AGE]
        for k in expired_keys:
            del _progress_store[k]

def create_progress() -> str:
    import time
    _cleanup_progress_store()
    task_id = str(uuid.uuid4())
    with _progress_lock:
        _progress_store[task_id] = {'status': 'pending', 'percent': 0, 'message': '等待处理...', 'filename': '', '_created_at': time.time()}
    return task_id

def get_progress(task_id: str) -> dict:
    with _progress_lock:
        return _progress_store.get(task_id, {'status': 'not_found', 'percent': 0, 'message': '任务不存在'}).copy()

def _update_progress(task_id: str, **kwargs):
    with _progress_lock:
        if task_id in _progress_store:
            if 'percent' in kwargs and kwargs.get('status') != 'error' and ('percent' in _progress_store[task_id]):
                kwargs['percent'] = max(kwargs['percent'], _progress_store[task_id]['percent'])
            _progress_store[task_id].update(kwargs)
_pdf_extracter = None
_img_extracter = None
_table_extracter = None
IMAGE_EXTENSIONS = {'.png', '.jpg', '.jpeg', '.bmp', '.tiff', '.tif', '.webp'}

def _get_pdf_extracter():
    """延迟初始化 RapidOCRPDF 提取器（避免模块导入时加载模型）"""
    global _pdf_extracter
    if _pdf_extracter is None:
        try:
            from rapidocr_pdf import RapidOCRPDF
            _pdf_extracter = RapidOCRPDF()
            logger.info('RapidOCRPDF 提取器初始化成功')
        except ImportError:
            raise RuntimeError('rapidocr_pdf 未安装，请执行: pip install rapidocr_pdf') from None
    return _pdf_extracter

def _get_img_extracter():
    """延迟初始化 RapidOCR 图片识别器（避免模块导入时加载模型）"""
    global _img_extracter
    if _img_extracter is None:
        try:
            from rapidocr import RapidOCR
            _img_extracter = RapidOCR()
            logger.info('RapidOCR 图片识别器初始化成功')
        except ImportError:
            raise RuntimeError('rapidocr 未安装，请执行: pip install rapidocr') from None
    return _img_extracter

def _get_table_extracter():
    """延迟初始化 RapidTable 表格结构识别器"""
    global _table_extracter
    if _table_extracter is None:
        try:
            from rapid_table import ModelType, RapidTable, RapidTableInput
            input_args = RapidTableInput(model_type=ModelType.SLANETPLUS)
            _table_extracter = RapidTable(input_args)
            logger.info('RapidTable (SLANet-plus) 表格识别器初始化成功')
        except ImportError:
            raise RuntimeError('rapid_table 未安装，请执行: pip install rapid-table') from None
    return _table_extracter

def extract_text_from_pdf(pdf_content: bytes) -> list[dict]:
    """
    从 PDF 文件提取文本内容

    使用 RapidOCRPDF 的完整流程:
    1. 提取文本型页面的直接文本
    2. 对图片型页面进行 OCR 识别
    3. 合并结果

    Args:
        pdf_content: PDF 文件字节内容

    Returns:
        列表，每项包含 {"page": 页码, "text": 文本内容}
    """
    from rapidocr_pdf import RapidOCRPDF
    extracter = _get_pdf_extracter()
    pdf_data = RapidOCRPDF.load_pdf(pdf_content)
    txts_dict, need_ocr_idxs = extracter.extract_texts(pdf_data, force_ocr=False, page_num_list=None)
    ocr_res_dict = {}
    if need_ocr_idxs:
        ocr_res_dict = extracter.get_ocr_res_streaming(pdf_data, need_ocr_idxs)
    merged = extracter.merge_direct_ocr(txts_dict, ocr_res_dict)
    pages = []
    for item in merged:
        if isinstance(item, (list, tuple)) and len(item) >= 2:
            page_num = item[0]
            text = item[1] if isinstance(item[1], str) else str(item[1])
            pages.append({'page': page_num, 'text': text})
    return pages

def extract_text_from_image(image_content: bytes) -> list[dict]:
    """
    从图片文件提取文本内容

    使用 RapidOCR 对图片进行直接 OCR 识别。

    Args:
        image_content: 图片文件字节内容

    Returns:
        列表，每项包含 {"page": 页码(固定0), "text": 文本内容}
    """
    import numpy as np
    extracter = _get_img_extracter()
    img_array = np.frombuffer(image_content, dtype=np.uint8)
    import cv2
    img = cv2.imdecode(img_array, cv2.IMREAD_COLOR)
    if img is None:
        return []
    result = extracter(img)
    if result.txts is None:
        return []
    text = '\n'.join(result.txts)
    return [{'page': 0, 'text': text}]

def extract_text(file_content: bytes, filename: str='') -> list[dict]:
    """
    统一入口：根据文件类型自动选择 PDF 或图片 OCR 提取

    Args:
        file_content: 文件字节内容
        filename: 文件名（用于判断类型）

    Returns:
        列表，每项包含 {"page": 页码, "text": 文本内容}
    """
    ext = os.path.splitext(filename or '')[1].lower()
    if ext == '.pdf':
        return extract_text_from_pdf(file_content)
    elif ext in IMAGE_EXTENSIONS:
        return extract_text_from_image(file_content)
    else:
        try:
            return extract_text_from_pdf(file_content)
        except (ValueError, OSError):
            return extract_text_from_image(file_content)

def extract_table_structure(file_content: bytes, filename: str='') -> list[dict]:
    """
    使用 RapidTable 提取文档中的表格结构

    与 extract_text 不同，本函数直接输出 HTML 表格结构，
    保留了行列对应关系，无需后置正则猜测。
    """
    import cv2
    import numpy as np
    ext = os.path.splitext(filename or '')[1].lower()
    is_pdf = ext == '.pdf'
    page_images = []
    if is_pdf:
        page_images = _pdf_to_images(file_content)
    else:
        img_array = np.frombuffer(file_content, dtype=np.uint8)
        img = cv2.imdecode(img_array, cv2.IMREAD_COLOR)
        if img is not None:
            page_images = [img]
    if not page_images:
        return []
    table_engine = _get_table_extracter()
    ocr_engine = _get_img_extracter()
    results = []
    for page_idx, img in enumerate(page_images):
        try:
            ocr_res = ocr_engine(img)
            ocr_results = [ocr_res.boxes, ocr_res.txts, ocr_res.scores]
            table_res = table_engine(img, ocr_results)
            html_table = table_res.pred_html or ''
            text = '\n'.join(ocr_res.txts) if ocr_res.txts else ''
            results.append({'page': page_idx, 'html': html_table, 'text': text})
        except (ValueError, TypeError, OSError) as e:
            logger.warning(f'RapidTable 第{page_idx}页识别失败: {e}')
            continue
    return results

def _pdf_to_images(pdf_content: bytes) -> list:
    """将 PDF 每一页转为 numpy 图片数组"""
    import cv2
    import fitz
    import numpy as np
    doc = fitz.open(stream=pdf_content, filetype='pdf')
    images = []
    try:
        for page in doc:
            pix = page.get_pixmap(dpi=200)
            img_data = pix.tobytes('png')
            img_array = np.frombuffer(img_data, dtype=np.uint8)
            img = cv2.imdecode(img_array, cv2.IMREAD_COLOR)
            if img is not None:
                images.append(img)
    finally:
        doc.close()
    return images

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

def _parse_ocr_table_format(lines: list[str], all_text: str) -> list[dict]:
    """
    解析 OCR 输出的表格格式

    OCR 引擎识别表格时，通常将每个单元格作为独立文本行输出，
    导致原本同一行的多列数据变成了多行。

    典型 OCR 输出:
    产品名称
    数量
    备注
    红色手提包
    100
    加急
    蓝色钱包
    200
    常规

    也支持表头关键词合并在同一行的情况:
    客户名称产品名称
    出货数量
    MINISO国际
    23cm企鹅公仔
    10000

    本函数通过检测表头关键词来确定列数和列顺序，
    然后按固定列数将后续行重新组合为数据行。
    """
    items = []
    header_keywords = {'product_name': ['产品名称', '产品', '品名', '商品', '物料'], 'quantity': ['出货数量', '数量', '数', 'qty', 'QTY'], 'customer': ['客户名称', '客户', '收货', '买方'], 'note': ['备注', '说明', '摘要', 'Remark', '备注说明']}
    line_col_map = {}
    used_cols = set()
    header_end = 0
    for i, line in enumerate(lines):
        line_stripped = line.strip()
        if re.search('[：:]\\s*\\S', line_stripped):
            continue
        found_in_line = []
        for col_name, keywords in header_keywords.items():
            if col_name in used_cols:
                continue
            for kw in keywords:
                if kw in line_stripped:
                    found_in_line.append(col_name)
                    break
        if found_in_line:
            if len(found_in_line) > 1:
                col_positions = []
                for col_name in found_in_line:
                    keywords = header_keywords[col_name]
                    for kw in keywords:
                        pos = line_stripped.find(kw)
                        if pos >= 0:
                            col_positions.append((pos, col_name))
                            break
                col_positions.sort()
                for _, col_name in col_positions:
                    if col_name not in used_cols:
                        line_col_map[i] = line_col_map.get(i, [])
                        if isinstance(line_col_map[i], str):
                            line_col_map[i] = [line_col_map[i]]
                        if col_name not in (line_col_map[i] if isinstance(line_col_map[i], list) else [line_col_map[i]]):
                            line_col_map[i].append(col_name)
                            used_cols.add(col_name)
                            header_end = max(header_end, i)
            else:
                col_name = found_in_line[0]
                if col_name not in used_cols:
                    line_col_map[i] = col_name
                    used_cols.add(col_name)
                    header_end = max(header_end, i)
    expanded_map = {}
    for line_idx, col in line_col_map.items():
        if isinstance(col, list):
            for j, col_name in enumerate(col):
                virtual_idx = line_idx + j * 0.5
                expanded_map[virtual_idx] = col_name
        else:
            expanded_map[line_idx] = col
    col_names_found = set(expanded_map.values())
    if 'product_name' not in col_names_found or 'quantity' not in col_names_found:
        return []
    sorted_keys = sorted(expanded_map.keys())
    col_order = [expanded_map[k] for k in sorted_keys]
    num_cols = len(col_order)
    header_start = int(sorted_keys[0])
    customer = _extract_customer_from_header(lines[:header_start + 1])
    data_start = header_end + 1
    data_lines = lines[data_start:]
    filtered_data = []
    for line in data_lines:
        stripped = line.strip()
        if not stripped:
            continue
        if re.match('^[-=\\s]+$', stripped):
            continue
        if re.search('^合计|^总计|^小计|^签章|^第\\s*\\d+\\s*页|^共\\s*\\d+\\s*页', stripped):
            continue
        filtered_data.append(stripped)
    for i in range(0, len(filtered_data) - num_cols + 1, num_cols):
        row_values = filtered_data[i:i + num_cols]
        row_dict = {}
        for col_idx, col_name in enumerate(col_order):
            if col_idx < len(row_values):
                row_dict[col_name] = row_values[col_idx]
        product_name = row_dict.get('product_name', '').strip()
        quantity_str = row_dict.get('quantity', '').strip()
        if not product_name or not quantity_str:
            continue
        if re.match('^\\d+$', product_name) and 'product_name' in col_order:
            continue
        quantity = _parse_quantity(quantity_str)
        if quantity <= 0:
            continue
        row_customer = row_dict.get('customer', '').strip() or customer
        note = row_dict.get('note', '').strip()
        items.append({'customer': row_customer, 'product_name': product_name, 'quantity': quantity, 'note': note})
    if not items and len(filtered_data) >= 2:
        items = _parse_ocr_sliding_window(filtered_data, col_order, customer)
    return items

def _parse_ocr_sliding_window(data_lines: list[str], col_order: list[str], default_customer: str) -> list[dict]:
    """
    使用滑动窗口方式在 OCR 输出中匹配产品-数量对

    当表格列对齐不严格时，按固定间隔分组可能失败。
    此函数寻找 "非数字行 + 数字行" 的模式来提取数据。
    """
    items = []
    num_cols = len(col_order)
    try:
        product_col_idx = col_order.index('product_name')
        quantity_col_idx = col_order.index('quantity')
        quantity_col_idx - product_col_idx
    except ValueError:
        pass
    i = 0
    while i < len(data_lines):
        line = data_lines[i].strip()
        if re.match('^\\d+\\.?\\d*$', line):
            i += 1
            continue
        if re.search('[\\u4e00-\\u9fa5a-zA-Z]', line):
            product_name = line
            quantity = 0
            quantity_idx = None
            note = ''
            for j in range(i + 1, min(i + num_cols + 2, len(data_lines))):
                next_line = data_lines[j].strip()
                qty_match = re.match('^(\\d+\\.?\\d*)$', next_line)
                if qty_match:
                    quantity = _parse_quantity(qty_match.group(1))
                    quantity_idx = j
                    break
            if quantity > 0 and product_name:
                if quantity_idx is not None and quantity_idx + 1 < len(data_lines):
                    potential_note = data_lines[quantity_idx + 1].strip()
                    if not re.match('^\\d+\\.?\\d*$', potential_note) and len(potential_note) < 20:
                        if not re.search('[\\u4e00-\\u9fa5a-zA-Z]{2,}', potential_note):
                            note = potential_note
                row_customer = default_customer
                for k in range(max(0, i - num_cols), i):
                    c_match = re.search('([\\u4e00-\\u9fa5]{2,}(?:公司|集团|科技|有限))', data_lines[k])
                    if c_match:
                        row_customer = c_match.group(1)
                        break
                items.append({'customer': row_customer, 'product_name': product_name, 'quantity': quantity, 'note': note})
                i = quantity_idx + 1 if quantity_idx else i + 1
                continue
        i += 1
    return items

def _parse_table_format(lines: list[str], all_text: str) -> list[dict]:
    """
    解析表格型出货单

    典型格式:
    产品名称    数量    客户    备注
    XXX产品     100    客户A   备注1
    YYY产品     200    客户B   备注2
    """
    items = []
    header_idx = -1
    header_line = ''
    for i, line in enumerate(lines):
        if re.search('产品|品名|商品', line) and re.search('数量|数|qty', line, re.IGNORECASE):
            header_idx = i
            header_line = line
            break
    if header_idx < 0:
        return []
    col_positions = _detect_column_positions(header_line)
    if not col_positions:
        return []
    customer = _extract_customer_from_header(lines[:header_idx + 1])
    for i in range(header_idx + 1, len(lines)):
        line = lines[i]
        if not line or re.match('^[-=\\s]+$', line):
            continue
        if re.search('合计|总计|小计|签章|日期|页码|第\\s*\\d+\\s*页', line):
            continue
        row_data = _extract_row_by_positions(line, col_positions)
        product_name = row_data.get('product_name', '').strip()
        quantity_str = row_data.get('quantity', '').strip()
        note = row_data.get('note', '').strip()
        if not product_name or not quantity_str:
            continue
        quantity = _parse_quantity(quantity_str)
        if quantity <= 0:
            continue
        row_customer = row_data.get('customer', '').strip() or customer
        items.append({'customer': row_customer, 'product_name': product_name, 'quantity': quantity, 'note': note})
    return items

def _parse_key_value_format(lines: list[str], all_text: str) -> list[dict]:
    """
    解析键值对格式出货单

    典型格式:
    客户：XXX公司
    产品：YYY产品  数量：100
    产品：ZZZ产品  数量：200
    """
    items = []
    current_customer = ''
    customer_match = re.search('客\\s*户[：:]\\s*([^\\n,，\\s]+)', all_text)
    if customer_match:
        current_customer = customer_match.group(1).strip()
    for line in lines:
        product_match = re.search('(?:产品|品名|商品)[：:]\\s*([^\\s,，]+)', line)
        quantity_match = re.search('(?:数量|数|qty)[：:]\\s*(\\d+)', line, re.IGNORECASE)
        if product_match:
            product_name = product_match.group(1).strip()
            quantity = _parse_quantity(quantity_match.group(1)) if quantity_match else 0
            if quantity > 0:
                note_match = re.search('(?:备注|说明)[：:]\\s*(.+?)(?:\\s{2,}|$)', line)
                note = note_match.group(1).strip() if note_match else ''
                items.append({'customer': current_customer, 'product_name': product_name, 'quantity': quantity, 'note': note})
    return items

def _parse_line_by_line(lines: list[str]) -> list[dict]:
    """
    逐行解析出货单（兜底策略）

    尝试从每一行中提取产品名和数量。
    典型格式：产品名  数量  (可能还有其他字段)
    """
    items = []
    customer = ''
    for line in lines[:10]:
        c_match = re.search('客\\s*户[：:]\\s*([^\\n,，\\s]+)', line)
        if c_match:
            customer = c_match.group(1).strip()
            break
        c_match2 = re.search('([\\u4e00-\\u9fa5]{2,}(?:公司|集团|科技|有限))', line)
        if c_match2:
            customer = c_match2.group(1).strip()
            break
    for line in lines:
        if re.search('^[\\s\\d\\-=/]+$', line):
            continue
        if re.search('出货|发货|签章|日期|页码|第\\s*\\d+\\s*页|合计|总计|小计', line):
            continue
        if len(line) < 2:
            continue
        match = re.search('([\\u4e00-\\u9fa5a-zA-Z0-9][\\u4e00-\\u9fa5a-zA-Z0-9\\s\\-]*[\\u4e00-\\u9fa5a-zA-Z0-9])\\s+(\\d+)\\s*$', line)
        if match:
            product_name = match.group(1).strip()
            quantity = int(match.group(2))
            if quantity > 0 and len(product_name) >= 2:
                items.append({'customer': customer, 'product_name': product_name, 'quantity': quantity, 'note': ''})
                continue
        parts = re.split('\\s{2,}', line)
        if len(parts) >= 2:
            product_name = parts[0].strip()
            qty_match = re.search('(\\d+)', parts[1])
            if qty_match and len(product_name) >= 2:
                quantity = int(qty_match.group(1))
                if quantity > 0:
                    note = parts[2].strip() if len(parts) > 2 else ''
                    items.append({'customer': customer, 'product_name': product_name, 'quantity': quantity, 'note': note})
    return items

def _detect_column_positions(header_line: str) -> dict | None:
    """检测表头中各列的起始位置"""
    positions = {}
    patterns = {'product_name': '产品|品名|商品|物料', 'quantity': '数量|数|qty|QTY', 'customer': '客户|收货|买方', 'note': '备注|说明|摘要|Remark'}
    for col_name, pattern in patterns.items():
        match = re.search(pattern, header_line, re.IGNORECASE)
        if match:
            positions[col_name] = match.start()
    if 'product_name' not in positions or 'quantity' not in positions:
        return None
    return positions

def _extract_row_by_positions(line: str, col_positions: dict) -> dict:
    """根据列位置从行中提取各列数据"""
    result = {}
    sorted_cols = sorted(col_positions.items(), key=lambda x: x[1])
    for i, (col_name, start_pos) in enumerate(sorted_cols):
        end_pos = sorted_cols[i + 1][1] if i + 1 < len(sorted_cols) else len(line)
        if start_pos < len(line):
            value = line[start_pos:end_pos].strip()
            result[col_name] = value
    return result

def _extract_customer_from_header(lines: list[str]) -> str:
    """从表头区域提取客户名"""
    for line in lines:
        match = re.search('客\\s*户[：:]\\s*([^\\n,，\\s]+)', line)
        if match:
            return match.group(1).strip()
        match2 = re.search('([\\u4e00-\\u9fa5]{2,}(?:公司|集团|科技|有限))', line)
        if match2:
            return match2.group(1).strip()
    return ''

def _parse_quantity(value: str) -> int:
    """解析数量字符串"""
    cleaned = re.sub('[^\\d.]', '', str(value))
    try:
        qty = int(float(cleaned))
        return qty
    except (ValueError, TypeError):
        return 0

async def import_staging_stockouts_from_file(db: AsyncSession, file_content: bytes, session_id: str, filename: str='', task_id: str='') -> tuple[int, str, list[str]]:
    """
    从 PDF / 图片出货单导入出货到暂存区

    流程:
    1. 根据文件类型自动选择 PDF 或图片 OCR 提取文本
    2. 解析出货单字段
    3. 匹配产品、校验库存
    4. 写入暂存区

    Args:
        db: 异步数据库会话
        file_content: 文件字节内容
        session_id: 会话 ID
        filename: 原始文件名（用于日志和类型判断）
        task_id: 进度追踪 ID（可选）

    Returns:
        (imported_count, message, errors)
    """

    def _prog(**kwargs):
        if task_id:
            _update_progress(task_id, **kwargs)
    try:
        _prog(status='processing', message=f'正在识别 {filename}...', filename=filename, percent=5)
        await asyncio.sleep(0)
        ext = os.path.splitext(filename or '')[1].lower()
        is_pdf = ext == '.pdf'
        file_type = 'PDF' if is_pdf else '图片'
        if is_pdf:
            _prog(message=f'正在加载 PDF {filename}...', percent=8)
        else:
            _prog(message=f'正在读取图片 {filename}...', percent=8)
        await asyncio.sleep(0)
        loop = asyncio.get_running_loop()
        parsed_items = []
        table_pages = []
        text_pages = []
        try:
            _prog(message='正在识别表格结构...', percent=12)
            table_pages = await loop.run_in_executor(None, extract_table_structure, file_content, filename)
            if table_pages:
                parsed_items = parse_html_shipping_tables(table_pages)
                logger.info(f'RapidTable 表格识别: {filename}, 识别到 {len(table_pages)} 页表格, 解析出 {len(parsed_items)} 个出货项')
        except (ValueError, TypeError, OSError) as e:
            logger.warning(f'RapidTable 表格识别失败，将回退到文本模式: {e}')
        if not parsed_items:
            _prog(message='正在使用文本识别模式...', percent=30)
            ocr_future = loop.run_in_executor(None, extract_text, file_content, filename)
            _ocr_simulated_pct = 30
            _ocr_simulated_msgs = [(35, '正在识别文字...'), (42, '正在提取文本内容...'), (50, '正在进行文字识别...'), (58, '正在整理识别结果...'), (65, '即将完成文本提取...')]

            async def _simulate_ocr_progress():
                nonlocal _ocr_simulated_pct
                for pct, msg in _ocr_simulated_msgs:
                    await asyncio.sleep(0.4)
                    _ocr_simulated_pct = pct
                    _prog(message=msg, percent=pct)
            sim_task = asyncio.create_task(_simulate_ocr_progress())
            try:
                text_pages = await ocr_future
            finally:
                sim_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await sim_task
            if not text_pages:
                _prog(status='error', message='文件无法提取文本内容', percent=0)
                return (0, '文件无法提取文本内容，可能是空白文件或图片质量过低', [])
            final_ocr_pct = max(70, _ocr_simulated_pct)
            _prog(message=f'{file_type}文本提取完成，共 {len(text_pages)} 页', percent=final_ocr_pct)
            await asyncio.sleep(0.05)
            logger.info(f"{file_type} OCR 提取完成: {filename}, 共 {len(text_pages)} 页, 文本长度: {sum(len(p['text']) for p in text_pages)}")
            _prog(message='正在解析出货单字段...', percent=75)
            await asyncio.sleep(0.05)
            parsed_items = parse_shipping_document(text_pages)
        if not parsed_items:
            preview_pages = table_pages or text_pages
            raw_text_preview = '\n'.join(p.get('text', '')[:200] for p in preview_pages[:3])
            logger.warning(f'{file_type} 解析未识别到出货项: {filename}\n原始文本:\n{raw_text_preview}')
            _prog(status='error', message='无法识别出货信息', percent=0)
            return (0, '无法从文件中识别出货信息，请确认文件格式是否正确', [])
        _prog(message=f'解析完成，识别到 {len(parsed_items)} 个出货项', percent=80)
        await asyncio.sleep(0.05)
        _prog(message='正在匹配产品和客户...', percent=85)
        await asyncio.sleep(0.05)
        result = await db.execute(select(Product))
        all_products = result.scalars().all()
        product_map = {p.name.lower().strip(): p for p in all_products}
        product_map.update({p.barcode: p for p in all_products if p.barcode})
        result = await db.execute(select(Customer))
        all_customers = result.scalars().all()
        _prog(message=f'正在写入暂存区（共{len(parsed_items)}项）...', percent=90)
        await asyncio.sleep(0.05)
        imported = 0
        errors = []
        for idx, item in enumerate(parsed_items, start=1):
            try:
                product_name = str(item.get('product_name', '')).strip()
                customer = str(item.get('customer', '')).strip()
                quantity = item.get('quantity', 0)
                note = str(item.get('note', '')).strip()
                if not product_name or quantity <= 0:
                    continue
                if len(parsed_items) > 1 and (idx % 5 == 0 or idx == len(parsed_items)):
                    item_pct = 90 + int(idx / len(parsed_items) * 6)
                    _prog(message=f'正在处理第 {idx}/{len(parsed_items)} 项...', percent=item_pct)
                    await asyncio.sleep(0.02)
                product, match_confidence = fuzzy_match_product(product_name, all_products, product_map)
                matched_customer, customer_confidence = fuzzy_match_customer(customer, all_customers)
                if matched_customer and customer_confidence >= 0.7:
                    if customer_confidence < 1.0:
                        logger.info(f"客户模糊匹配: OCR='{customer}' -> DB='{matched_customer.name}', 置信度={customer_confidence:.2f}")
                    customer = matched_customer.name
                is_validated = False
                validation_error = ''
                product_id = None
                stock_check_passed = False
                stock_check_message = ''
                match_info_parts = []
                if product:
                    is_validated = True
                    product_id = product.id
                    original_ocr_name = product_name
                    product_name = product.name
                    if match_confidence < 1.0:
                        match_info_parts.append(f"产品模糊匹配: OCR='{original_ocr_name}'→'{product_name}'({match_confidence:.0%})")
                    if product.current_stock < quantity:
                        stock_check_message = f'库存不足，当前库存: {product.current_stock}'
                    else:
                        stock_check_passed = True
                        stock_check_message = f'库存充足，当前库存: {product.current_stock}'
                else:
                    validation_error = f'产品"{product_name}"不存在'
                if match_info_parts:
                    note = note + '；' + '；'.join(match_info_parts) if note else '；'.join(match_info_parts)
                staging_stockout = StagingStockOut(session_id=session_id, customer=customer, stockout_date=datetime.now(), product_name=product_name, product_barcode='', product_id=product_id, quantity=quantity, note=note, is_validated=is_validated, validation_error=validation_error, stock_check_passed=stock_check_passed, stock_check_message=stock_check_message, status='pending')
                db.add(staging_stockout)
                imported += 1
            except (ValueError, TypeError, OSError) as e:
                errors.append(f'第{idx}项处理失败: {str(e)}')
                continue
        _prog(message='正在保存到数据库...', percent=98)
        await asyncio.sleep(0.05)
        await db.commit()
        result_msg = f'成功从{file_type}识别并导入 {imported} 个出货到暂存区'
        if errors:
            result_msg += f"。错误: {'; '.join(errors[:5])}"
        _prog(status='done', message=result_msg, percent=100)
        return (imported, result_msg, errors[:10] if errors else [])
    except (ValueError, TypeError, OSError) as e:
        await db.rollback()
        logger.error(f'OCR 导入失败: {str(e)}', exc_info=True)
        _prog(status='error', message=f'识别导入失败: {str(e)}', percent=0)
        return (0, f'识别导入失败: {str(e)}', [])
import_staging_stockouts_from_pdf = import_staging_stockouts_from_file
