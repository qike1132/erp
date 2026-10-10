"""get_async_db_context 的 post-commit 回调回归测试。

背景（2026-10-10 评审 P0-1）：get_async_db（请求路径）在 commit 成功后
执行 run_post_commit_callbacks，但 get_async_db_context（ARQ 任务等
非请求场景）commit 成功后不执行 —— 注册的缓存失效/领域事件回调被静默丢弃。

修法：commit 成功后补跑回调，与 get_async_db 逐字同款（回调失败不影响
已提交事务）。
"""
from typing import ClassVar

import pytest

from fastapi_app.core.database import get_async_db_context


@pytest.mark.asyncio
async def test_context_runs_post_commit_callbacks_after_successful_commit(monkeypatch):
    """commit 成功后必须执行 session.info 上注册的回调。"""
    executed = []

    async def fake_commit():
        executed.append("commit")

    # init_async_engine 未跑时 _AsyncSessionLocal 为 None，注入桩工厂
    class StubSession:
        info: ClassVar[dict] = {}

        def __init__(self):
            self.commit = fake_commit
            self.rollback = fake_commit

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

    stub_factory = StubSession
    monkeypatch.setattr(
        "fastapi_app.core.database._AsyncSessionLocal", stub_factory
    )

    # ensure_engine_for_current_loop 会碰真实引擎；打桩跳过
    async def fake_ensure():
        return None

    monkeypatch.setattr(
        "fastapi_app.core.database.ensure_engine_for_current_loop", fake_ensure
    )

    async with get_async_db_context() as session:
        assert isinstance(session.info, dict)

        async def callback():
            executed.append("callback")

        session.info.setdefault("post_commit_callbacks", []).append(callback)

    assert executed == ["commit", "callback"]


@pytest.mark.asyncio
async def test_context_skips_callbacks_on_commit_failure(monkeypatch):
    """commit 失败（回滚后重抛）时不得执行回调——业务数据未提交。"""
    executed = []

    async def failing_commit():
        raise RuntimeError("commit failed")

    class StubSession:
        info: ClassVar[dict] = {}

        def __init__(self):
            self.commit = failing_commit
            self.rollback = failing_commit

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

    monkeypatch.setattr(
        "fastapi_app.core.database._AsyncSessionLocal", StubSession
    )

    async def fake_ensure():
        return None

    monkeypatch.setattr(
        "fastapi_app.core.database.ensure_engine_for_current_loop", fake_ensure
    )

    with pytest.raises(RuntimeError):
        async with get_async_db_context() as session:
            session.info.setdefault("post_commit_callbacks", []).append(
                lambda: executed.append("callback")
            )

    assert "callback" not in executed
