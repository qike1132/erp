"""批量导入工厂闸门回归测试（2026-11-16 上线前审计 High：四条批量写路径缺闸门）。

背景：单条写路径有工厂隔离（``order.py`` 调 ``assert_product_factory_scoped``），
但四条批量写路径在写 Order / StockIn / InventoryLog 前**不做任何 Product.factory
比对**，同一个控件被绕过：

1. ``POST /batch/import-orders`` → ``import_orders_service`` 未接 scoped_factory；
2. 综合导入的「订单管理」Sheet → ``_call_sheet_importer`` 走裸调分支；
3. ``POST /tasks/import-orders|stockins`` → ARQ worker 侧无工厂上下文；
4. ``POST /staging/confirm`` → 确认链路写 order/inventory_log（抵扣还写 stock_out）。

修复把 ``scoped_factory``（超管/未绑定厂 = None）从端点透传到行处理器，行处理器在
产品解析出来后复用 ``batch_import_core._row_factory_rejected``（与
``shared/factory_scope.assert_product_factory_scoped`` 同口径）**按行拒绝**，
其余合法行照常导入。

本文件用假 DB + 替身依赖做**单元级**验证（不碰任何真实库），锁住：
1. ``_row_factory_rejected`` 判定真值表；
2. 同步订单 Sheet：他厂行拒绝、本厂行放行（拦「借导入给他厂建单」）；
3. 综合导入 core 路径（``import_orders_from_data``）同样拒绝；
4. ARQ 入队参数带 scoped_factory（worker 里没有 current_user，闸门算在端点）；
5. ARQ worker 侧订单/备货两个任务对他厂产品不写任何行、不动库存；
6. 暂存确认链路对他厂产品的暂存行不写 Order 且该行记错误；
7. 超管与未绑定厂用户全放行（防把正常业务堵死）；
8. 与单条接口控件（``assert_product_factory_scoped``）逐点对照，保证口径一致。
"""
from __future__ import annotations

import io
import os
import tempfile
from contextlib import asynccontextmanager, suppress
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi import HTTPException

import fastapi_app.tasks.batch_tasks as bt
from fastapi_app.api.v1.endpoints import tasks as tasks_ep
from fastapi_app.core.state_machine import StagingStatus
from fastapi_app.services import batch_import_core as bic
from fastapi_app.services import batch_import_service as bis
from fastapi_app.services import batch_service
from fastapi_app.services.batch_import_core import _row_factory_rejected
from fastapi_app.services.staging import order as staging_order_mod
from fastapi_app.shared.factory_scope import assert_product_factory_scoped, factory_scope_of
from fastapi_app.shared_models import InventoryLog, Order

_FACTORY_MSG = '产品不在你的工厂范围'


# ---------------------------------------------------------------------------
# 假会话与替身
# ---------------------------------------------------------------------------

class _FakeDb:
    """最小假会话：add/flush 记账，begin_nested 空转。"""

    def __init__(self):
        self.added = []
        self.flushed = 0
        self.info: dict = {}

    @asynccontextmanager
    async def begin_nested(self):
        yield self

    async def execute(self, stmt, *args, **kwargs):  # pragma: no cover - 导入路径不该查库
        raise AssertionError('导入路径不应触发额外 execute')

    async def flush(self):
        self.flushed += 1

    def add(self, obj):
        self.added.append(obj)


def _product(pid: int, factory: str | None):
    return SimpleNamespace(
        id=pid, name=f'产品{pid}', barcode=None, factory=factory, current_stock=100,
    )


class _ScalarResult:
    """``select(...).scalar_one_or_none()`` 的替身（单条接口控件用）。"""

    def __init__(self, value) -> None:
        self._value = value

    def scalar_one_or_none(self):
        return self._value


class _LookupDb:
    """只回答「这条产品属于哪个厂」的假会话，足够驱动 assert_product_factory_scoped。"""

    def __init__(self, factory: str | None) -> None:
        self._factory = factory

    async def execute(self, stmt, *args, **kwargs):
        return _ScalarResult(self._factory)


class _Savepoint:
    def __init__(self, session: _ArqSession) -> None:
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


