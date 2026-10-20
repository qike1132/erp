"""Z06-R6：ARQ 异步导入接行级业务键幂等（第 2 层 ``inventory_log.idem_key``）。

审计 Z06-R6 原文：「ARQ 任务入口（worker 侧 ``services/batch_import*`` 任务函数）
增加『解析后行级业务键幂等』（复用皮套导入 P1 修法的 idem_key 机制），而非文件哈希」。

修前事实：``/tasks/import-orders`` 与 ``/tasks/import-stockins`` 的 worker 任务写
``InventoryLog`` 时**完全不填 idem_key** → DB 层的部分唯一索引
``uq_inventory_log_idem`` 对这两条路径形同虚设，同一文件再上传一次即重复建单/重复入库。

本文件锁四件事：

1. ARQ 订单/备货导入写的 ``InventoryLog`` **带 idem_key**（键口径复用
   ``batch_import_core._import_idem_key``，与同步导入路径同一真相源）；
2. 幂等键冲突被兜成**行级跳过**（该行不落库、批次继续），而不是整批 500；
3. 非幂等键的 ``IntegrityError`` 仍按原样上抛（不被新 except 误吞）；
4. 备货导入的入库日期取 Excel 的「时间/备货时间」列（与同步导入路径同口径），
   缺列才回落到导入当日 —— 否则两条路径会落出两个不同的业务日，幂等键跟着分叉。
"""
import os
import tempfile
import types
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.exc import IntegrityError

import fastapi_app.tasks.batch_tasks as bt

_IDEM_CONSTRAINT = 'uq_inventory_log_idem'


def _idem_conflict() -> IntegrityError:
    """构造一个「幂等键冲突」的 IntegrityError（驱动原文形态）。"""
    return IntegrityError(
        'INSERT INTO inventory_log ...',
        params=None,
        orig=Exception(f'duplicate key value violates unique constraint "{_IDEM_CONSTRAINT}"'),
    )


class _FakeSavepoint:
    """savepoint 上下文：正常退出时做一次「autoflush」（真实 SQLAlchemy 行为）。

    真实 SQLAlchemy 在嵌套事务提交前会 ``session.flush()`` —— ``InventoryLog``
    的 INSERT 恰在此时发出，幂等键冲突也恰在此时爆发。不模拟这一点就测不到
    「冲突发生在 savepoint 退出时」这条真实路径。
    """

    def __init__(self, session: '_FakeSession') -> None:
        self._session = session

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        if exc_type is None:
            self._session.autoflush()
        else:
            # 回滚到 savepoint：本行未提交的写入作废
            self._session.pending.clear()
        return False


class _FakeSession:
    """最小 AsyncSession 替身：add/flush/savepoint/commit/rollback + 幂等键唯一约束。"""

    def __init__(self) -> None:
        self.committed_idem_keys: set[str] = set()
        self.pending: list = []
        self.commits = 0
        self.rollbacks = 0
        self.savepoints = 0
        self.closed = False

    # --- session API -------------------------------------------------------
    def add(self, obj) -> None:
        self.pending.append(obj)

    async def flush(self) -> None:
        self.autoflush()

    def begin_nested(self) -> _FakeSavepoint:
        self.savepoints += 1
        return _FakeSavepoint(self)

    async def commit(self) -> None:
        self.commits += 1

    async def rollback(self) -> None:
        self.rollbacks += 1

    async def close(self) -> None:
        self.closed = True

    # --- 模拟 DB 行为 ------------------------------------------------------
    def autoflush(self) -> None:
        for obj in list(self.pending):
            key = getattr(obj, 'idem_key', None)
            if key is not None and key in self.committed_idem_keys:
                self.pending.remove(obj)
                raise _idem_conflict()
        for obj in self.pending:
            key = getattr(obj, 'idem_key', None)
            if key is not None:
                self.committed_idem_keys.add(key)
        self.pending.clear()


def _product(product_id: int = 42):
    return types.SimpleNamespace(id=product_id, name='P', barcode='BC42')


def _tmp_upload() -> str:
    """位于 ``ALLOWED_UPLOAD_DIRS`` 内的路径（解析层被替换，文件无需真实存在）。"""
    return os.path.join(tempfile.gettempdir(), 'z06r6_arq_import_probe.xlsx')


def _patch_env(monkeypatch, rows: list, session: _FakeSession) -> None:
    """替换解析 / 会话工厂 / 产品解析 / 取号 / 库存增量，隔离 DB 与 Redis。"""
    monkeypatch.setattr(bt, '_parse_rows_async', AsyncMock(return_value=(True, rows, '')))
    monkeypatch.setattr(bt, '_open_import_session', AsyncMock(return_value=session))
    monkeypatch.setattr(bt, '_resolve_product_locked', AsyncMock(return_value=_product()))
    monkeypatch.setattr(
        'fastapi_app.services.numbering.generate_order_number',
        AsyncMock(return_value='SO-ARQ-0001'),
    )
    monkeypatch.setattr(
        'fastapi_app.services.numbering.generate_stockin_number',
        AsyncMock(return_value='SI-ARQ-0001'),
    )
    monkeypatch.setattr(
        'fastapi_app.shared.stock_concurrency.apply_stock_delta_locked',
        AsyncMock(return_value=None),
    )


