"""事件总线与 Pipeline 测试：订阅分发、异常隔离、步骤重试、失败中止。"""
from __future__ import annotations

import pytest

from server_manager_v8.application import (
    EventBus,
    LogAppended,
    Pipeline,
    PipelineAbortedError,
    PipelineFinished,
    Step,
    StepResult,
    StepUpdated,
    op_step,
)
from server_manager_v8.domain import OpResult


class TestEventBus:
    def test_type_subscribe(self) -> None:
        bus = EventBus()
        got = []
        bus.subscribe(lambda e: got.append(e), LogAppended)
        bus.publish(LogAppended(level='INFO', text='hello'))
        assert len(got) == 1 and got[0].text == 'hello'

    def test_catch_all_subscribe(self) -> None:
        bus = EventBus()
        got = []
        bus.subscribe(lambda e: got.append(type(e).__name__))
        bus.publish(LogAppended())
        assert got == ['LogAppended']

    def test_broken_subscriber_isolated(self) -> None:
        """订阅者抛异常不影响其他订阅者与发布者。"""
        bus = EventBus()
        got = []

        def broken(_e) -> None:
            raise RuntimeError('订阅者崩溃')

        bus.subscribe(broken)
        bus.subscribe(lambda e: got.append(1))
        bus.publish(LogAppended())  # 不应抛
        assert got == [1]

    def test_frozen_event(self) -> None:
        e = LogAppended(text='x')
        with pytest.raises(Exception):
            e.text = 'y'  # type: ignore[misc]


class TestStep:
    def test_success(self) -> None:
        step = Step('x', lambda: OpResult.success())
        result = step.run()
        assert result.ok and result.duration_ms >= 0

    def test_failure_no_retry(self) -> None:
        step = Step('x', lambda: OpResult.failure('boom'))
        result = step.run()
        assert not result.ok and result.reason == 'boom'

    def test_retry_then_success(self) -> None:
        calls = {'n': 0}

        def flaky() -> OpResult:
            calls['n'] += 1
            return OpResult.success() if calls['n'] >= 2 else OpResult.failure('retry')

        result = Step('x', flaky, retries=2).run()
        assert result.ok and calls['n'] == 2

    def test_retry_exhausted(self) -> None:
        result = Step('x', lambda: OpResult.failure('always'), retries=1).run()
        assert not result.ok

    def test_exception_turned_into_result(self) -> None:
        def boom() -> OpResult:
            raise ValueError('内部错误')

        result = Step('x', boom).run()
        assert not result.ok and 'ValueError' in result.reason

    def test_op_step_wrapper(self) -> None:
        assert op_step(lambda: True)().ok
        assert not op_step(lambda: False)().ok
        assert not op_step(lambda: 1 / 0)().ok


class TestPipeline:
    def test_all_steps_success(self) -> None:
        bus = EventBus()
        events = []
        bus.subscribe(lambda e: events.append(type(e).__name__))
        pipe = Pipeline(name='start_dev', bus=bus)
        pipe.add(Step('a', lambda: OpResult.success()))
        pipe.add(Step('b', lambda: OpResult.success()))
        result = pipe.run()
        assert result.ok
        assert events.count('StepUpdated') >= 4  # 每步 running + done
        assert events.count('PipelineFinished') == 1

    def test_fail_aborts_with_reason(self) -> None:
        pipe = Pipeline(name='p')
        pipe.add(Step('ok', lambda: OpResult.success()))
        pipe.add(Step('bad', lambda: OpResult.failure('端口被占用')))
        pipe.add(Step('never', lambda: OpResult.success()))
        with pytest.raises(PipelineAbortedError, match='端口被占用'):
            pipe.run()

    def test_empty_pipeline_rejected(self) -> None:
        assert not Pipeline(name='p').run().ok

    def test_step_events_carry_state(self) -> None:
        bus = EventBus()
        states = []
        bus.subscribe(lambda e: states.append(e.state) if isinstance(e, StepUpdated) else None)
        pipe = Pipeline(name='p', bus=bus)
        pipe.add(Step('s', lambda: OpResult.success()))
        pipe.run()
        assert states == ['running', 'done']

    def test_skipped_step(self) -> None:
        """StepResult.skip 语义：跳过并继续后续步骤。"""
        pipe = Pipeline(name='p')
        pipe.add(Step('skip', lambda: StepResult.skip('Redis 未配置')))
        pipe.add(Step('after', lambda: OpResult.success()))
        assert pipe.run().ok

    def test_finished_event_carries_duration(self) -> None:
        bus = EventBus()
        finished = []
        bus.subscribe(lambda e: finished.append(e) if isinstance(e, PipelineFinished) else None)
        pipe = Pipeline(name='p', bus=bus)
        pipe.add(Step('s', lambda: OpResult.success()))
        pipe.run()
        assert finished and finished[0].ok and finished[0].duration_ms >= 0
