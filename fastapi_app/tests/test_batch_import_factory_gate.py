"""批量导入工厂闸门（合并前审查 H1，P0-2 补漏）回归测试。

背景：P0-2（fd1c5eb5）给 stock/退货/aux 批量端点补了工厂隔离闸门，但
``/batch/import-stockins``、``/import-stockouts``、``/import-comprehensive``
三个 Excel 导入入口此前零校验——厂绑定用户上传含他厂产品名的表格即可给
他厂入/出库。修复把 ``scoped_factory`` 从端点透传到行处理器，按行拒绝
（与 a5dd07b0 批量端点的逐项拒绝模式对齐），其余行正常导入。

本文件用假 DB + 替身依赖做**单元级**验证（不碰任何真实库），覆盖：
1. ``_row_factory_rejected`` 判定真值表；
2. 服务层备货导入：他厂行拒绝、本厂行放行、未绑定厂全放行；
3. 服务层出货导入：他厂行拒绝；
4. 综合导入的透传分派：scoped 只给备货/出货，不给订单/产品导入。
"""
from __future__ import annotations

from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

from fastapi_app.services import batch_import_core as bic
from fastapi_app.services import batch_import_service as bis
from fastapi_app.services import batch_service
from fastapi_app.services.batch_import_core import _row_factory_rejected

_FACTORY_MSG = '产品不在你的工厂范围'


class _FakeDb:
    """最小假会话：add/flush 记账，begin_nested 空转。"""

    def __init__(self):
        self.added = []
        self.flushed = 0

    @asynccontextmanager
    async def begin_nested(self):
        yield self

    async def execute(self, stmt, *args, **kwargs):  # pragma: no cover - 备货路径不走
        raise AssertionError('备货导入路径不应触发额外 execute')

    async def flush(self):
        self.flushed += 1

    def add(self, obj):
        self.added.append(obj)


def _product(pid: int, factory: str | None):
    return SimpleNamespace(
        id=pid, name=f'产品{pid}', barcode=None, factory=factory, current_stock=100,
    )


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
# ② 服务层备货导入
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


# ---------------------------------------------------------------------------
# ③ 服务层出货导入
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# ④ 综合导入透传分派
# ---------------------------------------------------------------------------

async def test_call_sheet_importer_passes_scoped_factory_only_to_stock_sheets(monkeypatch) -> None:
    stockin_spy = AsyncMock(return_value=(0, []))
    stockout_spy = AsyncMock(return_value=(0, []))
    order_spy = AsyncMock(return_value=(0, []))
    monkeypatch.setattr(bis, 'import_stockins_from_data', stockin_spy, raising=False)
    monkeypatch.setattr(bis, 'import_stockouts_from_data', stockout_spy, raising=False)
    monkeypatch.setattr(bis, 'import_orders_from_data', order_spy, raising=False)

    db = _FakeDb()
    await bis._call_sheet_importer(
        stockin_spy, db, [], None, None, scoped_factory='A厂')
    await bis._call_sheet_importer(
        stockout_spy, db, [], None, None, scoped_factory='A厂')
    await bis._call_sheet_importer(
        order_spy, db, [], None, None, scoped_factory='A厂')

    # 备货/出货收到 scoped_factory；订单导入不接闸门（语义待业务确认）
    assert stockin_spy.await_args.kwargs.get('scoped_factory') == 'A厂'
    assert stockout_spy.await_args.kwargs.get('scoped_factory') == 'A厂'
    assert 'scoped_factory' not in order_spy.await_args.kwargs
