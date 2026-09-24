"""OCR 文本格式解析(表格/滑动窗口/键值/逐行)

从 ocr_service.py 按职责拆出,行为与原实现完全一致。
"""
import logging
import re

logger = logging.getLogger(__name__)


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
        pass  # defensive: 可选 ValueError 静默处理,不影响主流程
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
