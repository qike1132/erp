"""整库恢复后强制全员重新登录。

备份时点之后的登出/撤销记录会随 DB 与 Redis RDB 一起回滚——备份后登出的
token 会重新有效。恢复成功后把所有用户 token_version +1 是权威手段。
"""
from __future__ import annotations

import pytest

from fastapi_app.services.backup import restore as restore_mod


@pytest.mark.asyncio
async def test_restore_revokes_every_session(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, str] = {}

    class _FakeConn:
        async def execute(self, stmt):
            captured['sql'] = str(stmt)

    class _FakeTx:
        async def __aenter__(self):
            return _FakeConn()

        async def __aexit__(self, *exc):
            return False

    class _FakeEngine:
        def begin(self):
            return _FakeTx()

    monkeypatch.setattr(
        'fastapi_app.core.database.require_async_engine', lambda: _FakeEngine(),
        raising=False,
    )
    await restore_mod.revoke_all_sessions_after_restore()
    assert 'token_version' in captured['sql'].lower()


@pytest.mark.asyncio
async def test_restore_revocation_failure_does_not_raise(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """收尾失败只记日志：恢复本身已成功，不能因清理失败改判。"""

    def _explode():
        raise RuntimeError('engine unavailable')

    monkeypatch.setattr(
        'fastapi_app.core.database.require_async_engine', _explode, raising=False,
    )
    await restore_mod.revoke_all_sessions_after_restore()  # 不抛即过