# ---------------------------------------------------------------------------
# 1. ARQ 导入写的 InventoryLog 必须带 idem_key
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_orders_import_sets_idem_key_on_inventory_log(monkeypatch):
    session = _FakeSession()
    _patch_env(monkeypatch, [{'产品名称': 'P', '客户名称': '客户A', '数量': 7}], session)

    result = await bt.batch_import_orders_task(
        {'job_id': 'job-orders-1'}, _tmp_upload(), 'f.xlsx', 1,
    )

    assert result['imported_count'] == 1
    assert result['errors'] == []
    assert session.committed_idem_keys, '导入未写入任何幂等键 —— 第 2 层幂等形同虚设'
    key = next(iter(session.committed_idem_keys))
    assert key.startswith('order:客户A|42|7|')


@pytest.mark.asyncio
async def test_stockins_import_sets_idem_key_on_inventory_log(monkeypatch):
    session = _FakeSession()
    _patch_env(monkeypatch, [{'产品名称': 'P', '客户名称': '客户A', '数量': 7}], session)

    result = await bt.batch_import_stockins_task(
        {'job_id': 'job-stockins-1'}, _tmp_upload(), 'f.xlsx', 1,
    )

    assert result['imported_count'] == 1
    assert result['errors'] == []
    key = next(iter(session.committed_idem_keys))
    assert key.startswith('stockin:客户A|42|7|')


@pytest.mark.asyncio
async def test_stockins_import_uses_excel_date_column_as_business_day(monkeypatch):
    """备货日期取 Excel 的「时间」列 —— 与同步导入路径同口径，幂等键才稳定。"""
    session = _FakeSession()
    _patch_env(
        monkeypatch,
        [{'产品名称': 'P', '客户名称': '客户A', '数量': 7, '时间': '2026-03-05'}],
        session,
    )

    await bt.batch_import_stockins_task(
        {'job_id': 'job-stockins-2'}, _tmp_upload(), 'f.xlsx', 1,
    )

    key = next(iter(session.committed_idem_keys))
    assert key.endswith('|2026-03-05')


# ---------------------------------------------------------------------------
# 2. 同一文件再上传一次 → 行级跳过，不重复建单
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_reuploading_same_file_skips_duplicated_rows(monkeypatch):
    session = _FakeSession()
    rows = [{'产品名称': 'P', '客户名称': '客户A', '数量': 7}]
    _patch_env(monkeypatch, rows, session)

    first = await bt.batch_import_orders_task(
        {'job_id': 'job-orders-first'}, _tmp_upload(), 'f.xlsx', 1,
    )
    assert first['imported_count'] == 1
    assert first['errors'] == []

    # 第二次上传同一文件（新的 ARQ job —— 文件指纹守卫刻意不覆盖本路径）
    second = await bt.batch_import_orders_task(
        {'job_id': 'job-orders-second'}, _tmp_upload(), 'f.xlsx', 1,
    )

    assert second['imported_count'] == 0, '重复文件必须一行都不再导入'
    assert len(second['errors']) == 1
    assert '重复' in second['errors'][0]['error']
    assert session.rollbacks == 0, '行级跳过不得回滚整个批次'


@pytest.mark.asyncio
async def test_duplicate_row_does_not_block_other_rows(monkeypatch):
    """一条重复 + 一条新行：重复的跳过，新的照常导入。"""
    session = _FakeSession()
    _patch_env(
        monkeypatch,
        [
            {'产品名称': 'P', '客户名称': '客户A', '数量': 7},
            {'产品名称': 'P', '客户名称': '客户A', '数量': 7},
        ],
        session,
    )

    result = await bt.batch_import_orders_task(
        {'job_id': 'job-orders-dup'}, _tmp_upload(), 'f.xlsx', 1,
    )

    assert result['imported_count'] == 1
    assert len(result['errors']) == 1
    assert result['errors'][0]['row'] == 3


# ---------------------------------------------------------------------------
# 3. 非幂等键的 IntegrityError 仍上抛（不被新 except 误吞）
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_non_idempotency_integrity_error_still_propagates(monkeypatch):
    session = _FakeSession()
    _patch_env(monkeypatch, [{'产品名称': 'P', '客户名称': '客户A', '数量': 7}], session)

    other = IntegrityError(
        'INSERT INTO inventory_log ...',
        params=None,
        orig=Exception('duplicate key value violates unique constraint "inventory_log_pkey"'),
    )

    async def _build(_db, _row, _i):
        raise other

    with pytest.raises(IntegrityError):
        await bt._import_rows(
            session, [{'产品名称': 'P'}], _build, '订单', job_id='job-x', batch_size=50,
            idempotency=None,
        )


# ---------------------------------------------------------------------------
# 4. 结构守卫：行循环必须套 savepoint（冲突若在事务外爆发会 abort 整批）
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_each_row_runs_inside_its_own_savepoint(monkeypatch):
    session = _FakeSession()
    _patch_env(monkeypatch, [{'产品名称': 'P', '客户名称': '客户A', '数量': 1}] * 3, session)

    await bt.batch_import_orders_task(
        {'job_id': 'job-savepoint'}, _tmp_upload(), 'f.xlsx', 1,
    )

    assert session.savepoints == 3, '每行一个 savepoint，缺一即整批 abort 风险'
