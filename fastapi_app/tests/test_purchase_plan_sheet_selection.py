"""出货计划 Excel 解析必须按表名取「出货计划」，而不是 wb.active。

背景（2026-11-15 评审）：模板下载里带「填写示例」页；Excel/WPS 保存时会把
**当前查看的页签**记为 active。用户停在示例页保存时，按 active 解析会把示例行
当成首个数据行，`detected_month` 被锁成示例日期，用户当月所有行都会被判
「不允许跨月」而整批丢弃。
"""
import io

import openpyxl

from fastapi_app.services.purchase_plan_staging import (
    PLAN_TEMPLATE_HEADERS,
    _load_excel_rows,
)


def _workbook_bytes(active_index: int) -> bytes:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = '出货计划'
    ws.append(list(PLAN_TEMPLATE_HEADERS))
    ws.append(['客户A', '产品A', 10, '2026-11-20', ''])

    demo = wb.create_sheet('填写示例')
    demo.append(list(PLAN_TEMPLATE_HEADERS))
    demo.append(['示例客户', '示例产品', 1, '2026-01-15', '示例'])

    wb.active = active_index
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def test_active_sheet_is_example_but_parser_reads_plan_sheet():
    # clip_iter_rows 从第 2 行起（跳过表头），rows[0] 就是首条数据行
    rows = _load_excel_rows(_workbook_bytes(active_index=1))

    # 首条数据必须来自「出货计划」而不是示例页（示例数量是 1、日期 2026-01-15）
    assert rows[0][0] == '客户A'
    assert rows[0][2] == 10


def test_falls_back_to_active_sheet_when_named_sheet_missing():
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = 'Sheet'
    ws.append(list(PLAN_TEMPLATE_HEADERS))
    ws.append(['客户B', '产品B', 3, '2026-11-21', ''])
    buf = io.BytesIO()
    wb.save(buf)

    rows = _load_excel_rows(buf.getvalue())
    assert rows[0][0] == '客户B'
