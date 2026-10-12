"""表格解析 helper 单元测试（2026-10-11 复核 P2-14⑥）。

_parse_ocr_table_format 原 117 行拆为四个单元。既有覆盖走 parse_order_document
端到端；这里对纯函数直接下断言（期望值手工推导），变异可红——改坏列序/噪声过滤
对应测试必 fail。
"""

from fastapi_app.services.ocr._text_parsers import (
    _filter_data_lines,
    _rows_from_aligned_columns,
)


def test_filter_data_lines_drops_noise():
    """空白/分隔线/合计/页码行被剔除，业务行保留。"""
    raw = [
        '儿童保温杯500ml',
        '',                      # 空行
        '----------',            # 分隔线
        '===',                   # 分隔线
        '合计 3 项',              # 合计
        '第 1 页',                # 页码
        '共 2 页',                # 页码
        '50',
    ]
    assert _filter_data_lines(raw) == ['儿童保温杯500ml', '50']


def test_rows_aligned_columns_basic():
    """两列（product_name/quantity）按固定间隔重组；期望值手工推导。"""
    col_order = ['product_name', 'quantity']
    rows = ['儿童保温杯500ml', '50', '卡通雨伞8骨', '30']
    items = _rows_from_aligned_columns(rows, col_order, default_customer='华东商贸')
    assert items == [
        {'customer': '华东商贸', 'product_name': '儿童保温杯500ml', 'quantity': 50, 'note': ''},
        {'customer': '华东商贸', 'product_name': '卡通雨伞8骨', 'quantity': 30, 'note': ''},
    ]


def test_rows_aligned_columns_skips_bad_rows():
    """数量解析为 0 / 产品名为纯数字的行被丢弃。

    已知怪癖（既有行为，非本次引入）：`_parse_quantity` 会剥掉非数字字符，
    '-5' 变 5、'1,000' 变 1000——负数被当正数收下。OCR 场景可接受，
    不在本测试锁定范围。
    """
    col_order = ['product_name', 'quantity']
    rows = ['产品A', 'abc',    # quantity 解析为 0 → 丢
            '12345', '50',     # 产品名纯数字 → 丢
            '产品B', 'x']      # quantity 解析为 0 → 丢
    assert _rows_from_aligned_columns(rows, col_order, default_customer='') == []


def test_rows_aligned_columns_customer_column_wins():
    """三列含 customer 时逐行取列值，不再用表头客户。"""
    col_order = ['product_name', 'quantity', 'customer']
    rows = ['产品A', '50', '甲客户', '产品B', '30', '乙客户']
    items = _rows_from_aligned_columns(rows, col_order, default_customer='默认')
    assert [i['customer'] for i in items] == ['甲客户', '乙客户']
