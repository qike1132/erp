"""皮套导出（Excel .xlsx，openpyxl）"""
import io

from openpyxl import Workbook

from utils.report_exporter import _sanitize_excel_value


def _cell(value) -> object:
    """防公式注入。

    **复用** `utils/report_exporter._sanitize_excel_value` 这一权威实现，不要在仓库里
    维护第二套口径：原本地实现只判 `= + - @` 且用 `'` 前缀，漏了权威集的 `\\t`/`\\r`，
    两处行为已发生分歧（2026-10-02 第二轮审计）。
    """
    if value is None:
        return ''
    return _sanitize_excel_value(str(value))


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


def _inventory_row(r: dict, prefix: str = '') -> list:
    return [
        prefix + str(_cell(r.get('name'))), _cell(r.get('barcode')), _cell(r.get('unit')),
        int(r.get('initial_stock') or 0), int(r.get('total_in') or 0),
        int(r.get('total_out') or 0), int(r.get('current_stock') or 0),
    ]


def inventory_to_xlsx(rows: list[dict], title: str = '库存汇总') -> bytes:
    """库存汇总（主件 + 缩进配件）→ xlsx 字节流。"""
    wb = Workbook()
    ws = wb.active
    ws.title = title[:31]
    ws.append(['皮套', '条码', '单位', '期初', '入库', '出库', '结存'])
    for r in rows:
        ws.append(_inventory_row(r, ''))
        for child in r.get('children', []):
            ws.append(_inventory_row(child, '    '))
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
