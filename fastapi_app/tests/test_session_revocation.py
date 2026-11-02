"""会话撤销（token_version）回归。

背景：JWT 无状态，改密/改超管/改工厂/禁用后旧 token 一直可用，refresh 还会
按 now+7d 重算过期，实际是无限续签。token 里带 tv 声明、请求时与库里值比对，
敏感变更把它 +1 即可让旧凭据立刻失效。
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from fastapi_app.core import deps
from fastapi_app.services import user_service


@pytest.fixture(autouse=True)
async def _clean_active_cache():
    await deps._USER_ACTIVE_CACHE.clear()
    yield
    await deps._USER_ACTIVE_CACHE.clear()


def _db_row(*, status: bool, token_version: int, found: bool = True):
    db = MagicMock()
    result = MagicMock()
    result.first.return_value = (
        SimpleNamespace(status=status, token_version=token_version) if found else None
    )
    db.execute = AsyncMock(return_value=result)
    return db


@pytest.mark.asyncio
async def test_matching_token_version_passes() -> None:
    db = _db_row(status=True, token_version=3)
    assert await deps._verify_user_active(1, db, expected_token_version=3) is True


@pytest.mark.asyncio
async def test_stale_token_version_is_rejected() -> None:
    db = _db_row(status=True, token_version=3)
    assert await deps._verify_user_active(1, db, expected_token_version=2) is False


@pytest.mark.asyncio
async def test_legacy_token_without_tv_is_treated_as_zero() -> None:
    """加列上线时已签发的旧 token 不带 tv，必须仍可用。"""
    db = _db_row(status=True, token_version=0)
    assert await deps._verify_user_active(1, db, expected_token_version=0) is True


@pytest.mark.asyncio
async def test_bump_increments_version_and_invalidates_cache() -> None:
    await deps._USER_ACTIVE_CACHE.set(7, (True, 0))
    user = SimpleNamespace(id=7, token_version=0)
    await user_service.bump_token_version(AsyncMock(), user)
    assert user.token_version == 1
    assert await deps._USER_ACTIVE_CACHE.get(7) is None
