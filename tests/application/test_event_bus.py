"""事件与事件总线的单测。

覆盖三类：
    1. 事件类型本身的契约（frozen、必填字段校验）
    2. 总线的订阅 / 分发 / 退订语义
    3. ★ 并发与异常隔离（最容易出问题的地方）
"""

from __future__ import annotations

import threading

import pytest

from server_manager_v8.application.event_bus import (
    ALL_EVENTS,
    EmitReport,
    EventBus,
)
from server_manager_v8.application.events import (
    AuthChanged,
    DevStartupFailed,
    Event,
    LogAppended,
    LogBatchAppended,
    LogLevel,
    MetricsUpdated,
    OperationFailed,
    StartupProgressed,
    StateChanged,
    StepFinished,
    ToastRequested,
)
from server_manager_v8.domain.models import RunMode
from server_manager_v8.domain.results import Severity


# ═══════════════════════════════════════════════════════════════════
# 事件类型契约
# ═══════════════════════════════════════════════════════════════════


class TestEventContract:
    def test_events_are_frozen(self):
        """事件不可变 —— 发布后不该被 handler 篡改。"""
        e = LogAppended(ts=1.0, text='hello')
        with pytest.raises(Exception):
            e.text = 'tampered'  # type: ignore[misc]

    def test_log_appended_rejects_empty_text(self):
        """空文本在**构造时**就拒绝。

        这是相对旧实现 `data.get('text', '')` 的核心改进：
        旧写法让「忘记传 text」看起来像「text 是空字符串」。
        """
        with pytest.raises(ValueError, match='不能为空'):
            LogAppended(ts=1.0, text='')

    def test_dev_startup_failed_requires_reason(self):
        """失败事件必须带原因 —— 禁止空洞的失败。"""
        with pytest.raises(ValueError, match='不能为空'):
            DevStartupFailed(ts=1.0, reason='')

    def test_operation_failed_requires_reason(self):
        with pytest.raises(ValueError, match='不能为空'):
            OperationFailed(ts=1.0, action='kill_port', reason='')

    def test_step_finished_failure_requires_detail(self):
        """失败的步骤必须说明细节，否则运维无从下手。"""
        with pytest.raises(ValueError, match='detail'):
            StepFinished(ts=1.0, trace_id='t1', step='stop_prod', ok=False)
        # 成功时不要求 detail
        StepFinished(ts=1.0, trace_id='t1', step='stop_prod', ok=True)

    def test_toast_requires_text(self):
        with pytest.raises(ValueError, match='不能为空'):
            ToastRequested(ts=1.0, text='')

    def test_event_kind_property(self):
        assert LogAppended(ts=1.0, text='x').kind == 'LogAppended'
        assert isinstance(LogAppended(ts=1.0, text='x'), Event)

    def test_defaults_are_sane(self):
        e = LogAppended(ts=1.0, text='x')
        assert e.level is LogLevel.INFO
        assert e.source == ''

    def test_startup_progress_percent(self):
        assert StartupProgressed(ts=0, trace_id='t', step='a', index=1, total=4).percent == 25
        assert StartupProgressed(ts=0, trace_id='t', step='a', index=4, total=4).percent == 100

    def test_startup_progress_zero_total_does_not_crash(self):
        """total=0 不能除零 —— 旧实现在没传 total 时不崩，新实现必须同样。"""
        assert StartupProgressed(ts=0, trace_id='t', step='a').percent == 0

    def test_startup_progress_clamps(self):
        """进度不能小于 0 或大于 100（越界值来自上游 bug，不该显示给用户）。"""
        assert StartupProgressed(ts=0, trace_id='t', step='a', index=99, total=4).percent == 100
        assert StartupProgressed(ts=0, trace_id='t', step='a', index=-5, total=4).percent == 0

    def test_metrics_updated_allows_none_sample(self):
        """★ None 表示「采集器不可用」，必须能被表达。

        这是与「采到全 0」的关键区分（见 adapters/metrics_psutil docstring）。
        """
        e = MetricsUpdated(ts=1.0)
        assert e.sample is None

    def test_log_batch_defaults_empty(self):
        assert LogBatchAppended(ts=1.0).lines == ()

    def test_state_changed_carries_modes(self):
        e = StateChanged(ts=1.0, old=RunMode.NONE, new=RunMode.PROD)
        assert e.old is RunMode.NONE
        assert e.new is RunMode.PROD


