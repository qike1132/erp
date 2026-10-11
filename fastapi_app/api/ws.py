"""
WebSocket 实时通知端点

从 main.py 提取。支持三种认证方式：
1. Cookie JWT（浏览器自动携带）
2. WebSocket 认证票据（解决 Vite/部分网关代理不转发 Cookie 的握手问题）
3. 首条消息认证（移动端/API客户端发送 {"type":"auth","token":"xxx"}）

安全机制：
- 连接建立前校验 Origin 白名单（防跨站劫持）
- 建立连接后进行 Cookie/票据/消息 JWT 认证
- 票据有效期 30 秒且一次性使用，不暴露长期 JWT
- disconnect 安全处理未注册连接（防二次异常）

2026-10-11（复核 P2-14）结构拆分：websocket_notifications 原 155 行（C901 31+30），
三次 close-break 泄漏修复史使其成为全仓风险最高的函数。现提取
_authenticate / _verify_user_active / _message_loop 三个单元，主协程只保留
接线顺序；行为不变（现有 test_ws_ticket_auth.py 全量回归）。
"""

import asyncio
import contextlib
import json as _json
import logging
import secrets
import time
from typing import Any
from urllib.parse import urlparse

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from sqlalchemy import select as ws_select
from sqlalchemy.exc import DisconnectionError, OperationalError

from fastapi_app.core.config import settings
from fastapi_app.core.database import async_engine
from fastapi_app.shared_models import User as WSUser

logger = logging.getLogger(__name__)

_WS_AUTH_TIMEOUT = 5
_WS_TICKET_TTL_SECONDS = 30
_WS_TICKET_PREFIX = "ws:auth_ticket:"
_WS_HEARTBEAT_INTERVAL_SECONDS = 30
_WS_HEARTBEAT_TIMEOUT = 60
_WS_RATE_LIMIT = 30
_WS_VERIFY_INTERVAL = 60

# 进程内票据表：value = (user_id, issued_monotonic)。
# 第十轮审计：原只存 user_id —— 无时间戳无清理，票据在进程内**永久有效**（Redis 侧
# 才有 30s TTL），且未消费的票据使内存单调增长。补时间戳 + 消费时校验年龄 + 签发时清理过期项。
_WS_PENDING_TICKETS: dict[str, tuple[int, float]] = {}


async def _issue_ws_ticket(user_id: int) -> str:
    from fastapi_app.core.redis_wrapper import safe_set

    ticket = secrets.token_urlsafe(32)
    now = time.monotonic()
    # 顺手清掉过期票据，防止内存单调增长
    expired = [t for t, (_, ts) in _WS_PENDING_TICKETS.items() if now - ts > _WS_TICKET_TTL_SECONDS]
    for t in expired:
        _WS_PENDING_TICKETS.pop(t, None)
    await safe_set(
        _WS_TICKET_PREFIX + ticket,
        str(user_id),
        timeout=_WS_TICKET_TTL_SECONDS,
        context="WebSocket认证票据",
    )
    _WS_PENDING_TICKETS[ticket] = (user_id, now)
    return ticket


async def _consume_ws_ticket(ticket: str) -> int | None:
    from fastapi_app.core.redis_wrapper import safe_delete, safe_get

    if not ticket:
        return None

    entry = _WS_PENDING_TICKETS.pop(ticket, None)
    if entry is not None:
        user_id, issued_at = entry
        # 进程内票据同样遵守 30s TTL（与 Redis 侧一致）——超龄一律作废
        if time.monotonic() - issued_at > _WS_TICKET_TTL_SECONDS:
            await safe_delete(_WS_TICKET_PREFIX + ticket, context="WebSocket认证票据")
            return None
        await safe_delete(_WS_TICKET_PREFIX + ticket, context="WebSocket认证票据")
        return user_id

    value = await safe_get(_WS_TICKET_PREFIX + ticket, context="WebSocket认证票据")
    if value is None:
        return None
    try:
        user_id = int(value)
    except (TypeError, ValueError):
        return None
    await safe_delete(_WS_TICKET_PREFIX + ticket, context="WebSocket认证票据")
    return user_id


