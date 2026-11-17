"""按单号还原退货明细的工厂收窄（2026-11-17 上线前审计 P1-3）。

## 拦哪种出错

`GET /stock-returns/records`（`get_stockreturn_records`）是报表聚合行的「还原」入口：
前端拿到聚合行后按 return_no 拉回具体记录，供行内编辑/删除。它只按单号 + status
过滤，**没有工厂收窄** —— 而列表端点 `get_stockreturns` 早在 2026-10（4c）就按
`factory` 收窄了，兄弟入口 `stock/out/records`（`get_stockout_records`）也带
`factory=_factory_scope(_user)`。

于是厂绑定账号只要拿到他厂退货单号（报表可以导出、单号是 RETURN-YYYYMMDD-NNNN 顺序号），
就能还原出他厂的退货明细（产品名/客户/数量/日期/原因），并用同一条链路做行内编辑或删除。

## 本文件锁什么

1. `test_records_narrowed_by_factory`：真实测试库造甲/乙厂各一条退货，甲厂账号只还原出甲厂那条；
2. `test_records_show_unassigned_factory_rows`：未分厂的历史行照常可见（与写侧放行口径一致，
   否则老数据谁都查不到）；
3. `test_records_without_factory_not_narrowed`：`factory=None`（超管/未绑定厂）口径不变；
4. `test_endpoint_forwards_factory_scope`：端点必须传 `factory_scope_of(user)` —— 否则服务层
   永远拿到 None，等于没修。
"""
from types import SimpleNamespace

import pytest
from test_stock_return_api import sr_api as _api_fixture

from fastapi_app.api.v1.endpoints import stock_return as ep
from fastapi_app.services.stock_inventory_service import get_stockreturn_records
from fastapi_app.shared_models import Product, StockReturn

# pytest 按模块属性名注册导入的夹具
sr_api = _api_fixture


async def _make_return(db, tag: str, factory: str | None, return_no: str) -> StockReturn:
    product = Product(name=f"退货还原产品-{tag}", current_stock=0, factory=factory)
    db.add(product)
    await db.flush()
    row = StockReturn(
        return_no=return_no, product_id=product.id, quantity=3,
        customer=f"退货还原客户-{tag}", status='active',
    )
    db.add(row)
    await db.flush()
    return row


@pytest.mark.integration
async def test_records_narrowed_by_factory(sr_api):
    _client, db, _ = sr_api
    mine = await _make_return(db, 'p13a', '甲厂', 'SR-P13-A')
    theirs = await _make_return(db, 'p13b', '乙厂', 'SR-P13-B')

    rows = await get_stockreturn_records(db, nos='SR-P13-A,SR-P13-B', factory='甲厂')

    ids = {row['id'] for row in rows}
    assert mine.id in ids, '本厂退货明细必须还原出来'
    assert theirs.id not in ids, '他厂退货明细被还原了 —— 越权读（P1-3）'


@pytest.mark.integration
async def test_records_show_unassigned_factory_rows(sr_api):
    """未分厂（NULL/空串）的历史行照常可见 —— 与写侧 factory_scope 放行面一致。"""
    _client, db, _ = sr_api
    legacy = await _make_return(db, 'p13c', None, 'SR-P13-C')

    rows = await get_stockreturn_records(db, nos='SR-P13-C', factory='甲厂')

    assert [row['id'] for row in rows] == [legacy.id]


@pytest.mark.integration
async def test_records_without_factory_not_narrowed(sr_api):
    _client, db, _ = sr_api
    a = await _make_return(db, 'p13d', '甲厂', 'SR-P13-D')
    b = await _make_return(db, 'p13e', '乙厂', 'SR-P13-E')

    rows = await get_stockreturn_records(db, nos='SR-P13-D,SR-P13-E')

    ids = {row['id'] for row in rows}
    assert {a.id, b.id} <= ids, '不传 factory 时应保持原口径（超管/未绑定厂）'


async def test_endpoint_forwards_factory_scope(monkeypatch):
    seen: dict = {}

    async def _recorder(_db, **kwargs):
        seen.update(kwargs)
        return []

    monkeypatch.setattr(ep, 'get_stockreturn_records', _recorder)
    user = SimpleNamespace(id=7, factory='甲厂', is_super=False)

    await ep.list_return_records(nos='SR-1', db=object(), _user=user)

    assert seen.get('factory') == '甲厂', (
        '端点没把 factory_scope_of(user) 传进服务层 —— 收窄永远拿到 None（P1-3）'
    )
