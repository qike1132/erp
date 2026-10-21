"""P1-12：皮套导入行级业务幂等（重存 Excel 后重叠行不再重复入/出仓）。"""
from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

from fastapi_app.core.business_time import _BUSINESS_TZ
from fastapi_app.services import batch_import_core as bic
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
        self.flushed = 0

    @asynccontextmanager
    async def begin_nested(self):
        yield self

    async def execute(self, stmt, *args, **kwargs):
        self._execute_calls += 1
        return _Result(1 if self._execute_calls > 1 else None)

    async def flush(self):
        # 骨架收尾会 flush 一次（提交交给请求级事务，服务层不 commit）
        self.flushed += 1

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
    # Z04-R3② 合并骨架后，行循环与 post-commit 失效都在 core 骨架里：替身必须打在
    # batch_import_core 上（本用例只验幂等去重，不碰 Redis）。打在 bis 上会变成
    # 无人读取的死替身 → 真实失效回调被 create_task 抛出去。
    monkeypatch.setattr(bic, 'schedule_post_commit_invalidation', lambda *a, **k: None)
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
    assert db.flushed == 1  # 骨架收尾统一 flush 一次（提交仍交给请求级事务）


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
    assert db.flushed == 1


# ==================== 时间留空时幂等键必须可命中 ====================


class _RecordingDb(_FakeDb):
    """在 _FakeDb 基础上记下每次查重用到的日期绑定值。

    真实库里键能不能命中，取决于两次查询传的是不是**同一个时刻**；mock 的
    返回值不看参数，所以断言必须落在参数上，否则换成 ``datetime.now(UTC)``
    也照样「通过」。
    """

    def __init__(self):
        super().__init__()
        self.dates: list[datetime | None] = []

    async def execute(self, stmt, *args, **kwargs):
        params = stmt.compile().params
        self.dates.append(next((v for v in params.values() if isinstance(v, datetime)), None))
        return await super().execute(stmt, *args, **kwargs)


def _blank_time_rows(qty_key: str) -> list[dict]:
    return [
        {'产品名称': '皮套A', qty_key: 5, '客户名称': '客户A', '时间': None, '备注': ''},
        {'产品名称': '皮套A', qty_key: 5, '客户名称': '客户A', '时间': None, '备注': ''},
    ]


def test_blank_time_fallback_is_business_day_midnight() -> None:
    """回退值必须稳定（微秒恒 0）且落在业务日零点，否则等值查重永不命中。"""
    first = bis._blank_time_fallback()
    second = bis._blank_time_fallback()

    assert first == second, f'两次回退值不同，幂等键每次都不一样: {first!r} vs {second!r}'
    assert first.microsecond == 0 and (first.hour, first.minute, first.second) == (0, 0, 0)
    assert first.utcoffset() == timedelta(hours=8), f'不是业务时区零点: {first!r}'
    assert first.date() == datetime.now(_BUSINESS_TZ).date()


async def test_case_stockin_blank_time_rows_share_one_key(monkeypatch) -> None:
    case = _patch_common(monkeypatch, _blank_time_rows('入库数量'))
    monkeypatch.setattr(bis, 'generate_case_stockin_number', AsyncMock(side_effect=['CSI-1']))
    db = _RecordingDb()

    result = await bis.import_case_stockins_service(db, SimpleNamespace(filename='x.xlsx'))

    assert db.dates == [db.dates[0], db.dates[0]], f'两行查重日期不一致: {db.dates!r}'
    assert result.imported == 1 and result.skipped == 1, result.message
    assert len(db.added) == 1
    assert case.current_stock == 105


async def test_case_stockout_blank_time_rows_share_one_key(monkeypatch) -> None:
    case = _patch_common(monkeypatch, _blank_time_rows('出库数量'))
    monkeypatch.setattr(bis, 'generate_case_stockout_number', AsyncMock(side_effect=['CSO-1']))
    db = _RecordingDb()

    result = await bis.import_case_stockouts_service(db, SimpleNamespace(filename='x.xlsx'))

    assert db.dates == [db.dates[0], db.dates[0]], f'两行查重日期不一致: {db.dates!r}'
    assert result.imported == 1 and result.skipped == 1, result.message
    assert len(db.added) == 1
    assert case.current_stock == 95
