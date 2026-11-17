"""暂存「备货 / 出货」确认链路的工厂闸门（2026-11-17 上线前审计 P0-1）。

## 拦哪种出错

暂存行由 Excel 导入产生，产品是按**名字全表映射**解析的（`_build_product_map` 无
factory 过滤）。确认时 `apply_stock_delta_locked` 直接加减 `product.current_stock`
并写 `stock_in` / `stock_out` / `inventory_log` —— 全程没有「这个产品是不是本厂的」
校验。同族的 `staging/order.py` 在 2026-11-16（H1）已加 `scoped_factory` 闸门，
**备货与出货两条漏着**：厂绑定用户可给他厂产品建库存、改库存数，单据看起来完全合法。

## 本文件各锁一件事

1. `test_*_rejects_other_factory_row`：他厂行必须**逐行拒绝**（confirmed=0、
   errors 有内容、**一次库存写入都没有**），且该行被置 REJECTED —— 与导入路径的
   逐行拒绝同语义，不整批 404。
2. `test_*_allows_unassigned_factory_row`：产品 factory 为 NULL/空串的历史行必须
   放行（与 `shared/factory_scope` 的放行面一致，否则厂绑定用户连未分厂的历史行
   都确认不了）。
3. `test_*_endpoint_forwards_factory_scope`：端点必须把 `factory_scope_of(user)`
   传进服务层 —— 否则服务层闸门永远拿到 None（= 全放行），等于没修。

## 变异检查

- 把服务函数里的 `scoped_factory` 关键字参数删掉 → 用例 1/2 抛 TypeError 变红；
- 把闸门调用那行注释掉 → 用例 1 变红（他厂行被接受、库存被写）；
- 把端点响应里的 `scoped_factory=factory_scope_of(current_user)` 删掉 → 用例 3 变红。
"""
from types import SimpleNamespace

from fastapi_app.api.v1.endpoints import staging_stockin as ep_stockin
from fastapi_app.api.v1.endpoints import staging_stockout as ep_stockout
from fastapi_app.core.state_machine import StagingStatus
from fastapi_app.services.staging import stockin as stockin_mod
from fastapi_app.services.staging import stockout as stockout_mod
from fastapi_app.shared_models import StagingStockIn, StagingStockOut


class _Scalars:
    def __init__(self, rows: list) -> None:
        self._rows = rows
    def all(self) -> list:
        return list(self._rows)


class _Result:
    def __init__(self, rows: list) -> None:
        self._rows = rows

    def scalars(self) -> _Scalars:
        return _Scalars(self._rows)


class _Cursor:
    rowcount = 0


class _Savepoint:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *_exc):
        return False


class _FakeDB:
    """只实现 confirm_* 用到的四件事（不连库）：execute / begin_nested / add / flush。"""

    def __init__(self, rows: list) -> None:
        self._rows = rows
        self._select_done = False
        self.added: list = []

    async def execute(self, _stmt):
        if not self._select_done:
            self._select_done = True
            return _Result(self._rows)
        return _Cursor()

    def begin_nested(self) -> _Savepoint:
        return _Savepoint()

    def add(self, obj) -> None:
        self.added.append(obj)

    async def flush(self) -> None:
        return None


def _product(factory: str | None):
    return SimpleNamespace(id=1, name='P-1', factory=factory, current_stock=0, version=1)


def _stockin_row(**over: object) -> StagingStockIn:
    row = StagingStockIn(
        session_id='u7:default', customer='C1', product_name='P-1',
        product_id=1, quantity=5, note='',
    )
    row.is_validated = True
    row.status = StagingStatus.PENDING
    for k, v in over.items():
        setattr(row, k, v)
    return row


def _stockout_row(**over: object) -> StagingStockOut:
    row = StagingStockOut(
        session_id='u7:default', customer='C1', product_name='P-1',
        product_id=1, quantity=5, note='',
    )
    row.is_validated = True
    row.stock_check_passed = True
    row.status = StagingStatus.PENDING
    for k, v in over.items():
        setattr(row, k, v)
    return row


async def _noop_async(*_a, **_kw):
    return None


# ---------------------------------------------------------------- 备货（stock_in）
async def test_stockin_rejects_other_factory_row(monkeypatch):
    """他厂产品的暂存备货行：逐行拒绝，且**一次库存写入都没有**。"""
    writes: list = []
    monkeypatch.setattr(
        'fastapi_app.shared.stock_concurrency.get_product_for_update',
        lambda *_a, **_kw: _async_value(_product('B厂')),
    )
    monkeypatch.setattr(
        'fastapi_app.shared.stock_concurrency.apply_stock_delta_locked',
        lambda *_a, **_kw: _record_and_return(writes),
    )
    monkeypatch.setattr(stockin_mod, 'generate_stockin_number', lambda *_a, **_kw: _async_value('SI-T-1'))

    row = _stockin_row()
    confirmed, errors = await stockin_mod.confirm_staging_stockins(
        _FakeDB([row]), 'u7:default', scoped_factory='A厂',
    )

    assert confirmed == 0, '他厂行被确认了（库存会被改）'
    assert errors and '工厂' in errors[0], errors
    assert writes == [], f'被拒绝的行仍然写了库存：{writes}'
    assert row.status == 'rejected', row.status


