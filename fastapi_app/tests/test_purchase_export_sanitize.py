"""Z06-R3 + F2-3：采购中心打印 HTML 转义 + Excel 公式注入清洗。"""
import re

from fastapi_app.api.v1.endpoints.purchase_center.export_utils import (
    create_supplier_workbook,
)

# Excel 把首字符为这四个字符的单元格当公式/DDE 载荷解析。`\t` **不在**此列：
# 它正是权威清洗器加的前缀（打断解析的防御标记），列进去会让断言与修复互相矛盾。
_FORMULA_LEADERS = ('=', '+', '-', '@')
_TD_RE = re.compile(r'<td[^>]*>(.*?)</td>', re.S)








def test_supplier_workbook_sanitizes_formula_cells():
    supplier = {
        'supplier_name': '=cmd|\' /C calc\'!A0',
        'address': '=1+1',
        'phone': '@SUM(A1)',
        'contact_person': '-2+3',
        'items': [{
            'material_name': '=1+1',
            'specification': '+2+2',
            'quantity': 1,
            'unit': '=3+3',
        }],
    }

    wb = create_supplier_workbook(supplier)
    ws = wb.active

    # 带中文标签的单元格本身不以 / + - @ 开头，注入不成立；仍断言不以危险字符开头
    for row in (4, 5, 6, 7):
        assert not str(ws.cell(row, 1).value).startswith(('=', '+', '-', '@'))
    # 纯文本单元格必须加权威清洗前缀（\t），openpyxl 不会当公式执行
    assert ws.cell(10, 3).value.startswith('\t')
    assert ws.cell(10, 19).value.startswith('\t')
    # 模板公式列必须保留为公式（不能被文本清洗破坏）
    assert ws.cell(10, 30).value.startswith('=N')
