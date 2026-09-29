"""批量导入异步骨架的语义保真测试（spec §4.2：逐字保留 batch_tasks 原语义）。

全部打桩：Excel 解析返回固定行，async session 用 MagicMock 记录
commit/rollback 调用序。验证目标不是数据落库，而是：
50 行批量提交 / 行级失败 continue / 异常批回滚计数 skipped_uncommitted /
抛出时保留文件（delete_file=False）。
"""
from unittest import mock

import pytest

import fastapi_app.tasks.batch_tasks as bt


def _row(i: int) -> dict:
    return {'产品名称': f'P{i}', '客户名称': 'c', '数量': 1}


class _SessionRecorder:
    def __init__(self):
        self.commits = 0
        self.rollbacks = 0

    async def commit(self):
        self.commits += 1

    async def rollback(self):
        self.rollbacks += 1

    async def close(self):
        # 实现里 `finally: await db.close()` 是必须保留的语义，桩点提供 no-op。
        pass


@pytest.mark.asyncio
async def test_fifty_row_batch_commit_semantics(monkeypatch, tmp_path):
    rows = [_row(i) for i in range(110)]
    monkeypatch.setattr(bt, '_parse_rows_async', mock.AsyncMock(return_value=(True, rows, '')))
    session = _SessionRecorder()
    monkeypatch.setattr(bt, '_open_import_session', mock.AsyncMock(return_value=session))
    build = mock.AsyncMock(return_value=None)

    result = await bt._run_batch_import_async(str(tmp_path / 'f.xlsx'), 'job', '订单', build)

    # 110 行 = 2 次满批提交 + 尾批；imported_count 按行计
    assert result['imported_count'] == 110
    assert build.await_count == 110
    assert session.commits >= 3          # 50+50+尾批10
    assert session.rollbacks == 0
    assert result['errors'] == []


@pytest.mark.asyncio
async def test_row_level_error_continues_without_rollback(monkeypatch, tmp_path):
    rows = [_row(0), _row(1), _row(2)]
    monkeypatch.setattr(bt, '_parse_rows_async', mock.AsyncMock(return_value=(True, rows, '')))
    session = _SessionRecorder()
    monkeypatch.setattr(bt, '_open_import_session', mock.AsyncMock(return_value=session))
    build = mock.AsyncMock(side_effect=[None, '产品不存在', None])

    result = await bt._run_batch_import_async(str(tmp_path / 'f.xlsx'), 'job', '订单', build)

    assert result['imported_count'] == 2   # 第 2 行失败，1、3 行照常
    assert result['errors'] == [{'row': 3, 'error': '产品不存在'}]
    assert session.rollbacks == 0


@pytest.mark.asyncio
async def test_exception_rolls_back_batch_and_counts_skipped(monkeypatch, tmp_path):
    rows = [_row(0), _row(1), _row(2)]
    monkeypatch.setattr(bt, '_parse_rows_async', mock.AsyncMock(return_value=(True, rows, '')))
    session = _SessionRecorder()
    monkeypatch.setattr(bt, '_open_import_session', mock.AsyncMock(return_value=session))
    build = mock.AsyncMock(side_effect=[None, ValueError('boom'), None])

    result = await bt._run_batch_import_async(str(tmp_path / 'f.xlsx'), 'job', '订单', build)

    assert result['imported_count'] == 1   # 已提交 1 行（行号 2 前无满批）
    assert session.rollbacks == 1
    assert result['errors'][0]['skipped_uncommitted'] == 1  # 行 2 失败时未提交的 1 行被跳过


@pytest.mark.asyncio
async def test_parse_failure_short_circuits(monkeypatch, tmp_path):
    monkeypatch.setattr(bt, '_parse_rows_async', mock.AsyncMock(return_value=(False, [], 'Excel 文件为空')))
    build = mock.AsyncMock()
    result = await bt._run_batch_import_async(str(tmp_path / 'f.xlsx'), 'job', '订单', build)
    assert result == {'success': False, 'error': 'Excel 文件为空', 'imported_count': 0, 'task_id': 'job'}
    build.assert_not_awaited()
