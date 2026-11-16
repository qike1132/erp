"""WebSocket 凭据必须继承并复核 token_version（2026-11-16 审计 Medium）。

拦哪种错：`_clean_auth_payload` 只保留 jti/exp、`_load_ws_user` 只判 status 的写法 ——
改密/重置口令后 token_version 递增，HTTP 侧同一 access token 立刻 401，但长连接仍能
建连、并通过 60s 复核继续收业务事件（凭据已作废却还在收数据）。

自包含：数据库用假会话替身（不连库），Redis（黑名单/票据）全部打桩，不碰生产 Redis。
"""
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from fastapi_app.api import ws as ws_module
from fastapi_app.api.ws import register_websocket

DEPS_MOD = "fastapi_app.core.deps"
REDIS_MOD = "fastapi_app.core.redis_wrapper"

FUTURE_EXP = int(time.time()) + 3600


def _entity(user_id: int, token_version: int) -> SimpleNamespace:
    """`_load_ws_user_from_session` 需要的整实体（权限/超管字段够 manager 用即可）。"""
    return SimpleNamespace(
        id=user_id,
        status=True,
        is_super=True,
        factory=None,
        token_version=token_version,
        has_permission=lambda _code: True,
    )


class _Result:
    """同时满足两条取数路径：整实体走 scalar_one_or_none，活跃校验走 first。"""

    def __init__(self, entity, row) -> None:
        self._entity = entity
        self._row = row

    def unique(self):
        return self

    def scalar_one_or_none(self):
        return self._entity

    def first(self):
        return self._row


class _Session:
    def __init__(self, entity, row) -> None:
        self._entity = entity
        self._row = row

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return None

    async def execute(self, *_args, **_kwargs):
        return _Result(self._entity, self._row)


def _db_factory(user_id: int = 0, *, db_token_version: int = 0):
    """假库：用户当前 token_version = db_token_version（= 改密/重置后已 bump 的值）。"""
    entity = _entity(user_id, db_token_version)
    row = SimpleNamespace(id=user_id, status=True, token_version=db_token_version)
    return lambda: _Session(entity, row)


class _FakeWebSocket:
    """只记 close/send，够驱动 `_message_loop`（它的所有出口都是 close+break）。"""

    def __init__(self) -> None:
        self.closed: list[tuple[int, str]] = []
        self.sent: list[str] = []

    async def receive_text(self) -> str:
        return "ping"

    async def send_text(self, text: str) -> None:
        self.sent.append(text)

    async def close(self, code: int = 1000, reason: str = "") -> None:
        self.closed.append((code, reason))


class _FakeManager:
    def __init__(self) -> None:
        self.updated: list = []

    def update_principal(self, _websocket, principal) -> None:
        self.updated.append(principal)


@pytest.fixture(autouse=True)
async def _clear_user_active_cache():
    """活跃状态/会话版本缓存是进程级 10s TTL：不清理会串到下一个用例。"""
    from fastapi_app.core.deps import _USER_ACTIVE_CACHE

    await _USER_ACTIVE_CACHE.clear()
    yield
    await _USER_ACTIVE_CACHE.clear()


@pytest.fixture(autouse=True)
def _clear_pending_tickets():
    """进程内票据表是模块级全局：用例之间清干净，避免残留票据被下一个用例消费。"""
    ws_module._WS_PENDING_TICKETS.clear()
    yield
    ws_module._WS_PENDING_TICKETS.clear()


@pytest.fixture()
def ws_app(monkeypatch):
    application = FastAPI()
    register_websocket(application)
    monkeypatch.setattr(ws_module, "_origin_allowed", lambda _origin: True)
    monkeypatch.setattr(ws_module, "get_async_db_context", _db_factory())
    # 黑名单与票据走 Redis：单元测试里一律打桩，避免连生产 Redis
    monkeypatch.setattr(f"{DEPS_MOD}.is_token_revoked", AsyncMock(return_value=False))
    monkeypatch.setattr(f"{REDIS_MOD}.safe_delete", AsyncMock())
    monkeypatch.setattr(f"{REDIS_MOD}.safe_get", AsyncMock(return_value=None))
    return application


def _put_ticket(user_id: int, auth: dict) -> str:
    ticket = f"tk-{user_id}-{time.monotonic_ns()}"
    ws_module._WS_PENDING_TICKETS[ticket] = (user_id, time.monotonic(), auth)
    return ticket


# ============================================================================
# 凭据载荷
# ============================================================================
def test_clean_auth_payload_keeps_token_version():
    """tv 必须跟着票据走：丢了它，长连接就再也比不了会话版本。"""
    payload = ws_module._clean_auth_payload(
        {"sub": "7", "jti": "j-7", "exp": FUTURE_EXP, "tv": 3}
    )

    assert payload == {"jti": "j-7", "exp": FUTURE_EXP, "tv": 3}