class _ArqSession:
    """ARQ worker 侧的假会话：add/flush/savepoint/commit/rollback 记账。"""

    def __init__(self) -> None:
        self.added: list = []
        self.pending: list = []
        self.commits = 0
        self.rollbacks = 0
        self.closed = False
        self.info: dict = {}

    def add(self, obj) -> None:
        self.pending.append(obj)

    async def flush(self) -> None:
        self.autoflush()

    def autoflush(self) -> None:
        self.added.extend(self.pending)
        self.pending.clear()

    def begin_nested(self) -> _Savepoint:
        return _Savepoint(self)

    async def commit(self) -> None:
        self.autoflush()
        self.commits += 1

    async def rollback(self) -> None:
        self.pending.clear()
        self.rollbacks += 1

    async def close(self) -> None:
        self.closed = True


def _tmp_upload() -> str:
    """位于 ``ALLOWED_UPLOAD_DIRS`` 内的路径（解析层被打桩，文件无需真实存在）。"""
    return os.path.join(tempfile.gettempdir(), 'factory_gate_probe.xlsx')


def _job_ctx(label: str) -> dict:
    """ARQ 任务上下文，job_id 每次唯一。

    为什么不能用固定 job_id：worker 侧的重放幂等集合是**进程级**内存
    （``arq_app._IN_MEMORY_IDEMPOTENCY``，键 = job_id），固定 id 会让第二次执行
    同一用例时行被当成「本 job 已处理」直接跳过 —— 用例结果就取决于跑了几次。
    """
    return {'job_id': f'{label}-{uuid4().hex}'}


# ---------------------------------------------------------------------------
# ① 判定真值表
# ---------------------------------------------------------------------------

def test_row_factory_rejected_truth_table() -> None:
    # 未绑定厂/超管 → 全放行
    assert _row_factory_rejected(None, 'A厂') is False
    assert _row_factory_rejected(None, None) is False
    assert _row_factory_rejected('', 'A厂') is False
    # 产品未分配工厂（NULL/空串）→ 放行（与 factory_scope 读放行写拦截口径一致）
    assert _row_factory_rejected('A厂', None) is False
    assert _row_factory_rejected('A厂', '') is False
    # 本厂放行、他厂拒绝
    assert _row_factory_rejected('A厂', 'A厂') is False
    assert _row_factory_rejected('A厂', 'B厂') is True


# ---------------------------------------------------------------------------
# ② 对照控件：单条接口（assert_product_factory_scoped）—— 批量闸门必须同口径
# ---------------------------------------------------------------------------

async def test_single_order_endpoint_gate_contrast() -> None:
    """单条写路径的既有控件：厂绑定用户对他厂产品 404，超管/未绑定厂放行。

    这里把「同一产品（B厂）」在单条接口与批量行处理器上的结论并列断言 ——
    批量闸门若与单条控件口径分叉（比如放行了单条接口 404 的产品），本用例即红。
    """
    bound_user = SimpleNamespace(factory='A厂', is_super=False)
    super_user = SimpleNamespace(factory='A厂', is_super=True)
    unbound_user = SimpleNamespace(factory=None, is_super=False)

    # 单条接口：他厂产品 → 404（不暴露「存在但不属于你」）
    with pytest.raises(HTTPException) as exc:
        await assert_product_factory_scoped(_LookupDb('B厂'), 2, bound_user, what='产品')
    assert exc.value.status_code == 404
    # 同一产品在批量行处理器上同样被拒
    assert _row_factory_rejected(factory_scope_of(bound_user), 'B厂') is True

    # 超管/未绑定厂：单条接口放行，批量同样放行
    await assert_product_factory_scoped(_LookupDb('B厂'), 2, super_user, what='产品')
    await assert_product_factory_scoped(_LookupDb('B厂'), 2, unbound_user, what='产品')
    assert _row_factory_rejected(factory_scope_of(super_user), 'B厂') is False
    assert _row_factory_rejected(factory_scope_of(unbound_user), 'B厂') is False


# ---------------------------------------------------------------------------
# ③ 同步订单 Sheet（/batch/import-orders 与综合导入共用 import_orders_service）
# ---------------------------------------------------------------------------

