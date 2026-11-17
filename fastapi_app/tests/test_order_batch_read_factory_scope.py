"""批次管理三个读入口的工厂收窄 + 空白名单 fail-closed（审计 P1-2 / P1-4）。

## 拦哪种出错

批次模块有三个列表入口，它们本该共用一套可见性口径，实际却是三个样：

- `GET /order-batch/batch-query`（`get_batch_query_list`）：2026-11-16 H1 已加工厂收窄；
- `GET /order-batch/orders`（`get_batch_orders`）：**没有工厂收窄**（P1-2）；
- `GET /order-batch/history`（`get_batch_history`）：**没有工厂收窄**（P1-2）。

写侧三条路径（改批次号 / 批量分配 / 整批归档）都有
`assert_orders_factory_scoped` 闸门 —— 于是厂绑定账号在列表里能看到别厂的单、
点进去改就 404。更糟的是 `batch-query` 的**白名单为空**时两个分支都不加客户条件
（`if whitelist:` 才过滤）= 返回**全部**订单与备货行，而兄弟入口 `get_batch_orders` /
`get_batch_history` 空白名单直接返回空（P1-4）。白名单是「客户可见范围」，空应该是
「谁都不该看见」，不是「全放行」。

## 本文件各锁一件事

1. `test_orders_list_narrowed_by_factory`：/orders 只返回「全部 SKU 都属本厂或未分厂」的单；
2. `test_history_list_narrowed_by_factory`：/history 同一份判定（避免「历史看得见、当前看不见」）；
3. `test_orders_list_without_user_is_not_narrowed`：`user=None`（超管/诊断脚本）口径不变；
4. `test_empty_whitelist_returns_empty_instead_of_everything`：batch-query 空白名单必须空集；
5. `test_endpoints_forward_current_user`：两个端点必须把 `_current_user` 传进服务层
   （否则服务层永远拿到 None = 收窄失效，等于没修）。
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from fastapi_app.api.v1.endpoints import order_batch as ep
from fastapi_app.services import order_batch_service as svc
from fastapi_app.shared_models import Base, Order, OrderItem, Product

_AP = "甲厂"
_B = "乙厂"


@pytest_asyncio.fixture
async def db_session():
    """真实测试库会话（外层事务跑完即回滚，零持久变更）。"""
    from fastapi_app.tests._test_db_guard import resolve_test_db_url

    engine = create_async_engine(resolve_test_db_url(), poolclass=NullPool)
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        async with engine.connect() as conn:
            trans = await conn.begin()
            session = AsyncSession(
                bind=conn, expire_on_commit=False, join_transaction_mode="create_savepoint",
            )
            try:
                yield session
            finally:
                await session.close()
                await trans.rollback()
    finally:
        await engine.dispose()


async def _make_order(db, tag: str, factory: str | None, *, status: str, customer: str) -> Order:
    product = Product(name=f"批次读侧产品-{tag}", current_stock=0, factory=factory)
    db.add(product)
    await db.flush()
    order = Order(
        order_no=f"ORD-BRS-{tag}", product_id=product.id, customer=customer,
        quantity=7, status=status,
    )
    db.add(order)
    await db.flush()
    db.add(OrderItem(order_id=order.id, product_id=product.id, quantity=7))
    await db.flush()
    return order


def _user(factory: str) -> SimpleNamespace:
    return SimpleNamespace(id=1, factory=factory, is_super=False)


@pytest.mark.asyncio
async def test_orders_list_narrowed_by_factory(db_session, monkeypatch):
    """/orders：厂绑定账号只看得到本厂（或未分厂）的单。"""
    db = db_session
    mine = await _make_order(db, "mine", _AP, status="待备货", customer="客户X")
    theirs = await _make_order(db, "theirs", _B, status="待备货", customer="客户X")
    unassigned = await _make_order(db, "none", None, status="待备货", customer="客户X")
    monkeypatch.setattr(svc, "get_whitelist", lambda _db: _async_value(["客户X"]))

    got = await svc.get_batch_orders(db, user=_user(_AP))

    ids = {item["id"] for item in got["items"]}
    assert mine.id in ids, "本厂单必须可见"
    assert unassigned.id in ids, "未分厂的历史单必须可见（读侧既定口径）"
    assert theirs.id not in ids, "他厂单被读到了 —— 列表越权（P1-2）"
    assert got["total"] == 2, f"total 必须与可见集一致，实际 {got['total']}"


@pytest.mark.asyncio
async def test_history_list_narrowed_by_factory(db_session, monkeypatch):
    """/history：与 /orders 同一份判定。"""
    db = db_session
    mine = await _make_order(db, "hmine", _AP, status="批次已完成", customer="客户Y")
    theirs = await _make_order(db, "htheirs", _B, status="批次已完成", customer="客户Y")
    monkeypatch.setattr(svc, "get_whitelist", lambda _db: _async_value(["客户Y"]))

    got = await svc.get_batch_history(db, user=_user(_AP))

    ids = {item["id"] for item in got["items"]}
    assert mine.id in ids
    assert theirs.id not in ids, "历史列表越权读到他厂单（P1-2）"
    assert got["total"] == 1


@pytest.mark.asyncio
async def test_orders_list_without_user_is_not_narrowed(db_session, monkeypatch):
    """user=None（超管/运维诊断脚本直连会话）不收窄 —— 既有口径不变。"""
    db = db_session
    mine = await _make_order(db, "nmine", _AP, status="待备货", customer="客户Z")
    theirs = await _make_order(db, "ntheirs", _B, status="待备货", customer="客户Z")
    monkeypatch.setattr(svc, "get_whitelist", lambda _db: _async_value(["客户Z"]))

    got = await svc.get_batch_orders(db)  # 不传 user

    ids = {item["id"] for item in got["items"]}
    assert {mine.id, theirs.id} <= ids
    assert got["total"] == 2


@pytest.mark.asyncio
async def test_empty_whitelist_returns_empty_instead_of_everything(db_session, monkeypatch):
    """batch-query：白名单为空 → 空集（P1-4，与兄弟入口同口径）。"""
    db = db_session
    await _make_order(db, "wmine", _AP, status="待备货", customer="客户W")
    monkeypatch.setattr(svc, "get_whitelist", lambda _db: _async_value([]))

    got = await svc.get_batch_query_list(db, user=_user(_AP))

    assert got == {"items": [], "total": 0}, (
        f"空白名单返回了数据 —— fail-open（P1-4）：{got['total']} 行"
    )


async def test_endpoints_forward_current_user(monkeypatch):
    """两个端点必须把当前用户传进服务层（否则收窄永远拿到 None = 没修）。"""
    seen: dict = {}

    async def _recorder(_db, **kwargs):
        seen.update(kwargs)
        return {"items": [], "total": 0}

    user = SimpleNamespace(id=9, factory=_AP, is_super=False)
    monkeypatch.setattr(ep.order_batch_service, "get_batch_orders", _recorder)
    await ep.list_batch_orders(
        page=1, per_page=50, batch_no=None, status=None, customer=None, keyword=None,
        db=object(), _current_user=user,
    )
    assert seen.get("user") is user, "/orders 未把当前用户传给服务层（P1-2）"

    seen.clear()
    monkeypatch.setattr(ep.order_batch_service, "get_batch_history", _recorder)
    await ep.list_batch_history(
        page=1, per_page=50, batch_no=None, customer=None, date_from=None, date_to=None,
        db=object(), _current_user=user,
    )
    assert seen.get("user") is user, "/history 未把当前用户传给服务层（P1-2）"


def _async_value(value):
    async def _inner(*_a, **_kw):
        return value
    return _inner()
