"""P1-05 回归：产品写端点的工厂隔离。

厂绑定非超管用户：
- create 只能落本厂（客户端传的 factory 被忽略）；
- edit 不能改他厂产品，也不能把产品改挂到别的厂；
- delete 不能删他厂产品。
超管/未绑厂用户行为不变。
"""
from unittest.mock import AsyncMock, MagicMock

import pytest

from fastapi_app.api.v1.endpoints import product as product_ep
from fastapi_app.schemas.product import ProductCreate, ProductUpdate


class _Tx:
    async def __aenter__(self):
        return None

    async def __aexit__(self, *exc):
        return False


@pytest.fixture(autouse=True)
def _patch_infra(monkeypatch):
    monkeypatch.setattr(product_ep, 'db_transaction', lambda db: _Tx())
    monkeypatch.setattr(product_ep.cache_mgr, 'invalidate', AsyncMock())


def _user(factory='东莞', is_super=False):
    return MagicMock(factory=factory, is_super=is_super)


async def test_create_forces_own_factory(monkeypatch):
    svc = AsyncMock()
    monkeypatch.setattr(product_ep.product_service, 'create_product', svc)
    data = ProductCreate(name='产品A', factory='湖北')
    await product_ep.create_product(data=data, db=AsyncMock(), _user=_user())
    assert svc.await_args.kwargs['factory'] == '东莞'


async def test_create_superuser_keeps_requested_factory(monkeypatch):
    svc = AsyncMock()
    monkeypatch.setattr(product_ep.product_service, 'create_product', svc)
    data = ProductCreate(name='产品A', factory='湖北')
    await product_ep.create_product(data=data, db=AsyncMock(), _user=_user(is_super=True))
    assert svc.await_args.kwargs['factory'] == '湖北'


async def test_edit_checks_scope_and_forces_factory(monkeypatch):
    guard = AsyncMock()
    svc = AsyncMock()
    monkeypatch.setattr(product_ep, 'assert_product_factory_scoped', guard)
    monkeypatch.setattr(product_ep.product_service, 'update_product', svc)
    data = ProductUpdate(factory='湖北')
    await product_ep.edit_product(product_id=7, data=data, db=AsyncMock(), _user=_user())
    guard.assert_awaited_once()
    assert guard.await_args.args[1] == 7
    assert svc.await_args.kwargs['factory'] == '东莞'


async def test_edit_does_not_claim_unassigned_product(monkeypatch):
    """factory=None / ''（前端实际提交形态）时不得把未分配工厂产品静默认领。"""
    guard = AsyncMock()
    svc = AsyncMock()
    monkeypatch.setattr(product_ep, 'assert_product_factory_scoped', guard)
    monkeypatch.setattr(product_ep.product_service, 'update_product', svc)
    for payload in (ProductUpdate(price=1), ProductUpdate(factory='')):
        svc.reset_mock()
        await product_ep.edit_product(product_id=7, data=payload, db=AsyncMock(), _user=_user())
        assert svc.await_args.kwargs['factory'] is None


async def test_edit_guard_rejection_blocks_service(monkeypatch):
    """闸门抛 404 时不得调用写服务。"""
    from fastapi import HTTPException

    guard = AsyncMock(side_effect=HTTPException(status_code=404, detail='产品不存在'))
    svc = AsyncMock()
    monkeypatch.setattr(product_ep, 'assert_product_factory_scoped', guard)
    monkeypatch.setattr(product_ep.product_service, 'update_product', svc)
    with pytest.raises(HTTPException) as exc:
        await product_ep.edit_product(product_id=7, data=ProductUpdate(price=1), db=AsyncMock(), _user=_user())
    assert exc.value.status_code == 404
    svc.assert_not_awaited()


async def test_delete_checks_scope(monkeypatch):
    guard = AsyncMock()
    svc = AsyncMock()
    monkeypatch.setattr(product_ep, 'assert_product_factory_scoped', guard)
    monkeypatch.setattr(product_ep.product_service, 'delete_product', svc)
    await product_ep.delete_product(product_id=7, db=AsyncMock(), _user=_user())
    guard.assert_awaited_once()
    assert guard.await_args.args[1] == 7
    svc.assert_awaited_once()