def _patch_order_common(monkeypatch, products, rows):
    monkeypatch.setattr(bis, '_validate_xlsx_file', lambda _f: None)
    monkeypatch.setattr(bis, '_read_excel_sheets', AsyncMock(return_value=(rows, None)))
    monkeypatch.setattr(bic, 'schedule_post_commit_invalidation', lambda *a, **k: None)
    monkeypatch.setattr(
        'fastapi_app.services.purchase._auto_generate.schedule_auto_generate_purchase_orders',
        lambda *a, **k: None,
    )
    monkeypatch.setattr(batch_service, 'get_all_products', AsyncMock(return_value=products))
    monkeypatch.setattr(bis, '_pre_load_customer_names', AsyncMock(return_value={'客户A'}))
    monkeypatch.setattr(bis, 'generate_order_number', AsyncMock(return_value='SO-X'))
    monkeypatch.setattr(
        bis, 'get_product_for_update',
        AsyncMock(return_value=SimpleNamespace(id=1, current_stock=100, version=0)))


_ORDER_ROWS = [
    {'产品名称': '产品1', '订单数量': 5, '客户名称': '客户A'},
    {'产品名称': '产品2', '订单数量': 7, '客户名称': '客户A'},
]


async def test_orders_import_rejects_other_factory_row(monkeypatch) -> None:
    """厂绑定用户 + 他厂产品：该行记为错误行，订单与库存流水一行都不落。"""
    products = [_product(1, 'A厂'), _product(2, 'B厂')]
    _patch_order_common(monkeypatch, products, _ORDER_ROWS)
    db = _FakeDb()

    result = await bis.import_orders_service(
        db, SimpleNamespace(filename='x.xlsx'), scoped_factory='A厂')

    assert result.imported == 1   # 本厂行正常导入
    assert result.skipped == 1    # 他厂行按行拒绝
    assert [o.product_id for o in db.added if isinstance(o, Order)] == [1]
    assert [log.product_id for log in db.added if isinstance(log, InventoryLog)] == [1]
    assert _FACTORY_MSG in result.message


async def test_orders_import_allows_super_admin_and_unbound_factory(monkeypatch) -> None:
    """超管与未绑定厂用户行为不变：两行都导入（防把正常业务堵死）。"""
    products = [_product(1, 'A厂'), _product(2, 'B厂')]
    super_user = SimpleNamespace(factory='A厂', is_super=True)
    unbound_user = SimpleNamespace(factory=None, is_super=False)
    # 端点口径：两者的 scoped_factory 都算成 None（不限厂）
    assert (factory_scope_of(super_user) or None) is None
    assert (factory_scope_of(unbound_user) or None) is None

    for user in (super_user, unbound_user):
        _patch_order_common(monkeypatch, products, _ORDER_ROWS)
        db = _FakeDb()
        result = await bis.import_orders_service(
            db, SimpleNamespace(filename='x.xlsx'),
            scoped_factory=factory_scope_of(user) or None)
        assert result.imported == 2
        assert result.skipped == 0
        assert [o.product_id for o in db.added if isinstance(o, Order)] == [1, 2]


# ---------------------------------------------------------------------------
# ④ 综合导入 core 路径（import_orders_from_data）
# ---------------------------------------------------------------------------

async def test_comprehensive_order_sheet_rejects_other_factory_row(monkeypatch) -> None:
    """综合导入的「订单管理」Sheet 走 core 行处理器，此前是该 Sheet 的唯一裸调分支。"""
    monkeypatch.setattr(
        bic, '_pre_load_order_context',
        AsyncMock(return_value={
            'product_map': {'产品1': _product(1, 'A厂'), '产品2': _product(2, 'B厂')},
            'customer_names': {'客户A'},
        }))
    monkeypatch.setattr(bic, 'schedule_post_commit_invalidation', lambda *a, **k: None)
    monkeypatch.setattr(
        'fastapi_app.services.purchase._auto_generate.schedule_auto_generate_purchase_orders',
        lambda *a, **k: None,
    )
    db = _FakeDb()
    deps = bic.ImportDeps(generate_order_number=AsyncMock(return_value='SO-X'))

    count, messages = await bic.import_orders_from_data(
        db, _ORDER_ROWS, deps=deps, scoped_factory='A厂')

    assert count == 1
    assert [o.product_id for o in db.added if isinstance(o, Order)] == [1]
    assert '行3: 产品不在你的工厂范围，已拒绝该行（产品2）' in messages