def _origin_allowed(origin: str | None) -> bool:
    if not origin:
        return "*" in settings.ALLOWED_HOSTS
    try:
        host = urlparse(origin).hostname
        if not host:
            return False
        for allowed in settings.ALLOWED_HOSTS:
            if allowed == "*":
                return True
            if allowed.startswith("*.") and host.endswith(allowed[1:]):
                return True
            if host == allowed:
                return True
        return bool(settings.FASTAPI_DEBUG)
    except (ValueError, TypeError):
        return False


def _safe_disconnect(manager, websocket: WebSocket, user_id: int) -> None:
    try:
        manager.disconnect(websocket, user_id)
    except (KeyError, ValueError) as e:
        logger.warning("WebSocket disconnect 连接未注册: user_id=%s, %s", user_id, e)


async def _authenticate(websocket: WebSocket) -> tuple[int | None, str | None]:
    """票据 → Cookie → 首条消息三级认证。

    返回 (user_id, pending_message)。user_id None = 未认证（调用方 close 4001）；
    pending_message 是首条非认证消息（进入消息循环后补处理，如 ping）。
    认证流程中连接自身的异常（如 HTTPException）不向上传播——在此消费并返回 None。
    """
    ticket = websocket.query_params.get("ticket")
    user_id = await _consume_ws_ticket(ticket) if ticket else None

    if not user_id:
        user_id, _closed = await _auth_via_cookie(websocket)
        if _closed:
            return None, None

    pending_message: str | None = None
    if not user_id:
        user_id, pending_message = await _auth_via_first_message(websocket)

    return user_id, pending_message


async def _auth_via_cookie(websocket: WebSocket) -> tuple[int | None, bool]:
    """Cookie JWT 认证。返回 (user_id, 是否已 close 连接)。"""
    cookie_token = websocket.cookies.get("access_token")
    if not cookie_token:
        return None, False
    try:
        from fastapi_app.core.deps import _decode_jwt_token, is_token_revoked
        # expected_type='access'：与 HTTP 侧（deps.py 的三处解码）同口径。
        # 不传时 refresh token（寿命按 REFRESH_TOKEN_EXPIRE_DAYS，远长于 access）
        # 也能直接认证 WebSocket，扩大了凭据的可用面。
        payload = _decode_jwt_token(cookie_token, expected_type='access')
        jti = payload.get("jti")
        if jti and await is_token_revoked(jti):
            logger.warning("WebSocket Cookie认证失败: token已撤销")
            await websocket.close(code=4001, reason="Token revoked")
            return None, True
        uid = payload.get("sub")
        if uid:
            return int(uid), False
    except (ValueError, TypeError) as e:
        logger.warning("WebSocket Cookie认证失败: %s | exc_type=%s", e, type(e).__name__)
    except Exception as e:  # 认证流程异常（如 HTTPException）不应中断连接建立  # broad-except: WebSocket 连接容错，异常时关闭连接
        logger.warning("WebSocket Cookie认证异常: exc_type=%s msg=%s", type(e).__name__, e)
    return None, False


async def _auth_via_first_message(websocket: WebSocket) -> tuple[int | None, str | None]:
    """首条消息认证。返回 (user_id, 非认证消息原样回传)。"""
    try:
        initial_data = await asyncio.wait_for(
            websocket.receive_text(), timeout=_WS_AUTH_TIMEOUT
        )
    except TimeoutError:
        logger.warning("WebSocket等待认证消息超时")
        return None, None

    try:
        msg: Any = _json.loads(initial_data)
        if msg.get("type") == "auth" and msg.get("token"):
            ticket_user_id = await _consume_ws_ticket(str(msg["token"]))
            if ticket_user_id is not None:
                return ticket_user_id, None
            from fastapi_app.core.deps import _decode_jwt_token, is_token_revoked
            # expected_type='access'：同 HTTP 侧，禁止用 refresh token 认证
            payload = _decode_jwt_token(msg["token"], expected_type='access')
            jti = payload.get("jti")
            if jti and await is_token_revoked(jti):
                logger.warning("WebSocket首条消息认证失败: token已撤销")
            else:
                uid = payload.get("sub")
                if uid:
                    return int(uid), None
        else:
            return None, initial_data
    except (ValueError, TypeError, _json.JSONDecodeError) as e:
        logger.warning("WebSocket首条消息认证失败: %s", e)
        return None, initial_data
    return None, None


