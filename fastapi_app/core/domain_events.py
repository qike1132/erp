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
from datetime import UTC, datetime
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
    STOCK_RETURN_CANCELLED = 'stock_return.cancelled'
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


async def _dispatch_in_process(event: DomainEvent) -> None:
    """进程内同步通知所有订阅者（单个 handler 失败不影响其它 handler）。"""
    for handler in list(_subscribers.get(event.event_type, [])):
        try:
            result = handler(event)
            if hasattr(result, '__await__'):
                await result
        except Exception as e:  # defensive: 单个 handler 失败不能影响其他 handler
            logger.error(
                '领域事件处理失败: event=%s handler=%s error=%s',
                event.event_type.value, handler.__name__, e,
            )


async def _broadcast(event: DomainEvent) -> bool:
    """广播到 Redis Pub/Sub（跨 worker），返回**是否真的发出**。

    不能用 `safe_publish` 的返回值判断成败：它在 Redis 不可用或发布异常时返回 0 且不抛，
    而 0 同时也可能是"当前无订阅者"，两者无法区分。故这里直接问 `get_client()` ——
    拿不到客户端即视为未发出，这正是调用方需要重试/落死信的情形。
    """
    try:
        from fastapi_app.core.redis_wrapper import get_client
        client = get_client()
        if client is None:
            return False
        await client.publish(
            'domain_events',
            json.dumps(event.to_dict(), ensure_ascii=False, default=str),
        )
        return True
    except Exception as e:  # defensive: 广播失败不影响进程内事件处理
        logger.debug('领域事件Redis广播失败（可忽略）: %s', e)
        return False


def schedule_post_commit_domain_event(session: Any, event: DomainEvent) -> None:
    """注册「事务提交成功后」再发布的领域事件。

    事件订阅者（如 purchase_plan_service 的 FIFO 重算）使用**独立 session** 读库，
    事务提交前发布时读不到未提交的出货行，shipped_qty/plan.status 会按旧数据算错
    并落库。payload 必须在注册前提取为标量（commit 后 session expire，回调里不能
    再访问 ORM 属性）。

    回调由 db_transaction 在 commit 成功后执行；不经 db_transaction 的调用方
    （ARQ 任务、直连会话）注册无人执行，请直接 await publish_with_retry。
    """
    async def _publish() -> None:
        await publish_with_retry(event)

    info = getattr(session, 'info', None)
    if not isinstance(info, dict):
        # 与 schedule_post_commit_invalidation 同款退化：无法挂回调的会话当场发布
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return  # 无事件循环（同步上下文）：无法执行异步发布，只能放弃
        task = loop.create_task(_publish())
        task.add_done_callback(_log_publish_task_exception)
        return
    info.setdefault('post_commit_callbacks', []).append(_publish)


def _log_publish_task_exception(task: 'asyncio.Task[Any]') -> None:
    if task.cancelled():
        return
    exc = task.exception()
    if exc is not None:
        logger.warning('立即执行的领域事件发布回调失败: %s', exc, exc_info=exc)


async def publish(event: DomainEvent) -> bool:
    """发布领域事件

    1. 进程内同步通知所有订阅者
    2. 广播到 Redis Pub/Sub（跨 Worker 进程通信）

    返回广播是否发出。**本函数不抛异常**（进程内 handler 与广播失败都只记日志），
    调用方可以忽略返回值；需要「失败重试 + 死信」的调用方请用 publish_with_retry。
    """
    await _dispatch_in_process(event)
    return await _broadcast(event)


async def publish_with_retry(event: DomainEvent, max_retries: int = 1, delay: float = 0.5) -> None:
    """发布领域事件：进程内 handler 只跑一次，Redis 广播失败时重试。

    重试仍失败则升级为 ERROR 日志并记录完整事件载荷，便于人工恢复。
    主操作不受影响（仍不抛出）。

    注（2026-10-02 修）：本函数此前**整段不可达** —— 它调 `publish()` 并靠异常判断成败，
    而 `publish()` 把广播包在 try/except 里只打 debug 日志、`safe_publish` 自身也吞异常
    返回 0，`await publish(event)` 永不抛 → 重试循环、ERROR 日志、死信落盘从未执行过
    （Redis 故障期间事件静默丢失、死信文件恒空）。现改为看 `_broadcast()` 的**返回值**。
    """
    # 进程内 handler 只跑一次：重试的是广播，不是本进程的订阅者回调
    await _dispatch_in_process(event)

    last_error: Exception | None = None
    for attempt in range(max_retries + 1):
        if await _broadcast(event):
            return
        last_error = RuntimeError('Redis 广播未发出（客户端不可用或发布失败）')
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
    # 最小死信：落盘 JSONL，防止 Redis/持久层持续故障时事件仅存在于滚动日志中被冲掉
    try:
        await asyncio.to_thread(_append_deadletter, event, last_error)
    except Exception:  # defensive: 死信落盘失败不升级（已先有 ERROR 日志）
        logger.debug('领域事件死信落盘失败（可忽略）', exc_info=True)


def _append_deadletter(event: DomainEvent, error: Exception | None) -> None:
    """把发布失败的事件追加到 logs/domain_events_deadletter.jsonl（供人工/脚本重放）。"""
    from pathlib import Path as _Path
    log_dir = _Path(__file__).resolve().parents[2] / 'logs'
    log_dir.mkdir(exist_ok=True)
    record = {
        'ts': datetime.now(UTC).isoformat(),
        'event_type': event.event_type.value,
        'payload': event.payload,
        'error': str(error) if error else None,
    }
    with open(log_dir / 'domain_events_deadletter.jsonl', 'a', encoding='utf-8') as f:
        f.write(json.dumps(record, ensure_ascii=False, default=str) + '\n')


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
