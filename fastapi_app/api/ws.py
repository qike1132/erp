"""
WebSocket 实时通知端点

从 main.py 提取。支持两种认证方式：
1. Cookie JWT（浏览器自动携带）
2. 首条消息认证（移动端/API客户端发送 {"type":"auth","token":"xxx"}）

安全机制：
- 连接建立前校验 Origin 白名单（防跨站劫持）
- 建立连接后进行 Cookie/消息 JWT 认证
- disconnect 安全处理未注册连接（防二次异常）
"""

import asyncio
import json as _json
import logging
from urllib.parse import urlparse

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from sqlalchemy import select as ws_select
from sqlalchemy.exc import DisconnectionError, OperationalError

from fastapi_app.core.config import settings
from fastapi_app.core.database import async_engine
from fastapi_app.shared_models import User as WSUser

logger = logging.getLogger(__name__)

_WS_AUTH_TIMEOUT = 5


def _origin_allowed(origin: str | None) -> bool:
    if not origin:
        if "*" in settings.ALLOWED_HOSTS:
            return True
        return False
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
        if settings.FASTAPI_DEBUG:
            return True
        return False
    except (ValueError, TypeError):
        return False


def _safe_disconnect(manager, websocket: WebSocket, user_id: int) -> None:
    try:
        manager.disconnect(websocket, user_id)
    except (KeyError, ValueError) as e:
        logger.warning("WebSocket disconnect 连接未注册: user_id=%s, %s", user_id, e)


def register_websocket(app: FastAPI) -> None:

    @app.websocket("/ws/notifications")
    async def websocket_notifications(websocket: WebSocket):
        origin = websocket.headers.get("origin")
        if not _origin_allowed(origin):
            logger.warning("WebSocket Origin 校验失败: %s", origin)
            await websocket.close(code=4003, reason="Origin not allowed")
            return

        await websocket.accept()

        user_id = None
        pending_message = None

        cookie_token = websocket.cookies.get("access_token")
        # region debug-point DBG-1 cookie-auth-trace
        _dbg_cookie_len = len(cookie_token) if cookie_token else 0
        logger.info("[DBG-1] WebSocket auth start: cookie_present=%s cookie_len=%s",
                    bool(cookie_token), _dbg_cookie_len)
        # endregion
        if cookie_token:
            try:
                from fastapi_app.core.deps import _decode_jwt_token, is_token_revoked
                payload = _decode_jwt_token(cookie_token)
                jti = payload.get("jti")
                if jti and await is_token_revoked(jti):
                    logger.warning("WebSocket Cookie认证失败: token已撤销")
                    await websocket.close(code=4001, reason="Token revoked")
                    return
                else:
                    uid = payload.get("sub")
                    if uid:
                        user_id = int(uid)
                # region debug-point DBG-2 cookie-auth-success
                logger.info("[DBG-2] Cookie auth path done: user_id_set=%s uid=%s",
                            user_id is not None, uid)
                # endregion
            except (ValueError, TypeError) as e:
                logger.warning("WebSocket Cookie认证失败: %s | exc_type=%s", e, type(e).__name__)
            except Exception as e:  # noqa: BLE001  # debug-only: 捕获 HTTPException 等未处理异常以确认假设 H4
                logger.error("[DBG-2] Cookie auth UNCAUGHT exception: exc_type=%s msg=%s",
                             type(e).__name__, e)

        # region debug-point DBG-3 message-auth-entry
        logger.info("[DBG-3] Entering message-auth path: user_id_set=%s", user_id is not None)
        # endregion
        if not user_id:
            try:
                initial_data = await asyncio.wait_for(
                    websocket.receive_text(), timeout=_WS_AUTH_TIMEOUT
                )
                try:
                    msg = _json.loads(initial_data)
                    if msg.get("type") == "auth" and msg.get("token"):
                        from fastapi_app.core.deps import _decode_jwt_token, is_token_revoked
                        payload = _decode_jwt_token(msg["token"])
                        jti = payload.get("jti")
                        if jti and await is_token_revoked(jti):
                            logger.warning("WebSocket首条消息认证失败: token已撤销")
                        else:
                            uid = payload.get("sub")
                            if uid:
                                user_id = int(uid)
                    else:
                        pending_message = initial_data
                except (ValueError, TypeError, _json.JSONDecodeError) as e:
                    logger.warning("WebSocket首条消息认证失败: %s", e)
                    pending_message = initial_data
            except TimeoutError:
                logger.warning("WebSocket等待认证消息超时")

        # region debug-point DBG-4 final-auth-result
        logger.info("[DBG-4] Auth complete: user_id_set=%s final_uid=%s",
                    user_id is not None, user_id)
        # endregion
        if not user_id:
            await websocket.close(code=4001, reason="未认证")
            return

        async with async_engine.connect() as conn:
            try:
                result = await conn.execute(
                    ws_select(WSUser.id, WSUser.status).where(WSUser.id == user_id)
                )
                ws_user = result.first()
            except (OperationalError, DisconnectionError) as e:
                logger.warning("WebSocket 用户状态查询失败: %s", e)
                await websocket.close(code=4503, reason="服务暂时不可用")
                return

        if not ws_user or not ws_user[1]:
            await websocket.close(code=4001, reason="用户不存在或已禁用")
            return

        from fastapi_app.services.notification_service import manager
        manager.connect_existing(websocket, int(user_id))

        import time
        msg_count = 0
        msg_window_start = time.monotonic()
        last_verify_time = time.monotonic()
        last_recv_time = time.monotonic()
        MSG_RATE_LIMIT = 30  # max messages per minute
        VERIFY_INTERVAL = 60  # verify user active every 60s
        HEARTBEAT_INTERVAL = 30  # 服务端主动 ping 间隔（秒）
        HEARTBEAT_TIMEOUT = 60  # 60s 无响应则断开（stale 连接清理）

        try:
            if pending_message and pending_message == "ping":
                await websocket.send_text("pong")

            while True:
                try:
                    data = await asyncio.wait_for(
                        websocket.receive_text(), timeout=HEARTBEAT_TIMEOUT
                    )
                except TimeoutError:
                    logger.info("WebSocket 心跳超时断开: user_id=%s", user_id)
                    await websocket.close(code=4008, reason="心跳超时")
                    break
                now = time.monotonic()
                last_recv_time = now

                # Rate limiting
                if now - msg_window_start > 60:
                    msg_count = 0
                    msg_window_start = now
                msg_count += 1
                if msg_count > MSG_RATE_LIMIT:
                    logger.warning("WebSocket 消息频率超限: user_id=%s", user_id)
                    await websocket.close(code=4008, reason="消息频率超限")
                    break

                # Periodic user active verification
                if now - last_verify_time > VERIFY_INTERVAL:
                    last_verify_time = now
                    async with async_engine.connect() as conn:
                        try:
                            result = await conn.execute(
                                ws_select(WSUser.status).where(WSUser.id == user_id)
                            )
                            check_user = result.first()
                            if not check_user or not check_user[0]:
                                await websocket.close(code=4003, reason="用户已被禁用")
                                break
                        except (OperationalError, DisconnectionError):
                            logger.warning("WebSocket 用户状态复核查询失败")

                if data == "ping":
                    await websocket.send_text("pong")
        except WebSocketDisconnect:
            _safe_disconnect(manager, websocket, int(user_id))
        except RuntimeError:
            logger.warning("WebSocket 连接异常断开: user_id=%s", user_id, exc_info=False)
            _safe_disconnect(manager, websocket, int(user_id))
