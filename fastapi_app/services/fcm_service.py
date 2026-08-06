"""
FCM 推送服务

封装 Firebase Cloud Messaging 推送功能，支持：
- 发送到指定设备令牌
- 发送到主题（topic）
- 发送到指定用户（查询用户设备令牌）

所有方法均为 fire-and-forget，失败仅记录日志不影响业务流程。
同步 Firebase 调用通过 asyncio.to_thread() 包装，避免阻塞事件循环。
"""
import asyncio
import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from fastapi_app.core.circuit_breaker import CircuitBreakerOpenError, get_breaker

logger = logging.getLogger(__name__)

_fcm_initialized = False

FCM_MULTICAST_LIMIT = 500


def _ensure_fcm() -> bool:
    """延迟初始化 Firebase Admin SDK"""
    global _fcm_initialized
    if _fcm_initialized:
        return True

    try:
        import firebase_admin
        from firebase_admin import credentials

        if firebase_admin._apps:
            _fcm_initialized = True
            return True

        from fastapi_app.core.config import settings
        if not settings.FCM_ENABLED or not settings.FCM_SERVICE_ACCOUNT_PATH:
            logger.debug("FCM 未启用或未配置服务账号路径")
            return False

        cred = credentials.Certificate(settings.FCM_SERVICE_ACCOUNT_PATH)
        firebase_admin.initialize_app(cred)
        _fcm_initialized = True
        logger.info("Firebase Admin SDK 初始化成功")
        return True
    except ImportError:
        logger.warning("firebase_admin 未安装，FCM 推送不可用")
        return False
    except Exception as e:  # defensive: FCM初始化失败时应禁用推送服务
        logger.error("Firebase Admin SDK 初始化失败: %s", e)
        return False


def _send_sync(message) -> str:
    """同步发送单条 FCM 消息（在线程中运行）"""
    from firebase_admin import messaging
    # 设置超时避免 Google 服务慢响应时阻塞线程池
    return messaging.send(message, timeout=10)


def _send_multicast_sync(message):
    """同步发送 FCM 批量消息（在线程中运行）"""
    from firebase_admin import messaging
    return messaging.send_each_for_multicast(message, timeout=15)


async def send_to_device(token: str, title: str, body: str, data: dict[str, Any] | None = None):
    """发送 FCM 推送到指定设备令牌"""
    if not _ensure_fcm():
        return
    try:
        from firebase_admin import messaging

        message = messaging.Message(
            notification=messaging.Notification(title=title, body=body),
            data={k: str(v) for k, v in (data or {}).items()},
            token=token,
        )

        # 通过熔断器保护 FCM 调用，失败计数达到阈值后快速失败
        breaker = get_breaker("fcm_push")

        async def _do_send() -> None:
            await asyncio.to_thread(_send_sync, message)

        await breaker.call(_do_send)
        logger.debug("FCM 推送已发送到设备: %s", token[:20])
    except CircuitBreakerOpenError as e:
        logger.warning("FCM 设备推送被熔断器拦截: %s", e)
    except Exception as e:  # defensive: FCM单设备推送失败不影响业务流程
        logger.warning("FCM 设备推送失败: %s", e)


async def send_to_topic(topic: str, title: str, body: str, data: dict[str, Any] | None = None):
    """发送 FCM 推送到指定主题"""
    if not _ensure_fcm():
        return
    try:
        from firebase_admin import messaging

        message = messaging.Message(
            notification=messaging.Notification(title=title, body=body),
            data={k: str(v) for k, v in (data or {}).items()},
            topic=topic,
        )

        # 通过熔断器保护 FCM 调用，失败计数达到阈值后快速失败
        breaker = get_breaker("fcm_push")

        async def _do_send() -> None:
            await asyncio.to_thread(_send_sync, message)

        await breaker.call(_do_send)
        logger.debug("FCM 推送已发送到主题: %s", topic)
    except CircuitBreakerOpenError as e:
        logger.warning("FCM 主题推送被熔断器拦截: %s", e)
    except Exception as e:  # defensive: FCM主题推送失败不影响业务流程
        logger.warning("FCM 主题推送失败: %s", e)


async def send_to_user(
    db: AsyncSession,
    user_id: int,
    title: str,
    body: str,
    data: dict[str, Any] | None = None,
):
    """发送 FCM 推送到指定用户的所有活跃设备"""
    if not _ensure_fcm():
        return
    try:
        from fastapi_app.shared_models.device_token import DeviceToken

        result = await db.execute(
            select(DeviceToken.token).where(
                DeviceToken.user_id == user_id,
                DeviceToken.is_active.is_(True),
            )
        )
        tokens = list(result.scalars().all())
        if not tokens:
            logger.debug("用户 %s 无活跃设备令牌，跳过 FCM 推送", user_id)
            return

        from firebase_admin import messaging

        breaker = get_breaker("fcm_push")
        for i in range(0, len(tokens), FCM_MULTICAST_LIMIT):
            batch = tokens[i:i + FCM_MULTICAST_LIMIT]
            msg = messaging.MulticastMessage(
                notification=messaging.Notification(title=title, body=body),
                data={k: str(v) for k, v in (data or {}).items()},
                tokens=batch,
            )

            async def _do_send_multicast(_msg=msg) -> Any:
                return await asyncio.to_thread(_send_multicast_sync, _msg)

            response = await breaker.call(_do_send_multicast)
            logger.debug("FCM 用户推送批次 %d: 成功=%d, 失败=%d",
                         i // FCM_MULTICAST_LIMIT, response.success_count, response.failure_count)
    except CircuitBreakerOpenError as e:
        logger.warning("FCM 用户推送被熔断器拦截(user_id=%s): %s", user_id, e)
    except Exception as e:  # defensive: FCM按用户推送失败不影响业务流程
        logger.warning("FCM 用户推送失败(user_id=%s): %s", user_id, e)


async def send_to_all_users(
    db: AsyncSession,
    title: str,
    body: str,
    data: dict[str, Any] | None = None,
):
    """发送 FCM 推送到所有活跃设备"""
    if not _ensure_fcm():
        return
    try:
        from fastapi_app.shared_models.device_token import DeviceToken

        result = await db.execute(
            select(DeviceToken.token).where(DeviceToken.is_active.is_(True))
        )
        tokens = list(result.scalars().all())
        if not tokens:
            logger.debug("无活跃设备令牌，跳过 FCM 推送")
            return

        from firebase_admin import messaging

        breaker = get_breaker("fcm_push")
        total_success = 0
        total_failure = 0
        for i in range(0, len(tokens), FCM_MULTICAST_LIMIT):
            batch = tokens[i:i + FCM_MULTICAST_LIMIT]
            msg = messaging.MulticastMessage(
                notification=messaging.Notification(title=title, body=body),
                data={k: str(v) for k, v in (data or {}).items()},
                tokens=batch,
            )

            async def _do_send_multicast(_msg=msg) -> Any:
                return await asyncio.to_thread(_send_multicast_sync, _msg)

            response = await breaker.call(_do_send_multicast)
            total_success += response.success_count
            total_failure += response.failure_count
        logger.debug("FCM 批量推送完成: 成功=%d, 失败=%d", total_success, total_failure)
    except CircuitBreakerOpenError as e:
        logger.warning("FCM 全量推送被熔断器拦截: %s", e)
    except Exception as e:  # defensive: FCM全量推送失败不影响业务流程
        logger.warning("FCM 全量推送失败: %s", e)