# ═══════════════════════════════════════════════════════════════════
# 总线的订阅与分发
# ═══════════════════════════════════════════════════════════════════


class TestSubscribeAndEmit:
    def test_dispatches_only_matching_type(self):
        """只分发给订阅了该类型（或基类）的 handler。"""
        bus = EventBus()
        logs: list = []
        toasts: list = []
        bus.subscribe(LogAppended, logs.append)
        bus.subscribe(ToastRequested, toasts.append)

        bus.emit(LogAppended(ts=1.0, text='a'))
        assert len(logs) == 1
        assert len(toasts) == 0

    def test_multiple_handlers_all_called(self):
        bus = EventBus()
        got: list[str] = []
        bus.subscribe(LogAppended, lambda e: got.append('h1'))
        bus.subscribe(LogAppended, lambda e: got.append('h2'))
        bus.emit(LogAppended(ts=1.0, text='a'))
        assert got == ['h1', 'h2']

    def test_handlers_called_in_subscription_order(self):
        """★ 顺序保证：订阅顺序 = 调用顺序。

        这让「先审计再更新 UI」这类要求可以通过订阅顺序表达，
        而不需要在 handler 内部手工排序。
        """
        bus = EventBus()
        order: list[str] = []
        bus.subscribe(LogAppended, lambda e: order.append('first'))
        bus.subscribe(LogAppended, lambda e: order.append('second'))
        bus.subscribe(LogAppended, lambda e: order.append('third'))
        bus.emit(LogAppended(ts=1.0, text='a'))
        assert order == ['first', 'second', 'third']

    def test_wildcard_subscription_receives_all(self):
        bus = EventBus()
        seen: list[str] = []
        bus.subscribe(ALL_EVENTS, lambda e: seen.append(type(e).__name__))

        bus.emit(LogAppended(ts=1.0, text='a'))
        bus.emit(ToastRequested(ts=1.0, text='b'))
        bus.emit(AuthChanged(ts=1.0, role='admin'))

        assert seen == ['LogAppended', 'ToastRequested', 'AuthChanged']

    def test_subscribe_by_base_class_catches_subclasses(self):
        """订阅基类能收到所有子类事件（isinstance 语义）。"""
        bus = EventBus()
        got: list = []
        bus.subscribe(Event, got.append)
        bus.emit(LogAppended(ts=1.0, text='a'))
        assert len(got) == 1

    def test_subscribe_by_string_name(self):
        """按类名字符串订阅（兼容场景）。"""
        bus = EventBus()
        got: list = []
        bus.subscribe('LogAppended', got.append)
        bus.emit(LogAppended(ts=1.0, text='a'))
        bus.emit(ToastRequested(ts=1.0, text='b'))
        assert len(got) == 1

    def test_emit_returns_report(self):
        bus = EventBus()
        bus.subscribe(LogAppended, lambda e: None)
        bus.subscribe(LogAppended, lambda e: None)
        report = bus.emit(LogAppended(ts=1.0, text='a'))
        assert isinstance(report, EmitReport)
        assert report.delivered == 2
        assert report.failed == 0
        assert report.ok is True
        assert report.kind == 'LogAppended'

    def test_emit_with_no_subscribers_is_fine(self):
        """没有订阅者不是错误（总线允许事件被忽略）。"""
        report = EventBus().emit(LogAppended(ts=1.0, text='a'))
        assert report.delivered == 0
        assert report.ok is True

    def test_subscribe_rejects_non_callable(self):
        with pytest.raises(TypeError, match='可调用'):
            EventBus().subscribe(LogAppended, 'not a function')  # type: ignore[arg-type]


# ═══════════════════════════════════════════════════════════════════
# 退订
# ═══════════════════════════════════════════════════════════════════


