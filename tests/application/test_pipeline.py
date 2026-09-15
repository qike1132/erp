"""流水线编排的单测。

重点是四类容易被写错的行为：
    1. 中止语义（关键步骤失败即停，不跳过、不继续执行后续步骤）
    2. 非关键步骤失败后**继续执行**（新增能力，要防回归）
    3. 步骤抛异常时的归一化（不能崩到顶层）
    4. 事件的顺序与内容（进度条依赖它）
"""

from __future__ import annotations

import pytest

from server_manager_v8.application.events import (
    PipelineAborted,
    StepFinished,
    StepStarted,
)
from server_manager_v8.application.pipeline import (
    Pipeline,
    Step,
    fail_step,
    ok_step,
)
from server_manager_v8.domain.results import OpResult
from tests.application.conftest import FakeClock


def collect():
    """返回 (emit 函数, 事件列表)。"""
    events: list = []
    return events.append, events


# ═══════════════════════════════════════════════════════════════════
# 构造与元信息
# ═══════════════════════════════════════════════════════════════════


class TestConstruction:
    def test_rejects_empty_name(self):
        with pytest.raises(ValueError, match='name'):
            Pipeline('', [ok_step('a')])

    def test_rejects_empty_steps(self):
        with pytest.raises(ValueError, match='至少需要一个步骤'):
            Pipeline('p', [])

    def test_rejects_step_without_name(self):
        with pytest.raises(ValueError, match='name'):
            Step('', lambda ctx: None)

    def test_rejects_non_callable_step_fn(self):
        with pytest.raises(TypeError, match='可调用'):
            Step('a', 'not callable')  # type: ignore[arg-type]

    def test_step_names_matches_legacy_startup_steps(self):
        """步骤名清单 = 旧 `_startup_steps` 列表（供 UI 预渲染进度条）。"""
        p = Pipeline('start_dev', [
            ok_step('停止生产模式'),
            ok_step('检查Redis服务'),
            ok_step('启动后端服务'),
            ok_step('启动前端服务'),
            ok_step('完成'),
        ])
        assert p.step_names == (
            '停止生产模式', '检查Redis服务', '启动后端服务', '启动前端服务', '完成',
        )
        assert p.total == 5


# ═══════════════════════════════════════════════════════════════════
# 正常路径
# ═══════════════════════════════════════════════════════════════════


class TestHappyPath:
    def test_runs_all_steps_in_order(self):
        order: list[str] = []
        p = Pipeline('p', [
            Step('a', lambda ctx: (order.append('a'), None)[1]),
            Step('b', lambda ctx: (order.append('b'), None)[1]),
            Step('c', lambda ctx: (order.append('c'), None)[1]),
        ])
        result = p.run()
        assert order == ['a', 'b', 'c']
        assert result.ok is True
        assert result.aborted_at is None
        assert result.completed == 3

    def test_context_passed_to_each_step(self):
        """上下文原样传递 —— 步骤之间靠它交换数据（如已启动的 PID）。"""
        seen: list = []
        ctx = {'pids': []}
        p = Pipeline('p', [
            Step('a', lambda c: (seen.append(c), None)[1]),
        ])
        p.run(ctx)
        assert seen[0] is ctx

    def test_none_return_treated_as_success(self):
        """返回 None 视为成功 —— 方便写「无返回值的动作」。"""
        p = Pipeline('p', [Step('a', lambda ctx: None)])
        assert p.run().ok is True

    def test_opresult_success_detail_propagated(self):
        p = Pipeline('p', [Step('a', lambda ctx: OpResult.success('done it'))])
        result = p.run()
        assert result.ok is True
        assert result.steps[0].detail == 'done it'


# ═══════════════════════════════════════════════════════════════════
# ★ 中止语义（最关键的保真点）
# ═══════════════════════════════════════════════════════════════════


