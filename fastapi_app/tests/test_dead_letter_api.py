"""死信队列 API：重试成功/失败/并发/权限与 Redis fail-closed。"""
from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from fastapi_app.core.deps import _get_user_with_permissions
from fastapi_app.main import app
from fastapi_app.shared_models import User

pytestmark = [pytest.mark.asyncio]
PREFIX = "/api/v1/dead-letter/dead-letter"


def _entry(task_id: str = "dead-1") -> str:
    return json.dumps({
        "task_id": task_id,
        "task_name": "demo_task",
        "args": "(1,)",
        "kwargs": "{'flag': True}",
    })


def _client(*, set_result=True, eval_result=1):
    return SimpleNamespace(
        set=AsyncMock(return_value=set_result),
        eval=AsyncMock(return_value=eval_result),
    )


def _patches(redis_client, entries, *, enqueue=None):
    pool = SimpleNamespace(enqueue_job=enqueue or AsyncMock(return_value=SimpleNamespace(job_id="new-1")))
    return (
        patch("fastapi_app.api.v1.endpoints.dead_letter.get_client", return_value=redis_client),
        patch("fastapi_app.api.v1.endpoints.dead_letter.safe_lrange", AsyncMock(return_value=entries)),
        patch("fastapi_app.api.v1.endpoints.dead_letter.safe_llen", AsyncMock(return_value=len(entries))),
        patch("fastapi_app.api.v1.endpoints.dead_letter.safe_lrem", AsyncMock(return_value=1)),
        patch("fastapi_app.core.arq_app.get_arq_pool", AsyncMock(return_value=pool)),
    )


async def test_retry_parses_payload_removes_after_enqueue_and_releases_lock(
    client
):
    raw = _entry()
    redis_client = _client()
    enqueue = AsyncMock(return_value=SimpleNamespace(job_id="new-1"))
    patches = _patches(redis_client, [raw], enqueue=enqueue)
    with patches[0], patches[1], patches[2], patches[3] as lrem, patches[4]:
        response = await client.post(f"{PREFIX}/dead-1/retry")

    assert response.status_code == 200, response.text
    assert response.json()["new_task_id"] == "new-1"
    enqueue.assert_awaited_once_with("demo_task", 1, flag=True)
    lrem.assert_awaited_once()
    redis_client.eval.assert_awaited_once()


async def test_enqueue_failure_keeps_dead_letter_and_releases_lock(
    client
):
    redis_client = _client()
    enqueue = AsyncMock(side_effect=RuntimeError("arq unavailable"))
    patches = _patches(redis_client, [_entry()], enqueue=enqueue)
    with patches[0], patches[1], patches[2], patches[3] as lrem, patches[4]:
        response = await client.post(f"{PREFIX}/dead-1/retry")

    assert response.status_code == 500
    assert lrem.await_count == 0, "入队失败绝不能删除原死信"
    redis_client.eval.assert_awaited_once()


async def test_retry_not_found_redis_down_and_permission(client):
    redis_client = _client()
    patches = _patches(redis_client, [_entry("other")])
    with patches[0], patches[1], patches[2], patches[3], patches[4]:
        missing = await client.post(f"{PREFIX}/missing/retry")
    assert missing.status_code == 404

    with patch("fastapi_app.api.v1.endpoints.dead_letter.get_client", return_value=None):
        down = await client.post(f"{PREFIX}/dead-1/retry")
    assert down.status_code == 503

    user = User(username="not-super", password="x", is_super=False, status=True)
    user.permissions = []

    async def override_user():
        return user

    app.dependency_overrides[_get_user_with_permissions] = override_user
    try:
        denied = await client.post(f"{PREFIX}/dead-1/retry")
    finally:
        app.dependency_overrides.pop(_get_user_with_permissions, None)
    assert denied.status_code == 403


async def test_concurrent_retry_only_one_enqueues(client):
    redis_client = _client()
    redis_client.set.side_effect = [True, False]
    enqueue = AsyncMock(return_value=SimpleNamespace(job_id="new-1"))
    patches = _patches(redis_client, [_entry()], enqueue=enqueue)
    with patches[0], patches[1], patches[2], patches[3], patches[4]:
        first, second = await asyncio.gather(
            client.post(f"{PREFIX}/dead-1/retry"),
            client.post(f"{PREFIX}/dead-1/retry"),
        )

    assert {first.status_code, second.status_code} == {200, 409}
    assert enqueue.await_count == 1


async def test_list_stats_remove_and_malformed_entry(client):
    redis_client = _client()
    entries = [_entry("dead-1"), _entry("dead-2")]
    patches = _patches(redis_client, entries)
    with patches[0], patches[1], patches[2], patches[3] as lrem, patches[4]:
        listed = await client.get(f"{PREFIX}?limit=1&offset=1")
        stats = await client.get(f"{PREFIX}/stats")
        removed = await client.delete(f"{PREFIX}/dead-1")
        missing = await client.delete(f"{PREFIX}/missing")

    assert listed.status_code == 200
    assert listed.json()["total"] == 2
    assert stats.status_code == 200 and stats.json()["total_failed"] == 2
    assert removed.status_code == 200 and removed.json()["status"] == "removed"
    assert missing.status_code == 404
    lrem.assert_awaited_once()

    malformed = _patches(_client(), ["{not-json"])
    with malformed[0], malformed[1], malformed[2], malformed[3] as lrem, malformed[4]:
        response = await client.post(f"{PREFIX}/dead-1/retry")
    assert response.status_code == 500
    assert lrem.await_count == 0, "坏死信记录不得在未入队时被移除"
