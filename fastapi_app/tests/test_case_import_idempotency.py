"""P1-12：皮套导入行级业务幂等（重存 Excel 后重叠行不再重复入/出仓）。"""
from __future__ import annotations

from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

from fastapi_app.services import batch_import_service as bis
from fastapi_app.services import batch_service


class _Result:
    def __init__(self, value):
        self._value = value

    def scalar_one_or_none(self):
        return self._value


class _FakeDb:
    """第一次查重返回不存在，第二次返回已存在（模拟第一行已插入）。"""

    def __init__(self):
        self._execute_calls = 0
        self.added = []

    @asynccontextmanager
    async def begin_nested(self):
        yield self

    async def execute(self, stmt, *args, **kwargs):
        self._execute_calls += 1
        return _Result(1 if self._execute_calls > 1 else None)

    def add(self, obj):
        self.added.append(obj)


def _rows(qty_key: str) -> list[dict]:
    return [
        {'产品名称': '皮套A', qty_key: 5, '客户名称': '客户A', '时间': '2026-10-20 10:00:00', '备注': ''},
        {'产品名称': '皮套A', qty_key: 5, '客户名称': '客户A', '时间': '2026-10-20 10:00:00', '备注': ''},
    ]


def _patch_common(monkeypatch, rows):
    monkeypatch.setattr(bis, '_validate_xlsx_file', lambda _f: None)
    monkeypatch.setattr(bis, '_read_excel_sheets', AsyncMock(return_value=(rows, None)))
    monkeypatch.setattr(bis, 'schedule_post_commit_invalidation', lambda *a, **k: None)
    case = SimpleNamespace(id=1, current_stock=100, version=0)
    monkeypatch.setattr(batch_service, 'find_case_locked', AsyncMock(return_value=(case, None)))
    return case


async def test_case_stockin_duplicate_row_is_skipped(monkeypatch) -> None:
    case = _patch_common(monkeypatch, _rows('入库数量'))
    monkeypatch.setattr(bis, 'generate_case_stockin_number', AsyncMock(side_effect=['CSI-1']))
    db = _FakeDb()

    result = await bis.import_case_stockins_service(db, SimpleNamespace(filename='x.xlsx'))

    assert result.imported == 1
    assert result.skipped == 1
    assert '重复行' in result.message
    assert len(db.added) == 1
    assert case.current_stock == 105  # 只加一次


async def test_case_stockout_duplicate_row_is_skipped(monkeypatch) -> None:
    case = _patch_common(monkeypatch, _rows('出库数量'))
    monkeypatch.setattr(bis, 'generate_case_stockout_number', AsyncMock(side_effect=['CSO-1']))
    db = _FakeDb()

    result = await bis.import_case_stockouts_service(db, SimpleNamespace(filename='x.xlsx'))

    assert result.imported == 1
    assert result.skipped == 1
    assert '重复行' in result.message
    assert len(db.added) == 1
    assert case.current_stock == 95  # 只扣一次
