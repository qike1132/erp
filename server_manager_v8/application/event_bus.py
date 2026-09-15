"""类型化事件总线 —— 替代裸 `queue.Queue`。

═══════════════════════════════════════════════════════════════════
为什么不用 queue.Queue
═══════════════════════════════════════════════════════════════════

旧实现的模式是：

    后台线程 → q.put(('log', {...}))  →  主线程 _poll_queue() 每轮取 30 条

这个模式本身没错（跨线程通信必须经由队列），但它把两种职责混在了一起：

    1. **线程安全投递**（queue 的本职）
    2. **事件分发**（谁关心这个事件、该怎么处理）

结果主线程里长出一个巨大的 `if msg_type == 'log': ... elif ...` 分发链，
新增事件类型必须去改那个链。每改一次，主线程的分发逻辑就复杂一分。

本模块把职责 2 抽出来：总线允许**按类型订阅**，投递方不需要知道有谁在听。

═══════════════════════════════════════════════════════════════════
★ 线程模型（关键，必须讲清）
═══════════════════════════════════════════════════════════════════

总线**不自己开线程**，也不做异步投递。`emit()` 是**同步**调用：
在调用者的线程上，依次执行所有匹配的 handler。

这样设计的理由：
    · 投递语义确定（emit 返回时，handler 已全部执行完）—— 便于单测
    · 不需要额外的队列与工作线程，避免「队列积压」这类新问题
    · 旧实现之所以用队列，是因为 Tk 组件必须主线程操作；
      新架构是 WebView，UI 更新走 bridge 推送，同样需要切主线程 ——
      **这个切换由 presentation 层自己的 handler 负责**，不是总线的职责

跨线程安全靠一把 `RLock`：`emit` 与 `subscribe` 可被不同线程并发调用。
但要注意：**handler 本身在 emit 的线程上执行**，若 handler 要碰 UI，
它自己负责切到主线程（presentation 层的 `ThreadSafeBridge` 会做这件事）。

═══════════════════════════════════════════════════════════════════
★ handler 异常隔离：不能一个订阅者炸掉其他订阅者
═══════════════════════════════════════════════════════════════════

如果一个 UI 更新 handler 抛异常，导致「审计 handler 没被调用」——
那就丢失了审计留痕。审计丢一条，整个 4A 链条就断了。

所以每个 handler 单独 try/except，异常收集后：
    · 调用注入的 `on_handler_error` 回调（默认写 stderr）
    · **不重抛**（emit 的语义是「通知」，不是「执行事务」）
    · 但也**不静默**（有回调）

★ 注意一个反直觉之处：`emit()` 返回 `EmitReport` 而不是 None。
  调用方可以据此判断「有没有 handler 出错」，用于测试与诊断。
  这符合项目「显式结果对象」的一贯原则。
"""

from __future__ import annotations

import sys
import threading
from dataclasses import dataclass, field
from typing import Any, Callable

from .events import Event

#: 通配订阅的标记（订阅所有事件）
ALL_EVENTS = '*'

Handler = Callable[[Any], None]
ErrorCallback = Callable[[BaseException, Any], None]


def _default_error_callback(exc: BaseException, event: Any) -> None:
    """默认失败回调：写 stderr。绝不静默。"""
    kind = type(event).__name__
    print(f'[event_bus] handler 处理 {kind} 时异常: '
          f'{type(exc).__name__}: {exc}', file=sys.stderr)


@dataclass(frozen=True)
class EmitReport:
    """一次 `emit()` 的执行报告。"""

    kind: str
    delivered: int = 0
    failed: int = 0
    errors: tuple[tuple[str, str], ...] = ()

    @property
    def ok(self) -> bool:
        return self.failed == 0


@dataclass
class Subscription:
    """一个订阅句柄（可用于取消订阅）。"""

    event_type: type | str
    handler: Handler
    once: bool = False
    fired: bool = False