async def test_stockin_allows_unassigned_factory_row(monkeypatch):
    """产品未分配工厂（NULL/空串）→ 放行（与 shared/factory_scope 放行面一致）。"""
    writes: list = []
    monkeypatch.setattr(
        'fastapi_app.shared.stock_concurrency.get_product_for_update',
        lambda *_a, **_kw: _async_value(_product(None)),
    )
    monkeypatch.setattr(
        'fastapi_app.shared.stock_concurrency.apply_stock_delta_locked',
        lambda *_a, **_kw: _record_and_return(writes),
    )
    monkeypatch.setattr(stockin_mod, 'generate_stockin_number', lambda *_a, **_kw: _async_value('SI-T-2'))
    monkeypatch.setattr(stockin_mod.cache_mgr, 'invalidate_stock_and_order', _noop_async)
    monkeypatch.setattr(stockin_mod, 'schedule_post_commit_invalidation', lambda *_a, **_kw: None)
    monkeypatch.setattr(
        'fastapi_app.services.purchase._auto_generate.schedule_auto_generate_purchase_orders',
        lambda *_a, **_kw: None,
    )

    row = _stockin_row()
    confirmed, errors = await stockin_mod.confirm_staging_stockins(
        _FakeDB([row]), 'u7:default', scoped_factory='A厂',
    )

    assert confirmed == 1, f'未分厂的历史行被拒了：{errors}'
    assert writes, '放行路径应写一次库存'


# ---------------------------------------------------------------- 出货（stock_out）
async def test_stockout_rejects_other_factory_row(monkeypatch):
    """他厂产品的暂存出货行：在碰任何库存校验/扣减之前就被拒。"""
    monkeypatch.setattr(
        'fastapi_app.shared.stock_concurrency.get_product_for_update',
        lambda *_a, **_kw: _async_value(_product('B厂')),
    )
    row = _stockout_row()
    confirmed, errors = await stockout_mod.confirm_staging_stockouts(
        _FakeDB([row]), 'u7:default', scoped_factory='A厂',
    )

    assert confirmed == 0, '他厂出货行被确认了（会扣别厂库存）'
    assert errors and '工厂' in errors[0], errors
    assert row.status == 'rejected', row.status


# ---------------------------------------------------------------- 端点接线
class _TxCM:
    async def __aenter__(self):
        return None

    async def __aexit__(self, *_exc):
        return False


async def test_stockin_endpoint_forwards_factory_scope(monkeypatch):
    """端点必须把 factory_scope_of(user) 传进服务层（否则闸门永远是 None = 全放行）。"""
    seen: dict = {}

    async def _recorder(db, session_id, **kwargs):
        seen['session_id'] = session_id
        seen['kwargs'] = kwargs
        return 0, ['x']

    monkeypatch.setattr(ep_stockin, 'db_transaction', lambda _db: _TxCM())
    monkeypatch.setattr(ep_stockin.svc, 'confirm_staging_stockins', _recorder)

    await ep_stockin.confirm_staging_stockins(
        session_id='default', db=object(),
        current_user=SimpleNamespace(id=7, factory='A厂', is_super=False),
    )

    assert seen['kwargs'].get('scoped_factory') == 'A厂', seen


async def test_stockout_endpoint_forwards_factory_scope(monkeypatch):
    """出货端点同上（它在 confirmed>0 时才发事件，这里返回 0 避开通知链路）。"""
    seen: dict = {}

    async def _recorder(db, session_id, **kwargs):
        seen['session_id'] = session_id
        seen['kwargs'] = kwargs
        return 0, ['x']

    monkeypatch.setattr(ep_stockout, 'db_transaction', lambda _db: _TxCM())
    monkeypatch.setattr(ep_stockout.svc, 'confirm_staging_stockouts', _recorder)

    await ep_stockout.confirm_staging_stockouts(
        session_id='default', db=object(),
        current_user=SimpleNamespace(id=7, factory='A厂', is_super=False),
    )

    assert seen['kwargs'].get('scoped_factory') == 'A厂', seen


# ---------------------------------------------------------------- 小工具
def _async_value(value):
    async def _inner(*_a, **_kw):
        return value
    return _inner()


def _record_and_return(bucket: list):
    async def _inner(*args, **_kw):
        bucket.append(args)
        return None
    return _inner()
