"""事件总线 — 发布/订阅，替代 v6 的裸 queue.Queue + 主线程轮询。

设计：
    - 同步分发（Application 内事件量小，同步保证时序）
    - 订阅者异常隔离：单个订阅者抛异常不影响其他订阅者与发布者
      （审计/日志类订阅绝不能把主流程带崩）
    - 类型过滤：可按事件类型订阅，也可订阅全部
"""

from __future__ import annotations

import logging
from collections import defaultdict
from collections.abc import Callable

from .events import Event

__all__ = ['EventBus', 'Subscriber']

Subscriber = Callable[[Event], None]
_LOGGER = logging.getLogger('server_manager_v8.events')


class EventBus:
    """线程安全的发布/订阅总线。"""

    def __init__(self) -> None:
        self._subs: dict[type[Event], list[Subscriber]] = defaultdict(list)
        self._any: list[Subscriber] = []
        self._lock = __import__('threading').Lock()

    def subscribe(self, handler: Subscriber, event_type: type[Event] | None = None) -> None:
        """注册订阅者。event_type 为空 = 订阅全部事件。"""
        with self._lock:
            if event_type is None:
                self._any.append(handler)
            else:
                self._subs[event_type].append(handler)

    def publish(self, event: Event) -> None:
        """发布事件。订阅者异常隔离：记录日志，绝不向调用方抛。"""
        with self._lock:
            typed = list(self._subs.get(type(event), ()))
            any_subs = list(self._any)
        for handler in typed + any_subs:
            try:
                handler(event)
            except Exception:
                _LOGGER.exception('事件订阅者处理 %s 失败', type(event).__name__)

    @property
    def subscriber_count(self) -> int:
        with self._lock:
            return len(self._any) + sum(len(v) for v in self._subs.values())