class TestAbortSemantics:
    def test_critical_failure_aborts_remaining_steps(self):
        """★ 关键步骤失败 → 后续步骤**一步都不执行**。

        这是旧实现 `if not result.ok: ... return` 的语义。
        若写成「继续执行」，开发模式启动失败后仍会去启动后端进程 ——
        而生产可能还在跑，直接复现互杀事故。
        """
        ran: list[str] = []
        p = Pipeline('p', [
            Step('a', lambda ctx: (ran.append('a'), None)[1]),
            Step('b', lambda ctx: OpResult.failure('炸了', '细节')),
            Step('c', lambda ctx: (ran.append('c'), None)[1]),
        ])
        result = p.run()

        assert ran == ['a'], '失败之后的步骤绝不能执行'
        assert result.ok is False
        assert result.aborted_at == 'b'
        assert '炸了' in result.reason

    def test_aborted_result_requires_reason(self):
        p = Pipeline('p', [
            ok_step('a'),
            fail_step('b', '端口被占用', '2 个进程仍在监听'),
        ])
        result = p.run()
        assert result.reason
        assert result.failed_step == 'b'

    def test_step_results_only_include_executed_steps(self):
        """中止后，未执行的步骤不出现在结果里（不是「空结果占位」）。"""
        p = Pipeline('p', [
            ok_step('a'),
            fail_step('b', 'x'),
            ok_step('c'),
            ok_step('d'),
        ])
        result = p.run()
        assert len(result.steps) == 2
        assert [s.step for s in result.steps] == ['a', 'b']
        assert result.completed == 1

    def test_non_critical_failure_continues(self):
        """★ 非关键步骤失败后继续执行（新增能力）。

        用于「尽力而为」的步骤（如释放端口）。注意结果整体仍标记失败 ——
        因为它确实有步骤没成功，只是没阻断流程。
        """
        ran: list[str] = []
        p = Pipeline('p', [
            Step('a', lambda ctx: (ran.append('a'), None)[1]),
            Step('b', lambda ctx: OpResult.failure('release failed', '端口仍占用'),
                 critical=False),
            Step('c', lambda ctx: (ran.append('c'), None)[1]),
        ])
        result = p.run()

        assert ran == ['a', 'c'], '非关键步骤失败后必须继续'
        assert result.aborted_at is None
        assert result.failed_step == 'b'
        # 有步骤失败 → 整体仍为失败（不掩盖）
        assert result.ok is False

    def test_all_non_critical_failures_still_reported(self):
        p = Pipeline('p', [
            Step('a', lambda ctx: OpResult.failure('r1', 'd1'), critical=False),
            Step('b', lambda ctx: OpResult.failure('r2', 'd2'), critical=False),
        ])
        result = p.run()
        assert len(result.steps) == 2
        assert all(not s.ok for s in result.steps)


# ═══════════════════════════════════════════════════════════════════
# 异常归一化
# ═══════════════════════════════════════════════════════════════════


class TestExceptionNormalization:
    def test_step_exception_becomes_failure(self):
        """步骤抛异常 → 变成一次「有理由的失败」，不崩到顶层。"""
        def boom(ctx):
            raise RuntimeError('底层炸了')

        p = Pipeline('p', [Step('a', boom), ok_step('b')])
        result = p.run()

        assert result.ok is False
        assert result.aborted_at == 'a'
        # reason 记异常类型（一行摘要），detail 记原文（展开详情）
        assert result.steps[0].reason == 'RuntimeError'
        assert '底层炸了' in result.steps[0].detail

    def test_exception_in_non_critical_step_continues(self):
        def boom(ctx):
            raise ValueError('可忽略的错误')

        ran: list[str] = []
        p = Pipeline('p', [
            Step('a', boom, critical=False),
            Step('b', lambda ctx: (ran.append('b'), None)[1]),
        ])
        result = p.run()
        assert ran == ['b']
        assert result.aborted_at is None

    def test_bad_return_type_is_failure(self):
        """返回不认识的东西 → 报错而不是静默放过。

        静默放过会让写错的步骤（比如忘了 return OpResult）悄悄「成功」。
        """
        p = Pipeline('p', [Step('a', lambda ctx: 'unexpected string')])
        result = p.run()
        assert result.ok is False
        assert '类型非法' in result.steps[0].reason
        assert 'str' in result.steps[0].detail

    def test_keyboard_interrupt_is_caught_as_failure(self):
        """极端异常也被步骤边界吸收，不让流水线崩到顶层。"""
        def interrupt(ctx):
            raise KeyboardInterrupt()

        p = Pipeline('p', [Step('a', interrupt)])
        result = p.run()
        assert result.ok is False
        assert result.steps[0].reason == 'KeyboardInterrupt'


