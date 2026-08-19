"""
领域事件总线

跨域通信通过发布/订阅模式，解耦领域模块之间的直接依赖。
事件通过Redis Pub/Sub实现异步传播，支持进程内同步和跨进程异步两种模式。
"""
import asyncio
import json
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any

logger = logging.getLogger(__name__)


class DomainEventType(StrEnum):
    ORDER_CREATED = 'order.created'
    ORDER_STATUS_CHANGED = 'order.status_changed'
    ORDER_DELETED = 'order.deleted'
    STOCK_IN_CREATED = 'stock_in.created'
    STOCK_OUT_CREATED = 'stock_out.created'
    STOCK_OUT_UPDATED = 'stock_out.updated'
    STOCK_OUT_DELETED = 'stock_out.deleted'
    STOCK_RETURN_CREATED = 'stock_return.created'
    STOCK_RETURN_DELETED = 'stock_return.deleted'
    PRODUCT_UPDATED = 'product.updated'
    PURCHASE_PLAN_UPDATED = 'purchase_plan.updated'
    APPROVAL_DECISION = 'approval.decision'
    BACKUP_COMPLETED = 'backup.completed'
    USER_PERMISSION_CHANGED = 'user.permission_changed'


@dataclass
class DomainEvent:
    event_type: DomainEventType
    domain: str
    payload: dict[str, Any] = field(default_factory=dict)
    event_id: str = field(default_factory=lambda: '')
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())

    def __post_init__(self):
        if not self.event_id:
            import uuid
            self.event_id = uuid.uuid4().hex[:12]

    def to_dict(self) -> dict:
        return {
            'event_type': self.event_type.value,
            'domain': self.domain,
            'payload': self.payload,
            'event_id': self.event_id,
            'timestamp': self.timestamp,
        }

    @classmethod
    def from_dict(cls, data: dict) -> 'DomainEvent':
        return cls(
            event_type=DomainEventType(data['event_type']),
            domain=data['domain'],
            payload=data.get('payload', {}),
            event_id=data.get('event_id', ''),
            timestamp=data.get('timestamp', ''),
        )


_subscribers: dict[DomainEventType, list[Callable]] = {}


def subscribe(event_type: DomainEventType, handler: Callable):
    """订阅领域事件（进程内同步调用）"""
    if event_type not in _subscribers:
        _subscribers[event_type] = []
    _subscribers[event_type].append(handler)
    logger.debug('领域事件订阅: %s -> %s', event_type.value, handler.__name__)


async def publish(event: DomainEvent):
    """发布领域事件

    1. 进程内同步通知所有订阅者
    2. 异步广播到Redis Pub/Sub（跨Worker进程通信）
    """
    handlers = list(_subscribers.get(event.event_type, []))
    for handler in handlers:
        try:
            result = handler(event)
            if hasattr(result, '__await__'):
                await result
        except Exception as e:  # defensive: 单个 handler 失败不能影响其他 handler
            logger.error(
                '领域事件处理失败: event=%s handler=%s error=%s',
                event.event_type.value, handler.__name__, e,
            )

    try:
        from fastapi_app.core.redis_wrapper import safe_publish
        await safe_publish(
            'domain_events',
            json.dumps(event.to_dict(), ensure_ascii=False, default=str),
            context="领域事件广播",
        )
    except Exception as e:  # defensive: Redis 广播失败不影响进程内事件处理
        logger.debug('领域事件Redis广播失败（可忽略）: %s', e)


async def publish_with_retry(event: DomainEvent, max_retries: int = 1, delay: float = 0.5) -> None:
    """发布领域事件，失败时重试一次。

    重试仍失败则升级为 ERROR 日志并记录完整事件载荷，便于人工恢复。
    主操作不受影响（仍不抛出）。
    """
    last_error: Exception | None = None
    for attempt in range(max_retries + 1):
        try:
            await publish(event)
            return
        except Exception as e:  # defensive: 重试期间捕获所有异常
            last_error = e
            if attempt < max_retries:
                await asyncio.sleep(delay)
    # 所有重试均失败：记录 ERROR 级别日志含完整事件，便于人工恢复
    logger.error(
        '领域事件发布失败（已重试 %d 次）: event=%s payload=%s error=%s',
        max_retries,
        event.event_type.value,
        json.dumps(event.payload, ensure_ascii=False, default=str),
        last_error,
        exc_info=True,
    )


async def start_event_listener():
    """启动Redis领域事件监听器（跨进程事件接收）"""
    from fastapi_app.core.redis_wrapper import get_client
    while True:
        pubsub = None
        try:
            client = get_client()
            if not client:
                await asyncio.sleep(5)
                continue
            pubsub = client.pubsub()
            await pubsub.subscribe('domain_events')
            logger.info('领域事件Redis监听器已启动')
            async for message in pubsub.listen():
                if message['type'] != 'message':
                    continue
                try:
                    event = DomainEvent.from_dict(json.loads(message['data']))
                    handlers = list(_subscribers.get(event.event_type, []))
                    for handler in handlers:
                        try:
                            result = handler(event)
                            if hasattr(result, '__await__'):
                                await result
                        except Exception as e:  # defensive: 单个 handler 失败不能影响其他 handler
                            logger.error('跨进程领域事件处理失败: %s', e)
                except Exception as e:  # defensive: 单条消息解析失败不能中断监听器
                    logger.error('领域事件消息解析失败: %s', e)
        except Exception as e:  # defensive: 监听器异常后自动重连
            logger.warning('领域事件监听器异常: %s', e)
        finally:
            if pubsub:
                try:
                    await pubsub.unsubscribe()
                    await pubsub.aclose()
                except Exception:  # defensive: 清理失败不影响重连  # noqa: S110  # nosec B110
                    pass  # defensive: 异常静默处理,不影响主流程
        logger.info('领域事件监听器将在5秒后重连...')
        await asyncio.sleep(5)