class TestUnsubscribe:
    def test_unsubscribe_stops_delivery(self):
        bus = EventBus()
        got: list = []
        sub = bus.subscribe(LogAppended, got.append)
        bus.emit(LogAppended(ts=1.0, text='a'))
        assert bus.unsubscribe(sub) is True
        bus.emit(LogAppended(ts=1.0, text='b'))
        assert len(got) == 1

    def test_double_unsubscribe_returns_false(self):
        bus = EventBus()
        sub = bus.subscribe(LogAppended, lambda e: None)
        assert bus.unsubscribe(sub) is True
        assert bus.unsubscribe(sub) is False

    def test_once_subscription_auto_removes(self):
        """`once=True` 只触发一次 —— 避免「等一次事件」忘记退订造成泄漏。"""
        bus = EventBus()
        got: list = []
        bus.subscribe(LogAppended, got.append, once=True)
        bus.emit(LogAppended(ts=1.0, text='a'))
        bus.emit(LogAppended(ts=1.0, text='b'))
        assert len(got) == 1
        assert bus.subscription_count == 0

    def test_clear_removes_all(self):
        bus = EventBus()
        bus.subscribe(LogAppended, lambda e: None)
        bus.subscribe(ToastRequested, lambda e: None)
        assert bus.subscription_count == 2
        bus.clear()
        assert bus.subscription_count == 0

    def test_handler_can_unsubscribe_itself_during_emit(self):
        """★ handler 在 emit 过程中退订自己不能引发 RuntimeError。

        实现上靠「先快照订阅列表」保证 —— 直接遍历原列表会在修改时炸。
        """
        bus = EventBus()
        calls: list[int] = []

        def self_removing(event):
            calls.append(1)
            bus.unsubscribe(sub)  # type: ignore[used-before-assignment]

        sub = bus.subscribe(LogAppended, self_removing)
        bus.emit(LogAppended(ts=1.0, text='a'))
        bus.emit(LogAppended(ts=1.0, text='b'))
        assert len(calls) == 1

    def test_handler_subscribing_during_emit_does_not_break_iteration(self):
        """handler 在 emit 期间新增订阅，本次 emit 不应立刻触发它。"""
        bus = EventBus()
        late: list = []

        def add_subscriber(event):
            bus.subscribe(LogAppended, late.append)

        bus.subscribe(LogAppended, add_subscriber)
        bus.emit(LogAppended(ts=1.0, text='a'))
        # 快照语义：新订阅在**下一次** emit 才生效
        assert len(late) == 0
        bus.emit(LogAppended(ts=1.0, text='b'))
        assert len(late) == 1


# ═══════════════════════════════════════════════════════════════════
# ★ 异常隔离
# ═══════════════════════════════════════════════════════════════════


class TestHandlerErrorIsolation:
    def test_broken_handler_does_not_block_others(self):
        """★ 一个 handler 炸掉不能影响其他 handler。

        真实后果：若 UI handler 抛异常导致审计 handler 没被调用，
        就丢失了审计留痕 —— 审计丢一条，4A 链条就断了。
        """
        bus = EventBus(on_handler_error=lambda exc, ev: None)
        before: list = []
        after: list = []
        bus.subscribe(LogAppended, before.append)
        bus.subscribe(LogAppended, lambda e: 1 / 0)
        bus.subscribe(LogAppended, after.append)

        report = bus.emit(LogAppended(ts=1.0, text='a'))

        assert len(before) == 1
        assert len(after) == 1, '异常 handler 后的订阅者必须仍被调用'
        assert report.failed == 1
        assert report.delivered == 2
        assert report.ok is False

    def test_emit_never_raises_even_if_handler_does(self):
        bus = EventBus(on_handler_error=lambda exc, ev: None)
        bus.subscribe(LogAppended, lambda e: raise_fake())
        bus.emit(LogAppended(ts=1.0, text='a'))  # 不应抛出

    def test_error_callback_receives_exception_and_event(self):
        captured: list = []
        bus = EventBus(on_handler_error=lambda exc, ev: captured.append((exc, ev)))
        bus.subscribe(LogAppended, lambda e: 1 / 0)
        bus.emit(LogAppended(ts=1.0, text='a'))
        assert len(captured) == 1
        exc, ev = captured[0]
        assert isinstance(exc, ZeroDivisionError)
        assert isinstance(ev, LogAppended)

    def test_broken_error_callback_does_not_break_emit(self):
        """错误回调自己炸了也必须被吞掉，否则 emit 就失去了「永不抛出」的保证。"""
        def bad_callback(exc, ev):
            raise RuntimeError('callback 也炸了')

        bus = EventBus(on_handler_error=bad_callback)
        bus.subscribe(LogAppended, lambda e: 1 / 0)
        bus.emit(LogAppended(ts=1.0, text='a'))

    def test_error_does_not_silence_by_default(self, capsys):
        """默认错误回调写 stderr —— 不静默（项目铁律）。"""
        bus = EventBus()
        bus.subscribe(LogAppended, lambda e: 1 / 0)
        bus.emit(LogAppended(ts=1.0, text='a'))
        captured = capsys.readouterr()
        assert 'LogAppended' in captured.err
        assert 'ZeroDivisionError' in captured.err

    def test_report_lists_all_errors(self):
        bus = EventBus(on_handler_error=lambda exc, ev: None)
        bus.subscribe(LogAppended, lambda e: 1 / 0)
        # ★ 注意：不能写 `lambda e: KeyError('x')` —— 那只是**构造**了异常对象
        #   并把它当返回值，不会抛出。必须显式 raise。
        bus.subscribe(LogAppended, lambda e: (_ for _ in ()).throw(KeyError('x')))
        report = bus.emit(LogAppended(ts=1.0, text='a'))
        assert report.failed == 2
        assert len(report.errors) == 2
        assert any('ZeroDivisionError' in msg for _, msg in report.errors)
        assert any('KeyError' in msg for _, msg in report.errors)


