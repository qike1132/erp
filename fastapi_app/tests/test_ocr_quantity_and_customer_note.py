"""M-24 / M-25 回归（2026-11-21 全量审计）。

M-25：OCR 文本解析的超长数字串此前 ``int(float(cleaned))``——float 溢出成 inf
后 ``int(inf)`` 抛 OverflowError → 整次导入 500；``_parse_line_by_line`` 的裸
``int(\\d+)`` 可产出 10^400 级数量通过 ``>0`` 校验、flush 时 DataError 同样 500。
修复：``_parse_quantity`` 输入截 12 位、结果封顶 9 位、小数拒绝（对齐 H-1），
两个行解析点全部走该 helper。
M-24：客户模糊匹配静默改写库名且不留痕（产品匹配会写 match_info）——修复后
客户改写同样追加进 note，原始单据名可追溯。
"""
from types import SimpleNamespace

from fastapi_app.services.ocr import _import as ocr_import
from fastapi_app.services.ocr._text_parsers import _parse_line_by_line, _parse_quantity


def test_parse_quantity_caps_huge_digits():
    """400 位数字串：修复前 int(inf) 抛 OverflowError，修复后按越界返回 0。"""
    assert _parse_quantity('9' * 400) == 0


def test_parse_quantity_rounds_decimal():
    # OCR 路径小数四舍五入（「保温杯 1.5个」是合法读数，暂存行有人工确认兜底）；
    # Excel 导入路径才用「小数一律拒绝」（H-1），两条路径语义不同。
    # Python round 是银行家舍入：10.5→10、1.5→2、2.5→2——业务可接受。
    assert _parse_quantity('1.5') == 2
    assert _parse_quantity('2.4') == 2
    assert _parse_quantity('10.5') == 10


def test_parse_quantity_rejects_garbage():
    assert _parse_quantity('abc') == 0
    assert _parse_quantity('') == 0


def test_parse_quantity_accepts_normal_values():
    assert _parse_quantity('10') == 10
    assert _parse_quantity('1,234') == 1234
    assert _parse_quantity(' 25 件 ') == 25
    assert _parse_quantity('999999999') == 999_999_999  # 封顶边界内


def test_parse_line_by_line_rejects_huge_quantity_row():
    """10^400 级数量行：修复前进 items（flush 时 DataError），修复后整行跳过。"""
    lines = [f'产品甲 {"9" * 400}']
    assert _parse_line_by_line(lines) == []


def test_parse_line_by_line_still_parses_normal_rows():
    lines = ['产品甲 10']
    items = _parse_line_by_line(lines)
    assert len(items) == 1
    assert items[0]['quantity'] == 10


def test_customer_fuzzy_rewrite_is_recorded_in_note(monkeypatch):
    """M-24：「张三」→「张三丰」的静默改写必须在 note 里留原文。"""
    db_customer = SimpleNamespace(id=7, name='张三丰')
    monkeypatch.setattr(
        ocr_import, 'fuzzy_match_customer',
        lambda customer, all_customers: (db_customer, 0.75),
    )
    row = ocr_import._build_staging_row(
        'sess-1',
        {'product_name': '产品甲', 'customer': '张三', 'quantity': 3, 'note': ''},
        [], {}, [{'id': 7, 'name': '张三丰'}],
    )
    assert row is not None
    assert row.customer == '张三丰'  # 仍改写为库名（口径不变）
    assert '客户模糊匹配' in (row.note or '')
    assert "OCR='张三'" in (row.note or '')