async def test_call_sheet_importer_passes_scoped_factory_to_document_sheets(monkeypatch) -> None:
    """透传分派：订单/备货/出货三个 Sheet 都收到 scoped_factory，产品 Sheet 不接。"""
    stockin_spy = AsyncMock(return_value=(0, []))
    stockout_spy = AsyncMock(return_value=(0, []))
    order_spy = AsyncMock(return_value=(0, []))
    product_spy = AsyncMock(return_value=(0, []))
    monkeypatch.setattr(bis, 'import_stockins_from_data', stockin_spy, raising=False)
    monkeypatch.setattr(bis, 'import_stockouts_from_data', stockout_spy, raising=False)
    monkeypatch.setattr(bis, 'import_orders_from_data', order_spy, raising=False)
    monkeypatch.setattr(bis, 'import_products_from_data', product_spy, raising=False)

    db = _FakeDb()
    for importer in (stockin_spy, stockout_spy, order_spy, product_spy):
        await bis._call_sheet_importer(importer, db, [], None, None, scoped_factory='A厂')

    assert stockin_spy.await_args.kwargs.get('scoped_factory') == 'A厂'
    assert stockout_spy.await_args.kwargs.get('scoped_factory') == 'A厂'
    # 本轮修的就是它：订单 Sheet 此前走裸调分支，收不到闸门
    assert order_spy.await_args.kwargs.get('scoped_factory') == 'A厂'
    # 产品 Sheet 自带「工厂」列，不属跨厂写单据，不接闸门
    assert 'scoped_factory' not in product_spy.await_args.kwargs


# ---------------------------------------------------------------------------
# ⑤ ARQ 入队参数：闸门必须随任务参数进 worker
# ---------------------------------------------------------------------------

def _import_upload(filename: str = '订单.xlsx'):
    """满足 _validate_import_file 的最小上传对象（xlsx 魔数 + 可 seek 的文件体）。"""
    return SimpleNamespace(filename=filename, file=io.BytesIO(b'PK\x03\x04' + b'\x00' * 16))


async def test_async_import_orders_enqueues_scoped_factory(monkeypatch) -> None:
    """厂绑定用户 → 任务参数第 5 位带 'A厂'；超管/未绑定厂 → None（不限厂）。"""
    fake_pool = SimpleNamespace(enqueue_job=AsyncMock(return_value=SimpleNamespace(job_id='job-1')))
    monkeypatch.setattr('fastapi_app.core.arq_app.get_arq_pool', AsyncMock(return_value=fake_pool))

    async def _submit(user):
        resp = await tasks_ep.async_import_orders(file=_import_upload(), current_user=user)
        args = fake_pool.enqueue_job.await_args.args
        # 入队即产生的真实临时文件，本用例负责清理（worker 才不会跑）
        with suppress(OSError):
            os.unlink(args[1])
        return resp, args

    resp, args = await _submit(SimpleNamespace(id=7, factory='A厂', is_super=False))
    assert args[0] == 'batch_import_orders_task'
    assert args[2] == '订单.xlsx'
    assert args[3] == 7
    assert args[4] == 'A厂'
    assert resp['task_id'] == 'job-1'

    for user in (SimpleNamespace(id=8, factory='A厂', is_super=True),
                 SimpleNamespace(id=9, factory=None, is_super=False)):
        _, args = await _submit(user)
        assert args[4] is None