class EventBus:
    """类型化事件总线。

    用法：
        bus = EventBus()
        sub = bus.subscribe(LogAppended, on_log)
        bus.emit(LogAppended(ts=1.0, text='hello'))
        bus.unsubscribe(sub)
    """

    def __init__(self, *, on_handler_error: ErrorCallback | None = None) -> None:
        self._subs: list[Subscription] = []
        self._lock = threading.RLock()
        self._on_error = on_handler_error or _default_error_callback

    # ── 订阅 ──────────────────────────────────────────────────────

    def subscribe(self, event_type: type | str, handler: Handler, *,
                  once: bool = False) -> Subscription:
        """订阅某类型事件（或 `ALL_EVENTS` 订阅全部）。

        `once=True` 时 handler 只触发一次后自动退订 —— 用于「等某个事件到达」
        这类一次性等待，避免忘记退订造成的内存泄漏。
        """
        if not callable(handler):
            raise TypeError(f'handler 必须可调用，得到 {type(handler).__name__}')

        sub = Subscription(event_type=event_type, handler=handler, once=once)
        with self._lock:
            self._subs.append(sub)
        return sub

    def unsubscribe(self, sub: Subscription) -> bool:
        """取消订阅。返回是否真的移除了（重复取消返回 False）。"""
        with self._lock:
            try:
                self._subs.remove(sub)
                return True
            except ValueError:
                return False

    def clear(self) -> None:
        """移除所有订阅（测试与关闭时用）。"""
        with self._lock:
            self._subs.clear()

    @property
    def subscription_count(self) -> int:
        with self._lock:
            return len(self._subs)

    # ── 发布 ──────────────────────────────────────────────────────

    def emit(self, event: Any) -> EmitReport:
        """同步分发事件给所有匹配的 handler。

        ★ 顺序保证：**按订阅顺序**依次调用。这让「先记审计再更新 UI」
          这类顺序要求可以通过订阅顺序表达，而不需要在 handler 里手工排序。
        """
        kind = type(event)
        kind_name = kind.__name__

        # 先快照订阅列表：handler 内部可能订阅/退订，
        # 直接遍历原列表会 RuntimeError（或漏掉/重复调用）
        with self._lock:
            snapshot = list(self._subs)

        delivered = 0
        errors: list[tuple[str, str]] = []
        to_remove: list[Subscription] = []

        for sub in snapshot:
            if not self._matches(sub, kind, kind_name):
                continue

            try:
                sub.handler(event)
                delivered += 1
            except BaseException as exc:  # noqa: BLE001 —— 隔离：一个炸不能影响其他
                errors.append((kind_name, f'{type(exc).__name__}: {exc}'))
                try:
                    self._on_error(exc, event)
                except Exception:  # noqa: BLE001 —— 错误回调自己炸了也只能吞
                    pass

            if sub.once:
                sub.fired = True
                to_remove.append(sub)

        if to_remove:
            with self._lock:
                for sub in to_remove:
                    try:
                        self._subs.remove(sub)
                    except ValueError:
                        pass

        return EmitReport(
            kind=kind_name,
            delivered=delivered,
            failed=len(errors),
            errors=tuple(errors),
        )

    @staticmethod
    def _matches(sub: Subscription, kind: type, kind_name: str) -> bool:
        """订阅是否匹配该事件。

        匹配规则：
            · `ALL_EVENTS` → 全匹配
            · 订阅的是**类** → 用 isinstance 判断（**支持基类订阅子类事件**）
            · 订阅的是**字符串** → 与事件类名精确比较（兼容按名字订阅的场景）
        """
        if sub.event_type == ALL_EVENTS:
            return True
        if isinstance(sub.event_type, type):
            return isinstance(kind, type) and issubclass(kind, sub.event_type)
        return sub.event_type == kind_name


__all__ = [
    'ALL_EVENTS',
    'EmitReport',
    'EventBus',
    'Subscription',
]
