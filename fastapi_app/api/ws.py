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
_authenticate / _load_ws_user / _message_loop 三个单元，主协程只保留
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
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from fastapi_app.core.config import settings
from fastapi_app.core.database import get_async_db_context
from fastapi_app.shared_models import Permission
from fastapi_app.shared_models import User as WSUser

logger = logging.getLogger(__name__)

_WS_AUTH_TIMEOUT = 5
_WS_TICKET_TTL_SECONDS = 30
_WS_TICKET_PREFIX = "ws:auth_ticket:"
_WS_HEARTBEAT_INTERVAL_SECONDS = 30
_WS_HEARTBEAT_TIMEOUT = 60
_WS_RATE_LIMIT = 30
_WS_VERIFY_INTERVAL = 60

# 进程内票据表：value = (user_id, issued_monotonic, 原会话 jti/exp)。
# 票据只是短期握手凭据，长连接必须继承原会话的撤销/过期语义。
_WS_PENDING_TICKETS: dict[str, tuple[int, float, dict]] = {}


def _clean_auth_payload(payload: dict | None) -> dict:
    if not isinstance(payload, dict):
        return {}
    return {key: payload[key] for key in ('jti', 'exp') if payload.get(key) is not None}


async def _issue_ws_ticket(user_id: int, auth_payload: dict | None = None) -> str:
    from fastapi_app.core.redis_wrapper import safe_set

    ticket = secrets.token_urlsafe(32)
    now = time.monotonic()
    auth = _clean_auth_payload(auth_payload)
    expired = [t for t, entry in _WS_PENDING_TICKETS.items() if now - entry[1] > _WS_TICKET_TTL_SECONDS]
    for t in expired:
        _WS_PENDING_TICKETS.pop(t, None)
    await safe_set(
        _WS_TICKET_PREFIX + ticket,
        _json.dumps({'user_id': user_id, 'auth': auth}),
        timeout=_WS_TICKET_TTL_SECONDS,
        context="WebSocket认证票据",
    )
    _WS_PENDING_TICKETS[ticket] = (user_id, now, auth)
    return ticket


async def _consume_ws_ticket(ticket: str) -> tuple[int, dict] | None:
    from fastapi_app.core.redis_wrapper import safe_delete, safe_get

    if not ticket:
        return None

    entry = _WS_PENDING_TICKETS.pop(ticket, None)
    if entry is not None:
        user_id, issued_at = entry[0], entry[1]
        auth = entry[2] if len(entry) > 2 else {}
        if time.monotonic() - issued_at > _WS_TICKET_TTL_SECONDS:
            await safe_delete(_WS_TICKET_PREFIX + ticket, context="WebSocket认证票据")
            return None
        await safe_delete(_WS_TICKET_PREFIX + ticket, context="WebSocket认证票据")
        return user_id, auth

    value = await safe_get(_WS_TICKET_PREFIX + ticket, context="WebSocket认证票据")
    if value is None:
        return None
    try:
        if isinstance(value, str) and value.startswith('{'):
            parsed = _json.loads(value)
            user_id = int(parsed['user_id'])
            auth = _clean_auth_payload(parsed.get('auth'))
        else:
            # 兼容滚动发布前 30 秒内的旧票据；新票据必带 auth。
            user_id, auth = int(value), {}
    except (TypeError, ValueError, KeyError, _json.JSONDecodeError):
        return None
    await safe_delete(_WS_TICKET_PREFIX + ticket, context="WebSocket认证票据")
    return user_id, auth


def _origin_allowed(origin: str | None) -> bool:
    """Origin 白名单判定。

    L4（2026-10-31 评审）——本函数的两个「宽松回退」依赖 core/config.py 的生产
    启动闸门兜底，重构闸门时必须连带核对本处：
    1. `origin 为 None → "*" in ALLOWED_HOSTS`：生产闸门（config.py Settings.__init__
       「ALLOWED_HOSTS 必须显式配置、禁 *」）保证生产恒为 False，仅开发环境可放行；
    2. `异常 Origin → bool(FASTAPI_DEBUG)`：生产闸门（config.py「生产禁止
       FASTAPI_DEBUG=true」）保证生产恒为 False。
    两个闸门任一被移除，本函数就会在生产漏放无 Origin/异常 Origin 的握手。
    """
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


async def _authenticate(websocket: WebSocket) -> tuple[int | None, str | None, dict]:
    """票据 → Cookie → 首条消息认证，并保留原会话 jti/exp。"""
    auth_payload: dict = {}
    ticket = websocket.query_params.get("ticket")
    ticket_result = await _consume_ws_ticket(ticket) if ticket else None
    user_id = ticket_result[0] if ticket_result else None
    if ticket_result:
        auth_payload = ticket_result[1]

    if not user_id:
        user_id, closed, auth_payload = await _auth_via_cookie(websocket)
        if closed:
            return None, None, {}

    pending_message: str | None = None
    if not user_id:
        user_id, pending_message, auth_payload = await _auth_via_first_message(websocket)

    return user_id, pending_message, auth_payload


async def _auth_via_cookie(websocket: WebSocket) -> tuple[int | None, bool, dict]:
    """Cookie JWT 认证。返回 (user_id, 是否已 close, 原会话上下文)。"""
    cookie_token = websocket.cookies.get("access_token")
    if not cookie_token:
        return None, False, {}
    try:
        from fastapi_app.core.deps import _decode_jwt_token, is_token_revoked
        payload = _decode_jwt_token(cookie_token, expected_type='access')
        jti = payload.get("jti")
        if jti and await is_token_revoked(jti):
            logger.warning("WebSocket Cookie认证失败: token已撤销")
            await websocket.close(code=4001, reason="Token revoked")
            return None, True, {}
        uid = payload.get("sub")
        if uid:
            return int(uid), False, _clean_auth_payload(payload)
    except (ValueError, TypeError) as e:
        logger.warning("WebSocket Cookie认证失败: %s | exc_type=%s", e, type(e).__name__)
    except Exception as e:  # 认证流程异常（如 HTTPException）不应中断连接建立  # broad-except: WebSocket 连接容错，异常时关闭连接
        logger.warning("WebSocket Cookie认证异常: exc_type=%s msg=%s", type(e).__name__, e)
    return None, False, {}


