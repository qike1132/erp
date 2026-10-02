"""皮套导出（Excel .xlsx，openpyxl）"""
import io

from openpyxl import Workbook

MAX_EXPORT_ROWS = 20000


def _cell(value) -> object:
    """防公式注入：以 = + - @ 开头的文本加前导单引号。"""
    if value is None:
        return ''
    text = str(value)
    if text[:1] in ('=', '+', '-', '@'):
        return "'" + text
    return text


def movements_to_xlsx(rows: list[dict], title: str = '出入库流水') -> bytes:
    """出入库流水 → xlsx 字节流。"""
    wb = Workbook()
    ws = wb.active
    ws.title = title[:31]
    ws.append(['单号', '皮套', '条码', '方向', '数量', '客户', '日期', '备注'])
    for r in rows:
        ws.append([
            _cell(r.get('movement_no')), _cell(r.get('case_name')), _cell(r.get('case_barcode')),
            '入库' if r.get('direction') == 'in' else '出库', int(r.get('quantity') or 0),
            _cell(r.get('customer')), _cell(r.get('movement_date')), _cell(r.get('note')),
        ])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def inventory_to_xlsx(rows: list[dict], title: str = '库存汇总') -> bytes:
    """库存汇总（主件 + 缩进配件）→ xlsx 字节流。"""
    wb = Workbook()
    ws = wb.active
    ws.title = title[:31]
    ws.append(['皮套', '条码', '单位', '期初', '结存'])
    for r in rows:
        ws.append([
            _cell(r.get('name')), _cell(r.get('barcode')), _cell(r.get('unit')),
            int(r.get('initial_stock') or 0), int(r.get('current_stock') or 0),
        ])
        for child in r.get('children', []):
            ws.append([
                '    ' + str(_cell(child.get('name'))), _cell(child.get('barcode')),
                _cell(child.get('unit')), int(child.get('initial_stock') or 0),
                int(child.get('current_stock') or 0),
            ])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