async def test_async_import_stockins_enqueues_scoped_factory(monkeypatch) -> None:
    """备货 ARQ 端点同理：该路径直写 StockIn + 库存，闸门丢在端点等于全裸。"""
    fake_pool = SimpleNamespace(enqueue_job=AsyncMock(return_value=SimpleNamespace(job_id='job-2')))
    monkeypatch.setattr('fastapi_app.core.arq_app.get_arq_pool', AsyncMock(return_value=fake_pool))

    await tasks_ep.async_import_stockins(
        file=_import_upload('备货.xlsx'),
        current_user=SimpleNamespace(id=11, factory='A厂', is_super=False),
    )
    args = fake_pool.enqueue_job.await_args.args
    with suppress(OSError):
        os.unlink(args[1])
    assert args[0] == 'batch_import_stockins_task'
    assert args[3] == 11
    assert args[4] == 'A厂'


# ---------------------------------------------------------------------------
# ⑥ ARQ worker 侧：他厂行不写单、不动库存
# ---------------------------------------------------------------------------

def _patch_arq_env(monkeypatch, session, product, rows):
    monkeypatch.setattr(bt, '_parse_rows_async', AsyncMock(return_value=(True, rows, '')))
    monkeypatch.setattr(bt, '_open_import_session', AsyncMock(return_value=session))
    monkeypatch.setattr(bt, '_resolve_product_locked', AsyncMock(return_value=product))
    monkeypatch.setattr(
        'fastapi_app.services.numbering.generate_order_number',
        AsyncMock(return_value='SO-ARQ-1'))
    monkeypatch.setattr(
        'fastapi_app.services.numbering.generate_stockin_number',
        AsyncMock(return_value='SI-ARQ-1'))
    delta = AsyncMock(return_value=None)
    monkeypatch.setattr(
        'fastapi_app.shared.stock_concurrency.apply_stock_delta_locked', delta)
    return delta


_ARQ_ROW = {'产品名称': '产品2', '客户名称': '客户A', '数量': 7}


async def test_arq_orders_task_rejects_other_factory_product(monkeypatch) -> None:
    """订单 ARQ 任务：他厂产品 → 该行记错误、无 Order/InventoryLog 落库。"""
    session = _ArqSession()
    _patch_arq_env(monkeypatch, session, _product(2, 'B厂'), [_ARQ_ROW])

    result = await bt.batch_import_orders_task(
        _job_ctx('job-orders-gate'), _tmp_upload(), 'f.xlsx', 1, 'A厂')

    assert result['imported_count'] == 0
    assert result['errors'] == [
        {'row': 2, 'error': '产品不在你的工厂范围，已拒绝该行（产品2）'}]
    assert session.added == []


async def test_arq_stockins_task_rejects_other_factory_product(monkeypatch) -> None:
    """备货 ARQ 任务：他厂产品 → 不写 StockIn、库存增量一次都不调。"""
    session = _ArqSession()
    delta = _patch_arq_env(monkeypatch, session, _product(2, 'B厂'), [_ARQ_ROW])

    result = await bt.batch_import_stockins_task(
        _job_ctx('job-stockins-gate'), _tmp_upload(), 'f.xlsx', 1, 'A厂')

    assert result['imported_count'] == 0
    assert result['errors'] == [
        {'row': 2, 'error': '产品不在你的工厂范围，已拒绝该行（产品2）'}]
    assert session.added == []
    assert delta.await_count == 0


async def test_arq_tasks_allow_unbound_factory_user(monkeypatch) -> None:
    """未绑定厂（scoped_factory=None，超管同口径）：两个任务行为不变，照常写入。"""
    session = _ArqSession()
    _patch_arq_env(monkeypatch, session, _product(2, 'B厂'), [_ARQ_ROW])

    orders_result = await bt.batch_import_orders_task(
        _job_ctx('job-orders-open'), _tmp_upload(), 'f.xlsx', 1, None)
    assert orders_result['imported_count'] == 1
    assert [type(o).__name__ for o in session.added] == ['Order', 'InventoryLog']

    session2 = _ArqSession()
    delta2 = _patch_arq_env(monkeypatch, session2, _product(2, 'B厂'), [_ARQ_ROW])
    stockins_result = await bt.batch_import_stockins_task(
        _job_ctx('job-stockins-open'), _tmp_upload(), 'f.xlsx', 1, None)
    assert stockins_result['imported_count'] == 1
    assert [type(o).__name__ for o in session2.added] == ['StockIn', 'InventoryLog']
    assert delta2.await_count == 1