async def _auth_via_first_message(websocket: WebSocket) -> tuple[int | None, str | None, dict]:
    """首条消息认证。返回 (user_id, 非认证消息, 原会话上下文)。"""
    try:
        initial_data = await asyncio.wait_for(
            websocket.receive_text(), timeout=_WS_AUTH_TIMEOUT
        )
    except TimeoutError:
        logger.warning("WebSocket等待认证消息超时")
        return None, None, {}

    try:
        msg: Any = _json.loads(initial_data)
        if msg.get("type") == "auth" and msg.get("token"):
            ticket_result = await _consume_ws_ticket(str(msg["token"]))
            if ticket_result is not None:
                return ticket_result[0], None, ticket_result[1]
            from fastapi_app.core.deps import _decode_jwt_token, is_token_revoked
            payload = _decode_jwt_token(msg["token"], expected_type='access')
            jti = payload.get("jti")
            if jti and await is_token_revoked(jti):
                logger.warning("WebSocket首条消息认证失败: token已撤销")
            else:
                uid = payload.get("sub")
                if uid:
                    return int(uid), None, _clean_auth_payload(payload)
        else:
            return None, initial_data, {}
    except (ValueError, TypeError, _json.JSONDecodeError) as e:
        logger.warning("WebSocket首条消息认证失败: %s", e)
        return None, initial_data, {}
    return None, None, {}


async def _token_auth_valid(payload: dict) -> bool:
    """长连接周期复核：原会话过期或撤销后立即失效。"""
    if not payload:
        return True
    try:
        exp = payload.get('exp')
        if exp is not None and time.time() >= float(exp):
            return False
    except (TypeError, ValueError):
        return False
    jti = payload.get('jti')
    if jti:
        from fastapi_app.core.deps import is_token_revoked
        if await is_token_revoked(jti):
            return False
    return True


async def _load_ws_user_from_session(
    db: AsyncSession, user_id: int,
) -> tuple[WSUser | None, bool]:
    """从 ORM 会话取回启用用户与权限；供生产加载和数据库回归共用。"""
    result = await db.execute(
        ws_select(WSUser)
        .options(joinedload(WSUser.permissions).joinedload(Permission.children))
        .where(WSUser.id == user_id)
    )
    user = result.unique().scalar_one_or_none()
    if user is None or not user.status:
        return None, True
    return user, True


async def _load_ws_user(user_id: int) -> tuple[WSUser | None, bool]:
    """一次查询取回启用状态与完整权限，供建连和周期复核共用。"""
    try:
        async with get_async_db_context() as db:
            return await _load_ws_user_from_session(db, user_id)
    except SQLAlchemyError as e:
        logger.warning("WebSocket 用户与权限查询失败: %s", e)
        return None, False


def _bump_rate_window(now: float, msg_count: int, msg_window_start: float) -> tuple[int, float, bool]:
    """60s 滑动窗口限频。返回 (新计数, 新窗口起点, 是否超限)。"""
    if now - msg_window_start > 60:
        msg_count = 0
        msg_window_start = now
    msg_count += 1
    return msg_count, msg_window_start, msg_count > _WS_RATE_LIMIT


async def _message_loop(
    websocket: WebSocket, user_id: int, pending_message: str | None,
    *, manager, auth_payload: dict,
) -> None:
    """心跳、限频及周期性会话/用户/权限复核。

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

            if now - last_verify_time > _WS_VERIFY_INTERVAL:
                last_verify_time = now
                if not await _token_auth_valid(auth_payload):
                    await websocket.close(code=4001, reason="会话已过期或撤销")
                    break
                principal, query_ok = await _load_ws_user(user_id)
                if query_ok and principal is None:
                    await websocket.close(code=4003, reason="用户已被禁用")
                    break
                if principal is not None:
                    manager.update_principal(websocket, principal)
                # 查询失败沿用已验证主体；下次心跳周期继续复核。

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

        user_id, pending_message, auth_payload = await _authenticate(websocket)
        if user_id is None:
            # Cookie 撤销路径已自行 close；其余未认证路径在此统一 close。
            # 已断开时 close 会抛——与原实现的隐式容错等价，这里显式 suppress。
            with contextlib.suppress(Exception):
                await websocket.close(code=4001, reason="未认证")
            return

        if not await _token_auth_valid(auth_payload):
            await websocket.close(code=4001, reason="会话已过期或撤销")
            return
        principal, query_ok = await _load_ws_user(user_id)
        if not query_ok:
            await websocket.close(code=4503, reason="服务暂时不可用")
            return
        if principal is None:
            await websocket.close(code=4001, reason="用户不存在或已禁用")
            return

        from fastapi_app.services.notification_service import manager
        manager.connect_existing(websocket, int(user_id), principal=principal)

        try:
            await _message_loop(
                websocket, int(user_id), pending_message,
                manager=manager, auth_payload=auth_payload,
            )
        finally:
            # 第八轮审计：心跳超时/频率超限/用户禁用三条路径都是 close 后 `break`（正常退出
            # try），此前 _safe_disconnect 只在 except 里 → 这些路径不清连接，socket 永久留在
            # manager.active_connections。改到 finally 覆盖所有出口。
            _safe_disconnect(manager, websocket, int(user_id))