def test_expected_token_version_absent_means_no_comparison():
    """滚动发布期 30s 内的旧票据没有 tv：返回 None（退回只判启用状态）。"""
    assert ws_module._expected_token_version({}) is None
    assert ws_module._expected_token_version({"tv": 4}) == 4
    assert ws_module._expected_token_version({"tv": "5"}) == 5
    # 不可解析按 0 参与比对（fail-closed）
    assert ws_module._expected_token_version({"tv": "oops"}) == 0


# ============================================================================
# 建连：tv 不匹配被拒 / 匹配通过
# ============================================================================
def test_connect_rejected_when_token_version_stale(ws_app, monkeypatch):
    """改密后旧 access token 建连必须被拒（凭据 tv=1，用户当前 2）。

    服务端先 accept 再 close（握手已完成，凭据判定在握手后），所以拒绝表现为
    「连上了但立刻断开」：必须真去读一条消息才拿得到 WebSocketDisconnect。
    """
    user_id = 31
    monkeypatch.setattr(ws_module, "get_async_db_context", _db_factory(user_id, db_token_version=2))
    ticket = _put_ticket(user_id, {"jti": "j-31", "exp": FUTURE_EXP, "tv": 1})

    with pytest.raises(Exception):  # noqa: BLE001 - TestClient 把拒绝握手封装成运行时异常
        with TestClient(ws_app).websocket_connect(f"/ws/notifications?ticket={ticket}") as websocket:
            websocket.receive_text()

    from fastapi_app.services.notification_service import manager

    assert user_id not in manager.active_connections, "被拒的连接不得登记到 manager"


def test_connect_allowed_when_token_version_matches(ws_app, monkeypatch):
    """tv 匹配（凭据 5，用户当前 5）时必须正常建连并能收发心跳。"""
    user_id = 41
    monkeypatch.setattr(ws_module, "get_async_db_context", _db_factory(user_id, db_token_version=5))
    ticket = _put_ticket(user_id, {"jti": "j-41", "exp": FUTURE_EXP, "tv": 5})

    with TestClient(ws_app).websocket_connect(f"/ws/notifications?ticket={ticket}") as websocket:
        websocket.send_text("ping")
        assert websocket.receive_text() == "pong"


# ============================================================================
# 60s 周期复核：tv 变化即断开
# ============================================================================
async def test_periodic_recheck_closes_when_token_version_changed(monkeypatch):
    """连接建立后改密：复核发现 tv 不符 → 4001 断开（不能继续收事件）。"""
    user_id = 21
    monkeypatch.setattr(ws_module, "get_async_db_context", _db_factory(user_id, db_token_version=2))
    # 让每条消息都走一次复核（等价于 60s 到点），不用真等
    monkeypatch.setattr(ws_module, "_WS_VERIFY_INTERVAL", -1)
    monkeypatch.setattr(f"{DEPS_MOD}.is_token_revoked", AsyncMock(return_value=False))
    websocket = _FakeWebSocket()
    manager = _FakeManager()

    await ws_module._message_loop(
        websocket, user_id, None,
        manager=manager,
        auth_payload={"jti": "j-21", "exp": FUTURE_EXP, "tv": 1},
    )

    assert websocket.closed == [(4001, "会话已失效，请重新登录")]
    assert manager.updated == [], "tv 不符的连接不得刷新主体（先断开再谈其他）"


async def test_periodic_recheck_keeps_connection_when_token_version_matches(monkeypatch):
    """对照组：tv 一致时复核不得误杀长连接（否则改密前的正常用户会被踢）。"""
    user_id = 22
    monkeypatch.setattr(ws_module, "get_async_db_context", _db_factory(user_id, db_token_version=3))
    monkeypatch.setattr(ws_module, "_WS_VERIFY_INTERVAL", -1)
    monkeypatch.setattr(f"{DEPS_MOD}.is_token_revoked", AsyncMock(return_value=False))
    websocket = _FakeWebSocket()
    manager = _FakeManager()
    received = {"n": 0}

    async def _receive() -> str:
        received["n"] += 1
        if received["n"] > 1:
            # 复核已经跑过一轮：用正常断开收尾，否则这个假 socket 会一直喂 ping
            raise ws_module.WebSocketDisconnect()
        return "ping"

    websocket.receive_text = _receive  # type: ignore[method-assign]

    await ws_module._message_loop(
        websocket, user_id, None,
        manager=manager,
        auth_payload={"jti": "j-22", "exp": FUTURE_EXP, "tv": 3},
    )

    assert websocket.closed == [], "tv 一致时不得断开"
    assert len(manager.updated) == 1, "复核应把最新主体刷到 manager"