# ---------------------------------------------------------------------------
# ⑦ 暂存确认链路（写 order + inventory_log，抵扣分支还写 stock_out）
# ---------------------------------------------------------------------------

class _Rows:
    def __init__(self, rows) -> None:
        self._rows = rows

    def scalars(self):
        return self

    def all(self):
        return list(self._rows)


class _SavepointCtx:
    """模拟 savepoint 回滚：行内失败时丢弃该行已 add 的对象。

    不模拟这一点就测不到「他厂行被拒后不落 Order」——真实 SQLAlchemy 里
    该行在 ``begin_nested`` 退出时随 savepoint 一起回滚。
    """

    def __init__(self, db) -> None:
        self._db = db
        self._snapshot: list = []

    async def __aenter__(self):
        self._snapshot = list(self._db.added)
        return self

    async def __aexit__(self, exc_type, exc, tb):
        if exc_type is not None:
            self._db.added = self._snapshot
        return False


class _StagingDb:
    """暂存确认的假会话：SELECT 返回预置暂存行，其余（拒行的 DELETE）返回空。"""

    def __init__(self, staging_rows) -> None:
        self._rows = staging_rows
        self.added = []
        self.flushed = 0

    def begin_nested(self):
        return _SavepointCtx(self)

    async def execute(self, stmt, *args, **kwargs):
        if str(stmt).lstrip().upper().startswith('SELECT'):
            return _Rows(self._rows)
        return _Rows([])

    async def flush(self):
        self.flushed += 1

    def add(self, obj):
        self.added.append(obj)


def _staging_row(product_id: int = 2):
    return SimpleNamespace(
        id=1, customer='客户A', product_name='产品2', product_id=product_id,
        quantity=7, note='', order_date=None, deduct_stock=False, deduct_quantity=0,
        status=StagingStatus.PENDING, is_validated=True,
    )


def _patch_staging_common(monkeypatch, product):
    monkeypatch.setattr(
        'fastapi_app.shared.stock_concurrency.get_product_for_update',
        AsyncMock(return_value=product))
    monkeypatch.setattr(
        staging_order_mod, 'generate_order_number', AsyncMock(return_value='SO-STG-1'))
    monkeypatch.setattr(
        'fastapi_app.services.outsource_service.auto_generate_for_order', AsyncMock())
    monkeypatch.setattr(
        staging_order_mod, 'schedule_post_commit_invalidation', lambda *a, **k: None)
    monkeypatch.setattr(
        staging_order_mod, 'cache_mgr',
        SimpleNamespace(invalidate_stock_and_order=AsyncMock()))


async def test_staging_confirm_rejects_other_factory_product(monkeypatch) -> None:
    """暂存确认：他厂产品的暂存行 → 不建 Order（该行进错误清单）。"""
    _patch_staging_common(monkeypatch, _product(2, 'B厂'))
    staging = _staging_row()
    db = _StagingDb([staging])

    confirmed, errors = await staging_order_mod.confirm_staging_orders(
        db, 'u1:default', scoped_factory='A厂')

    assert confirmed == 0
    assert len(errors) == 1
    assert _FACTORY_MSG in errors[0]
    assert [o for o in db.added if isinstance(o, Order)] == []
    assert staging.status == StagingStatus.REJECTED


async def test_staging_confirm_allows_unbound_factory_user(monkeypatch) -> None:
    """超管/未绑定厂（scoped_factory=None）：确认行为不变，照常建单（防堵死）。"""
    _patch_staging_common(monkeypatch, _product(2, 'B厂'))
    staging = _staging_row()
    db = _StagingDb([staging])

    confirmed, errors = await staging_order_mod.confirm_staging_orders(
        db, 'u1:default', scoped_factory=None)

    assert confirmed == 1
    assert errors == []
    assert [o.product_id for o in db.added if isinstance(o, Order)] == [2]
    assert staging.status == StagingStatus.APPROVED


# ---------------------------------------------------------------------------
# ⑧ 服务层备货/出货导入（既有闸门，防本次改动回退）
# ---------------------------------------------------------------------------