def _engine_or_none():
    """引擎在模块导入时即初始化（fastapi_app/core/database.py:149），此处收窄 Optional。"""
    engine = async_engine
    assert engine is not None  # noqa: S101
    return engine


async def _verify_user_active(user_id: int) -> bool | None:
    """查询用户有效状态。True=有效 False=无效 None=查询失败（容错放行）。"""
    engine = _engine_or_none()
    async with engine.connect() as conn:
        try:
            result = await conn.execute(
                ws_select(WSUser.id, WSUser.status).where(WSUser.id == user_id)
            )
            ws_user = result.first()
        except (OperationalError, DisconnectionError) as e:
            logger.warning("WebSocket 用户状态查询失败: %s", e)
            return None
    return bool(ws_user and ws_user[1])


def _bump_rate_window(now: float, msg_count: int, msg_window_start: float) -> tuple[int, float, bool]:
    """60s 滑动窗口限频。返回 (新计数, 新窗口起点, 是否超限)。"""
    if now - msg_window_start > 60:
        msg_count = 0
        msg_window_start = now
    msg_count += 1
    return msg_count, msg_window_start, msg_count > _WS_RATE_LIMIT


async def _message_loop(websocket: WebSocket, user_id: int, pending_message: str | None) -> None:
    """心跳 / 限频 / 周期性用户状态复核 / ping-pong 消息循环。

    所有 close+break 路径都在本函数内完成，连接清理由调用方 finally 统一处理。
    """
    msg_count = 0
    msg_window_start = time.monotonic()
    last_verify_time = time.monotonic()

    try:
        if pending_message and pending_message == "ping":
            await websocket.send_text("pong")

        while True:
            try:
                data = await asyncio.wait_for(
                    websocket.receive_text(), timeout=_WS_HEARTBEAT_TIMEOUT
                )
            except TimeoutError:
                logger.info("WebSocket 心跳超时断开: user_id=%s", user_id)
                await websocket.close(code=4008, reason="心跳超时")
                break
            now = time.monotonic()

            msg_count, msg_window_start, over_limit = _bump_rate_window(
                now, msg_count, msg_window_start
            )
            if over_limit:
                logger.warning("WebSocket 消息频率超限: user_id=%s", user_id)
                await websocket.close(code=4008, reason="消息频率超限")
                break

            # Periodic user active verification
            if now - last_verify_time > _WS_VERIFY_INTERVAL:
                last_verify_time = now
                active = await _verify_user_active(user_id)
                if active is False:
                    await websocket.close(code=4003, reason="用户已被禁用")
                    break
                # None = 查询失败，容错放行（与原行内 except 路径一致）

            if data == "ping":
                await websocket.send_text("pong")
    except WebSocketDisconnect:
        pass  # 断开清理统一走 finally
    except RuntimeError:
        logger.warning("WebSocket 连接异常断开: user_id=%s", user_id, exc_info=False)


def register_websocket(app: FastAPI) -> None:

    @app.websocket("/ws/notifications")
    async def websocket_notifications(websocket: WebSocket):
        origin = websocket.headers.get("origin")
        if not _origin_allowed(origin):
            logger.warning("WebSocket Origin 校验失败: %s", origin)
            await websocket.close(code=4003, reason="Origin not allowed")
            return

        await websocket.accept()

        user_id, pending_message = await _authenticate(websocket)
        if user_id is None:
            # Cookie 撤销路径已自行 close；其余未认证路径在此统一 close。
            # 已断开时 close 会抛——与原实现的隐式容错等价，这里显式 suppress。
            with contextlib.suppress(Exception):
                await websocket.close(code=4001, reason="未认证")
            return

        active = await _verify_user_active(user_id)
        if active is None:
            await websocket.close(code=4503, reason="服务暂时不可用")
            return
        if not active:
            await websocket.close(code=4001, reason="用户不存在或已禁用")
            return

        from fastapi_app.services.notification_service import manager
        manager.connect_existing(websocket, int(user_id))

        try:
            await _message_loop(websocket, int(user_id), pending_message)
        finally:
            # 第八轮审计：心跳超时/频率超限/用户禁用三条路径都是 close 后 `break`（正常退出
            # try），此前 _safe_disconnect 只在 except 里 → 这些路径不清连接，socket 永久留在
            # manager.active_connections。改到 finally 覆盖所有出口。
            _safe_disconnect(manager, websocket, int(user_id))
