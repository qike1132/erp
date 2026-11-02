"""认证回退路径必须取 token 自己的 tv，而不是默认 0。

OCR 评审发现：`_authenticate_user_id` 在 request.state 上没有 payload 的罕见
回退分支里曾写成 `(payload or {}).get('tv', 0)`——payload 缺失时恒取 0，会把
token_version>0 的合法 token 误判为过期（每次请求 401，直到重新登录）。
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from fastapi_app.core import deps


@pytest.mark.asyncio
async def test_fallback_path_reads_tv_from_token(monkeypatch: pytest.MonkeyPatch) -> None:
    request = SimpleNamespace(state=SimpleNamespace())  # 没有 _jwt_payload

    monkeypatch.setattr(deps, '_resolve_user_id', lambda r: 7)
    monkeypatch.setattr(deps, '_resolve_token_jti', lambda r: 'jti-x')
    monkeypatch.setattr(deps, '_resolve_token_tv', lambda r: 5)
    monkeypatch.setattr(deps, 'is_token_revoked', AsyncMock(return_value=False))

    seen: dict[str, object] = {}

    async def _active(user_id, db, *, expected_token_version=None):
        seen['user_id'] = user_id
        seen['tv'] = expected_token_version
        return True

    monkeypatch.setattr(deps, '_verify_user_active', _active)

    assert await deps._authenticate_user_id(request, AsyncMock()) == 7
    assert seen['tv'] == 5, '回退路径必须使用 token 的 tv，否则合法 token 会被误杀'