def _patch_stockin_common(monkeypatch, products, rows):
    monkeypatch.setattr(bis, '_validate_xlsx_file', lambda _f: None)
    monkeypatch.setattr(bis, '_read_excel_sheets', AsyncMock(return_value=(rows, None)))
    monkeypatch.setattr(bic, 'schedule_post_commit_invalidation', lambda *a, **k: None)
    monkeypatch.setattr(batch_service, 'get_all_products', AsyncMock(return_value=products))
    monkeypatch.setattr(bis, '_pre_load_customer_names', AsyncMock(return_value={'客户A'}))
    monkeypatch.setattr(bis, 'generate_stockin_number', AsyncMock(return_value='SI-X'))
    locked = SimpleNamespace(id=1, current_stock=100, version=0)
    monkeypatch.setattr(bis, 'get_product_for_update', AsyncMock(return_value=locked))
    delta = AsyncMock()
    monkeypatch.setattr(bis, 'apply_stock_delta_locked', delta)
    return delta


async def test_stockin_import_rejects_other_factory_row(monkeypatch) -> None:
    products = [_product(1, 'A厂'), _product(2, 'B厂')]
    rows = [
        {'产品名称': '产品1', '备货数量': 5, '客户名称': '客户A', '时间': ''},
        {'产品名称': '产品2', '备货数量': 7, '客户名称': '客户A', '时间': ''},
    ]
    delta = _patch_stockin_common(monkeypatch, products, rows)
    db = _FakeDb()

    result = await bis.import_stockins_service(db, SimpleNamespace(filename='x.xlsx'), scoped_factory='A厂')

    assert result.imported == 1   # 本厂行正常导入
    assert result.skipped == 1    # 他厂行按行拒绝
    assert delta.await_count == 1  # 库存只动本厂那一行


async def test_stockin_import_allows_same_factory_and_unbound_user(monkeypatch) -> None:
    products = [_product(1, 'A厂')]
    rows = [{'产品名称': '产品1', '备货数量': 5, '客户名称': '客户A', '时间': ''}]

    # 未绑定厂（scoped_factory=None）：放行
    delta = _patch_stockin_common(monkeypatch, products, rows)
    result = await bis.import_stockins_service(
        _FakeDb(), SimpleNamespace(filename='x.xlsx'))
    assert result.imported == 1
    assert delta.await_count == 1

    # 本厂绑定：同样放行
    delta2 = _patch_stockin_common(monkeypatch, products, rows)
    result2 = await bis.import_stockins_service(
        _FakeDb(), SimpleNamespace(filename='x.xlsx'), scoped_factory='A厂')
    assert result2.imported == 1
    assert delta2.await_count == 1


def _patch_stockout_common(monkeypatch, product, rows):
    monkeypatch.setattr(bis, '_validate_xlsx_file', lambda _f: None)
    monkeypatch.setattr(bis, '_read_excel_sheets', AsyncMock(return_value=(rows, None)))
    monkeypatch.setattr(bic, 'schedule_post_commit_invalidation', lambda *a, **k: None)
    monkeypatch.setattr(
        batch_service, 'get_product_by_identifier', AsyncMock(return_value=product))
    delta = AsyncMock()
    monkeypatch.setattr(bis, 'apply_stock_delta_locked', delta)
    return delta


async def test_stockout_import_rejects_other_factory_row(monkeypatch) -> None:
    product = _product(2, 'B厂')
    rows = [{'产品名称': '产品2', '出货数量': 3, '客户名称': '客户A', '时间': ''}]
    delta = _patch_stockout_common(monkeypatch, product, rows)
    db = _FakeDb()

    result = await bis.import_stockouts_service(db, SimpleNamespace(filename='x.xlsx'), scoped_factory='A厂')

    # 注：imported==0 时 _build_batch_result 会丢弃 skipped 计数（既有行为），
    # 故这里断言错误消息与「库存分毫未动」，不断言 skipped。
    assert result.imported == 0
    assert _FACTORY_MSG in result.message
    assert delta.await_count == 0  # 库存分毫未动