def raise_fake():
    raise RuntimeError('模拟 handler 失败')


# ═══════════════════════════════════════════════════════════════════
# ★ 线程安全
# ═══════════════════════════════════════════════════════════════════


class TestThreadSafety:
    def test_concurrent_emit_from_multiple_threads(self):
        """多线程并发 emit 不丢事件、不崩。"""
        bus = EventBus(on_handler_error=lambda exc, ev: None)
        received: list = []
        lock = threading.Lock()

        def record(event):
            with lock:
                received.append(event.text)

        bus.subscribe(LogAppended, record)

        def worker(tag: str) -> None:
            for i in range(50):
                bus.emit(LogAppended(ts=1.0, text=f'{tag}-{i}'))

        threads = [threading.Thread(target=worker, args=(f't{n}',)) for n in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(received) == 200

    def test_concurrent_subscribe_and_emit(self):
        """emit 期间另一线程订阅/退订不能引发 RuntimeError。"""
        bus = EventBus(on_handler_error=lambda exc, ev: None)
        stop = threading.Event()
        errors: list = []

        def churn():
            while not stop.is_set():
                try:
                    sub = bus.subscribe(LogAppended, lambda e: None)
                    bus.unsubscribe(sub)
                except Exception as exc:  # noqa: BLE001
                    errors.append(exc)
                    return

        def emit_loop():
            for _ in range(200):
                try:
                    bus.emit(LogAppended(ts=1.0, text='x'))
                except Exception as exc:  # noqa: BLE001
                    errors.append(exc)
                    return

        churner = threading.Thread(target=churn)
        churner.start()
        emit_loop()
        stop.set()
        churner.join()

        assert errors == [], f'并发操作不应出错: {errors}'


# ═══════════════════════════════════════════════════════════════════
# 与旧实现的对照（保真说明）
# ═══════════════════════════════════════════════════════════════════


class TestMigrationFidelity:
    def test_all_nine_legacy_message_types_have_a_class(self):
        """旧实现的 9 种 `_msg_queue` 类型必须都有对应事件类。

        这是防止「迁移时漏掉一种事件」的清单式断言 ——
        漏掉的话那个功能会静默失效（没人订阅到，也没人发现）。
        """
        from server_manager_v8.application import events as E

        legacy_to_new = {
            'log': 'LogAppended',
            'log_batch': 'LogBatchAppended',
            'toast': 'ToastRequested',
            'state_set': 'StateChanged',
            'startup_progress': 'StartupProgressed',
            'dual_failed': 'DevStartupFailed',
            'hosting_refresh': 'ServiceListChanged',
            'hosting_apply': 'ServiceApplied',
            'dual_started': 'DevStarted',
        }
        for legacy, new_name in legacy_to_new.items():
            assert hasattr(E, new_name), (
                f'旧事件 {legacy!r} 没有对应的新事件类 {new_name} —— 迁移遗漏'
            )

    def test_log_level_matches_legacy_strings(self):
        """级别字面量必须与旧实现的字符串一致（日志解析依赖）。"""
        assert LogLevel.INFO.value == 'INFO'
        assert LogLevel.WARNING.value == 'WARNING'
        assert LogLevel.ERROR.value == 'ERROR'

    def test_severity_used_for_toast(self):
        """toast 用 Severity 而非 LogLevel —— 因为它是给用户看的告警级别。"""
        e = ToastRequested(ts=1.0, text='x', level=Severity.P2)
        assert e.level is Severity.P2
