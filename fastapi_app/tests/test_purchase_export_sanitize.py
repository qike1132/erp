"""Z06-R3 + F2-3：采购中心打印 HTML 转义 + Excel 公式注入清洗。"""
import html as html_lib
import re
from decimal import Decimal
from types import SimpleNamespace

from fastapi_app.api.v1.endpoints.purchase_center.export_utils import (
    create_supplier_workbook,
    generate_factory_summary_print,
    generate_normal_summary_print,
    generate_supplier_summary_print,
)

# Excel 把首字符为这四个字符的单元格当公式/DDE 载荷解析。`\t` **不在**此列：
# 它正是权威清洗器加的前缀（打断解析的防御标记），列进去会让断言与修复互相矛盾。
_FORMULA_LEADERS = ('=', '+', '-', '@')
_TD_RE = re.compile(r'<td[^>]*>(.*?)</td>', re.S)


def _cell_texts(page: str) -> list[str]:
    """取打印页里每个 `<td>` 的**可见文本**（实体已还原）。

    断言必须打在「单元格实际落到 Excel 的那串字符」上，而不是整页 HTML ——
    否则 `<td style="...">` 里的 `=` 会让「不出现危险首字符」这类断言无条件成立（假绿）。
    """
    return [html_lib.unescape(m) for m in _TD_RE.findall(page)]


def _assert_no_formula_leader(page: str) -> list[str]:
    cells = _cell_texts(page)
    bad = [t for t in cells if t[:1] in _FORMULA_LEADERS]
    assert bad == [], f'打印单元格以公式引导符开头，Excel 打开即解析: {bad}'
    return cells


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


def test_normal_summary_print_neutralizes_formula_led_in_cells():
    """F2-3：普通汇总打印 —— 打印页另存/用 Excel 打开时，单元格首字符必须已被打断。"""
    evil = "=cmd|' /C calc'!A0"
    order = SimpleNamespace(
        id=1, order_no='=CMD|NO', supplier_name='滨发', customer_name='客户A',
        order_date='2026-10-21',
    )
    item = SimpleNamespace(
        material_name=evil, specification='+1+1', quantity=Decimal('20'),
        unit='-个', material_category='@SUM(A1)',
    )

    page = generate_normal_summary_print([order], {1: [item]})
    cells = _assert_no_formula_leader(page)

    assert '\t' + evil in cells          # 正面断言：前缀确实写进了单元格，不是把值丢了
    assert '\t=CMD|NO' in page           # 非 `<td>` 插值（订单编号）同走单点，也需打断
    assert '订单编号:' in page           # 标签文本仍在 → 只加前缀，没有整列丢弃


def test_factory_summary_print_neutralizes_formula_led_in_cells():
    evil = "=cmd|fabric"
    order = SimpleNamespace(
        id=1, source_order_id=None, product_name='@PROD', product_quantity=Decimal('10'),
        customer_name='=cmd|customer', supplier_name='滨发',
    )
    item = SimpleNamespace(
        supplier_name='+SUP', material_name=evil, specification='-SPEC',
        quantity=Decimal('5'), unit='米',
    )

    page = generate_factory_summary_print([order], {1: [item]})
    cells = _assert_no_formula_leader(page)

    assert '\t' + evil in cells
    assert '\t+SUP' in cells
    assert '\t-SPEC' in cells


def test_supplier_summary_print_neutralizes_formula_led_in_cells():
    evil = "=cmd|material"
    supplier_groups = [{
        'supplier_name': '滨发',
        'orders': ['PO-1'],
        'items': [{
            'material_name': evil, 'specification': '+SPEC', 'unit': '-UNIT',
            'quantity': 1, 'material_category': '@CAT', 'order_count': 1,
        }],
    }]

    page = generate_supplier_summary_print(supplier_groups, [])
    cells = _assert_no_formula_leader(page)

    assert '\t' + evil in cells
    assert '\t+SPEC' in cells


def test_first_char_escape_leaves_clean_values_and_numbers_untouched():
    """反向门：不得「给所有值加前缀」，也不得把数值列降级成文本。

    负数量是合法退货/冲抵口径，Excel 对纯数字按数值解析，本就不是注入面；
    若给它加 `\\t` 会把 -5 变成文本，破坏合计列的可计算性。
    """
    order = SimpleNamespace(
        id=1, order_no='PO-1', supplier_name='滨发', customer_name='客户A',
        order_date='2026-10-21',
    )
    item = SimpleNamespace(
        material_name='布料A', specification='10cm', quantity=Decimal('-5'),
        unit='米', material_category='主料',
    )

    cells = _cell_texts(generate_normal_summary_print([order], {1: [item]}))

    for clean in ('布料A', '10cm', '米', '主料'):
        assert clean in cells, f'正常值被误加前缀: {cells}'
    assert '-5' in cells and '\t-5' not in cells
