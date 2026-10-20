"""Z06-R3：采购中心打印 HTML 转义 + Excel 公式注入清洗。"""
from types import SimpleNamespace

from fastapi_app.api.v1.endpoints.purchase_center.export_utils import (
    create_supplier_workbook,
    generate_normal_summary_print,
)


def test_print_html_escapes_database_fields():
    order = SimpleNamespace(
        id=1, order_no='<script>alert(1)</script>', supplier_name='A&B',
        customer_name='<img src=x onerror=alert(1)>', order_date='2026-10-20',
    )
    item = SimpleNamespace(
        material_name='<b>=cmd</b>', specification='"x"', quantity=1,
        unit='<i>个</i>', material_category='<u>类</u>',
    )

    html = generate_normal_summary_print([order], {1: [item]})

    assert '<script>' not in html
    assert '&lt;script&gt;' in html
    assert '<img src=x' not in html
    assert '&lt;img src=x' in html
    assert 'A&amp;B' in html


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
