from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from fastapi_app.api import ws as ws_module
from fastapi_app.api.ws import register_websocket


@pytest.fixture()
def app(monkeypatch):
    application = FastAPI()
    register_websocket(application)

    class Result:
        def first(self):
            return (1, True)

        def unique(self):
            return self

        def scalar_one_or_none(self):
            return SimpleNamespace(
                status=True, is_super=True, factory=None,
                has_permission=lambda _code: True,
            )

    class Connection:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def execute(self, *_args, **_kwargs):
            return Result()

    monkeypatch.setattr(ws_module, "async_engine", type("Engine", (), {"connect": Connection})())
    return application


def test_ticket_is_single_use(app, monkeypatch):
    monkeypatch.setattr(ws_module, "_origin_allowed", lambda _origin: True)
    client = TestClient(app)
    ws_module._WS_PENDING_TICKETS["ticket"] = (1, __import__("time").monotonic())
    with client.websocket_connect("/ws/notifications?ticket=ticket") as websocket:
        websocket.send_text("ping")
        assert websocket.receive_text() == "pong"
    with pytest.raises(Exception):  # noqa: BLE001 - TestClient 对拒绝握手封装为任意运行时异常
        with client.websocket_connect("/ws/notifications?ticket=ticket"):
            pass


def test_ticket_expired_rejected(app, monkeypatch):
    """第十一轮落地：进程内票据同样有 30s TTL —— 超龄票据即使未被消费也一律作废。"""
    import time

    monkeypatch.setattr(ws_module, "_origin_allowed", lambda _origin: True)
    client = TestClient(app)
    ws_module._WS_PENDING_TICKETS["stale"] = (1, time.monotonic() - 10_000)
    with pytest.raises(Exception):  # noqa: BLE001 - TestClient 对拒绝握手封装为任意运行时异常
        with client.websocket_connect("/ws/notifications?ticket=stale"):
            pass
    assert "stale" not in ws_module._WS_PENDING_TICKETS


def test_rate_limit_bump_window(monkeypatch):
    """拆分后 _bump_rate_window 的行为契约（P2-14）：60s 窗口重置 + 超限判定。"""
    now = 1000.0
    # 新窗口起算：计数从 0 → 1，不超限
    count, start, over = ws_module._bump_rate_window(now, 0, now - 61)
    assert (count, start) == (1, now) and not over
    # 同窗口累加到阈值：不超限
    count, _, over = ws_module._bump_rate_window(now, ws_module._WS_RATE_LIMIT - 1, now)
    assert count == ws_module._WS_RATE_LIMIT and not over
    # 再加一条：超限
    count, _, over = ws_module._bump_rate_window(now, ws_module._WS_RATE_LIMIT, now)
    assert count == ws_module._WS_RATE_LIMIT + 1 and over
