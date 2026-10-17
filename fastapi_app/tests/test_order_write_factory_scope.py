"""订单写端点工厂隔离回归（2026-10-17 审计 F-BE-API-01）。

读端点早有「绑定工厂的非超管只能碰本厂」隔离，写端点只认权限码按 id 直取，
厂绑定用户可对可枚举的自增 order_id 跨厂 PUT/DELETE。修复后六个写端点统一
走 _assert_order_factory_scoped：非本厂订单一律 404。
"""
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException

from fastapi_app.api.v1.endpoints.order import _assert_order_factory_scoped


def _user(factory='东莞', is_super=False):
    u = MagicMock()
    u.factory = factory
    u.is_super = is_super
    return u


def _db(scalar):
    """db.execute(...) await 后 scalar_one_or_none() 返回 scalar。"""
    result = MagicMock()
    result.scalar_one_or_none.return_value = scalar
    db = MagicMock()
    db.execute = AsyncMock(return_value=result)
    return db


@pytest.mark.asyncio
async def test_cross_factory_order_returns_404():
    """厂绑定用户访问他厂订单 → 404（不暴露存在性）。"""
    db = _db('湖北')  # 订单的工厂归属
    with pytest.raises(HTTPException) as ei:
        await _assert_order_factory_scoped(db, 123, _user('东莞'))
    assert ei.value.status_code == 404


@pytest.mark.asyncio
async def test_same_factory_passes():
    db = _db('东莞')
    await _assert_order_factory_scoped(db, 123, _user('东莞'))  # 不抛即过


@pytest.mark.asyncio
async def test_super_user_bypasses():
    db = _db('湖北')
    await _assert_order_factory_scoped(db, 123, _user('东莞', is_super=True))


@pytest.mark.asyncio
async def test_unbound_user_bypasses():
    """factory=None 的用户不受限（与读端点同口径）。"""
    db = MagicMock()
    db.execute = AsyncMock(side_effect=AssertionError('不应发起查询'))
    await _assert_order_factory_scoped(db, 123, _user(None))


@pytest.mark.asyncio
async def test_order_without_factory_product_passes():
    """订单的物料都没挂工厂（factory 全 NULL）→ 无法判定归属，放行（与读端点
    WHERE 过滤的行为一致：过滤条件 isnot(None) 下该订单本就不可见——但写侧
    service 层仍有自己的权限校验兜底）。"""
    db = _db(None)
    await _assert_order_factory_scoped(db, 123, _user('东莞'))
