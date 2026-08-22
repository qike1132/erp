"""综合导入 Sheet 级 savepoint 原子性契约测试（mock，无数据库依赖）

验证 2026-08-22 事务收敛改造：
- 单个 Sheet 失败仅回滚该 Sheet（savepoint 上下文），不再触发全事务 rollback
- 计数只在 savepoint 成功退出后累加（上报数与落库一致）
- 未知 Sheet 类型记入 errors 而非抛异常
"""
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.exc import SQLAlchemyError

from fastapi_app.services.batch_import_service import _process_comprehensive_sheet


class _FakeResults:
    def __init__(self):
        self.imported = {'products': 0, 'orders': 0, 'stockins': 0, 'stockouts': 0}
        self.errors = []


def _make_db():
    db = AsyncMock()
    savepoint = AsyncMock()
    savepoint.__aenter__ = AsyncMock(return_value=savepoint)
    savepoint.__aexit__ = AsyncMock(return_value=False)
    db.begin_nested = MagicMock(return_value=savepoint)
    return db, savepoint


async def test_sheet_failure_rolls_back_only_that_sheet(monkeypatch):
    db, _ = _make_db()

    async def ok_importer(db_, data_list):
        return 7, []

    async def fail_importer(db_, data_list):
        raise SQLAlchemyError('sheet boom')

    monkeypatch.setattr(
        batch_import_module(), '_SHEET_IMPORTERS',
        {'order': (ok_importer, 'orders'), 'stockout': (fail_importer, 'stockouts')},
    )
    results = _FakeResults()

    await _process_comprehensive_sheet(db, 'order', '订单管理', [{'x': 1}], results)
    await _process_comprehensive_sheet(db, 'stockout', '出货管理', [{'x': 1}], results)

    assert results.imported['orders'] == 7
    assert results.imported['stockouts'] == 0, '失败 Sheet 不应累加计数'
    assert len(results.errors) == 1
    assert '出货管理' in results.errors[0]
    # 关键契约：失败处理不再调用全事务 rollback（旧实现会误伤其他 Sheet）
    db.rollback.assert_not_awaited()
    # 两个 Sheet 都各自进入 savepoint
    assert db.begin_nested.call_count == 2


async def test_products_sheet_single_value_counter(monkeypatch):
    db, _ = _make_db()

    async def product_importer(db_, data_list):
        return 3

    monkeypatch.setattr(batch_import_module(), '_SHEET_IMPORTERS', {'product': (product_importer, 'products')})
    results = _FakeResults()

    await _process_comprehensive_sheet(db, 'product', '产品管理', [], results)
    assert results.imported['products'] == 3
    assert results.errors == []


async def test_unknown_sheet_type_records_error(monkeypatch):
    db, _ = _make_db()
    monkeypatch.setattr(batch_import_module(), '_SHEET_IMPORTERS', {})
    results = _FakeResults()

    await _process_comprehensive_sheet(db, 'nonexistent', '神秘Sheet', [], results)
    assert results.imported == {'products': 0, 'orders': 0, 'stockins': 0, 'stockouts': 0}
    assert len(results.errors) == 1
    assert '神秘Sheet' in results.errors[0]


def batch_import_module():
    from fastapi_app.services import batch_import_service as mod
    return mod
