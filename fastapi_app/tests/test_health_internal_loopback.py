"""回环直连（本机 GUI/ watchdog）必须能拿到 /api/health 的内部运维信号。

背景：2026-11-02 `7607554f` 把 backup/audit_retention 等运维细节从**匿名**
/api/health 移除，但 ERP 服务器管理器的「备份」徽章正是匿名探测该接口
（hosting_view.py），结果永远显示「备份 未上报」。

判据：**直连回环**（request.client 为 127.0.0.1/::1 且无 X-Forwarded-For）视为
本机运维进程；经 nginx 反代进入的请求后端同样看到 127.0.0.1，但必然带
X-Forwarded-For（nginx `$proxy_add_x_forwarded_for`），必须继续隐藏内部信号。
"""
from __future__ import annotations

import time
from types import SimpleNamespace

import pytest

from fastapi_app.core import health


def _req(host: str, xff: str | None = None):
    headers = {} if xff is None else {'x-forwarded-for': xff}
    return SimpleNamespace(client=SimpleNamespace(host=host), headers=headers)


def _seed_cache():
    health._health_cache["public_data"] = {"status": "healthy", "app": "erp"}
    health._health_cache["internal_data"] = {
        "backup": {"ok": True, "age_hours": 1.0, "arq_ok": True},
        "audit_retention": {"ok": True},
        "numbering_audit_retention": {"ok": True},
        "checks": {},
    }
    health._health_cache["cached_at"] = time.time()


async def _no_degraded():
    return []


@pytest.mark.asyncio
async def test_direct_loopback_gets_backup_block(monkeypatch):
    _seed_cache()
    monkeypatch.setattr(health, "degraded_reasons_all", _no_degraded)

    payload = await health.health_check(_req("127.0.0.1"), user_id=None)

    assert payload["backup"]["ok"] is True
    assert "db_pool" in payload["checks"]


@pytest.mark.asyncio
async def test_proxied_request_keeps_internal_signals_hidden(monkeypatch):
    """反代请求后端看到的是 127.0.0.1，但带 X-Forwarded-For —— 不得暴露内部信号。"""
    _seed_cache()
    monkeypatch.setattr(health, "degraded_reasons_all", _no_degraded)

    payload = await health.health_check(
        _req("127.0.0.1", xff="203.0.113.9"), user_id=None,
    )

    assert "backup" not in payload
    assert "checks" not in payload


def test_runtime_fingerprint_hidden_for_proxied_requests():
    payload = health._attach_runtime(
        {"status": "healthy"}, _req("127.0.0.1", xff="203.0.113.9"),
    )
    assert "runtime" not in payload
    direct = health._attach_runtime({"status": "healthy"}, _req("127.0.0.1"))
    assert direct["runtime"]["pid"] == health._PROCESS_PID


def test_authenticated_user_still_gets_internal_signals(monkeypatch):
    _seed_cache()
    monkeypatch.setattr(health, "degraded_reasons_all", _no_degraded)
    # 兼容旧 API：显式 user_id 时行为不变
    payload = health._health_from_cache(
        health._health_cache["public_data"], 42, [],
    )
    assert payload["backup"]["ok"] is True
