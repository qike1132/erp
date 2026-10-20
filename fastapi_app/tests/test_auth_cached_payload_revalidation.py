"""P1-14：限流中间件预写入 payload 时，早返回也必须校验撤销/禁用。"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from fastapi_app.core import deps


def _request(payload=None):
    state = SimpleNamespace()
    if payload is not None:
        state._jwt_payload = payload
    return SimpleNamespace(state=state)


async def test_revoked_token_is_rejected_even_with_cached_payload(monkeypatch) -> None:
    req = _request({'sub': '7', 'jti': 'jti-1'})
    revoked = AsyncMock(return_value=True)
    active = AsyncMock(return_value=True)
    monkeypatch.setattr(deps, 'is_token_revoked', revoked)
    monkeypatch.setattr(deps, '_verify_user_active', active)

    with pytest.raises(HTTPException) as exc:
        await deps._authenticate_user_id(req, AsyncMock())

    assert exc.value.status_code == 401
    assert 'Token已失效' in exc.value.detail
    revoked.assert_awaited_with('jti-1', fail_closed=False)
    active.assert_not_awaited()


async def test_disabled_user_is_rejected_even_with_cached_payload(monkeypatch) -> None:
    req = _request({'sub': '7', 'jti': 'jti-2'})
    monkeypatch.setattr(deps, 'is_token_revoked', AsyncMock(return_value=False))
    monkeypatch.setattr(deps, '_verify_user_active', AsyncMock(return_value=False))

    with pytest.raises(HTTPException) as exc:
        await deps._authenticate_user_id(req, AsyncMock())

    assert exc.value.status_code == 401
    assert '禁用' in exc.value.detail


async def test_active_user_with_cached_payload_passes(monkeypatch) -> None:
    req = _request({'sub': '7', 'jti': 'jti-3'})
    revoked = AsyncMock(return_value=False)
    active = AsyncMock(return_value=True)
    monkeypatch.setattr(deps, 'is_token_revoked', revoked)
    monkeypatch.setattr(deps, '_verify_user_active', active)

    assert await deps._authenticate_user_id(req, AsyncMock()) == 7
    revoked.assert_awaited_with('jti-3', fail_closed=False)
    assert active.await_count == 1


async def test_strict_path_still_uses_fail_closed_blacklist(monkeypatch) -> None:
    req = _request(None)
    monkeypatch.setattr(deps, '_resolve_user_id', lambda r: 7)
    monkeypatch.setattr(deps, '_resolve_token_jti', lambda r: 'from-header')
    revoked = AsyncMock(return_value=False)
    monkeypatch.setattr(deps, 'is_token_revoked', revoked)
    monkeypatch.setattr(deps, '_verify_user_active', AsyncMock(return_value=True))

    assert await deps._authenticate_user_id(req, AsyncMock(), fail_closed=True) == 7
    revoked.assert_awaited_with('from-header', fail_closed=True)