# ═══════════════════════════════════════════════════════════════════
# 事件
# ═══════════════════════════════════════════════════════════════════


class TestEvents:
    def test_emits_started_and_finished_per_step(self):
        emit, events = collect()
        clock = FakeClock()
        p = Pipeline('start_dev', [ok_step('a'), ok_step('b')],
                     clock=clock, emit=emit)
        p.run(trace_id='t1')

        started = [e for e in events if isinstance(e, StepStarted)]
        finished = [e for e in events if isinstance(e, StepFinished)]
        assert len(started) == 2
        assert len(finished) == 2
        assert [e.step for e in started] == ['a', 'b']
        assert [e.index for e in started] == [1, 2]
        assert all(e.total == 2 for e in started)
        assert all(e.trace_id == 't1' for e in started)

    def test_emits_aborted_on_critical_failure(self):
        emit, events = collect()
        p = Pipeline('start_dev', [ok_step('a'), fail_step('b', 'r', 'd')],
                     clock=FakeClock(), emit=emit)
        p.run(trace_id='t1')

        aborted = [e for e in events if isinstance(e, PipelineAborted)]
        assert len(aborted) == 1
        assert aborted[0].failed_step == 'b'
        assert aborted[0].completed == 1
        assert aborted[0].total == 2
        assert aborted[0].trace_id == 't1'

    def test_no_aborted_event_on_success(self):
        emit, events = collect()
        p = Pipeline('p', [ok_step('a')], clock=FakeClock(), emit=emit)
        p.run()
        assert not [e for e in events if isinstance(e, PipelineAborted)]

    def test_no_aborted_event_for_non_critical_failure(self):
        """非关键步骤失败不触发中止事件（它没中止流程）。"""
        emit, events = collect()
        p = Pipeline('p', [
            Step('a', lambda ctx: OpResult.failure('r', 'd'), critical=False),
        ], clock=FakeClock(), emit=emit)
        p.run()
        assert not [e for e in events if isinstance(e, PipelineAborted)]

    def test_emit_failure_does_not_break_pipeline(self):
        """★ 事件发布失败不能中断业务（通知机制不该影响主流程）。"""
        def broken_emit(event):
            raise RuntimeError('总线炸了')

        p = Pipeline('p', [ok_step('a'), ok_step('b')],
                     clock=FakeClock(), emit=broken_emit)
        result = p.run()
        assert result.ok is True
        assert result.completed == 2

    def test_step_order_started_then_finished(self):
        """每步的事件顺序是 Started → Finished（进度条依赖这个顺序）。"""
        emit, events = collect()
        p = Pipeline('p', [ok_step('a')], clock=FakeClock(), emit=emit)
        p.run()
        kinds = [type(e).__name__ for e in events]
        assert kinds == ['StepStarted', 'StepFinished']


# ═══════════════════════════════════════════════════════════════════
# 耗时与并发
# ═══════════════════════════════════════════════════════════════════


class TestDuration:
    def test_duration_from_injected_clock(self):
        clock = FakeClock()

        def slow(ctx):
            clock.advance(0.25)
            return None

        p = Pipeline('p', [Step('a', slow)], clock=clock)
        result = p.run()
        assert result.steps[0].duration_ms == 250
        assert result.duration_ms == 250

    def test_zero_duration_does_not_go_negative(self):
        """时钟回退（异常情况）不能让 duration 变负数。"""
        clock = FakeClock()

        def back(ctx):
            clock.advance(-1.0)
            return None

        p = Pipeline('p', [Step('a', back)], clock=clock)
        assert p.run().steps[0].duration_ms == 0


class TestNoSharedState:
    def test_same_pipeline_runnable_concurrently(self):
        """★ 同一个 Pipeline 实例可被多次/并发 run，互不干扰。

        旧实现把进度存在 `self._startup_progress` 上，两次启动会互相覆盖。
        """
        p = Pipeline('p', [ok_step('a'), ok_step('b')], clock=FakeClock())
        r1 = p.run(trace_id='t1')
        r2 = p.run(trace_id='t2')
        assert r1.ok is True
        assert r2.ok is True
        assert r1.steps == r2.steps

    def test_pipeline_does_not_mutate_step_list(self):
        steps = [ok_step('a')]
        p = Pipeline('p', steps)
        p.run()
        p.run()
        assert p.total == 1
