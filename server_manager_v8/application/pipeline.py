"""Pipeline 编排模型（腾讯蓝鲸 SOPS 裁剪）— 多步运维动作的显式建模。

解决 v6 的核心病灶 D15：开发模式启动的 5 个步骤写死在一个 120 行线程函数里。
v8 把步骤建模为可单测的 Pipeline：

    - Step：单个步骤（名称 + 执行函数 + 可重试策略）
    - StepResult：显式结果（ok/reason/duration_ms/skipped）
    - Pipeline：顺序执行、失败即中止、每步发布事件驱动 Stepper 渲染

语义对齐蓝鲸 SOPS：步骤可视化、耗时可见、失败中止、可重试。
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from server_manager_v8.domain import OpResult

from .event_bus import EventBus
from .events import PipelineFinished, PipelineStarted, StepUpdated

__all__ = ['Pipeline', 'PipelineAbortedError', 'Step', 'StepResult']

STATE_PENDING = 'pending'
STATE_RUNNING = 'running'
STATE_DONE = 'done'
STATE_FAILED = 'failed'
STATE_SKIPPED = 'skipped'

ExecuteFn = Callable[[], OpResult]


@dataclass(frozen=True)
class StepResult:
    """单步执行结果。"""

    ok: bool
    reason: str = ''
    duration_ms: int = 0
    skipped: bool = False

    @classmethod
    def success(cls, duration_ms: int = 0) -> StepResult:
        return cls(ok=True, duration_ms=duration_ms)

    @classmethod
    def fail(cls, reason: str, duration_ms: int = 0) -> StepResult:
        return cls(ok=False, reason=reason, duration_ms=duration_ms)

    @classmethod
    def skip(cls, reason: str = '') -> StepResult:
        return cls(ok=True, reason=reason, skipped=True)


class PipelineAbortedError(Exception):
    """步骤失败导致的中止。msg 面向 UI 展示。"""


@dataclass
class Step:
    """一个可执行步骤。"""

    name: str
    execute: ExecuteFn
    retries: int = 0  # 失败重试次数（幂等步骤可配，如清端口）

    def run(self, on_update: Callable[[str], None] | None = None) -> StepResult:
        start = time.monotonic()
        attempts = 0
        while True:
            attempts += 1
            if on_update:
                on_update(STATE_RUNNING)
            try:
                result = self.execute()
            except Exception as exc:
                result = OpResult.failure(f'{type(exc).__name__}: {exc}')
            duration = int((time.monotonic() - start) * 1000)
            if result.ok:
                if on_update:
                    on_update(STATE_DONE)
                return StepResult.success(duration_ms=duration)
            if attempts <= self.retries:
                continue
            if on_update:
                on_update(STATE_FAILED)
            return StepResult.fail(result.reason or '执行失败', duration_ms=duration)


@dataclass
class Pipeline:
    """顺序步骤编排：失败即中止，每步发布事件。"""

    name: str
    steps: list[Step] = field(default_factory=list)
    bus: EventBus | None = None
    trace_id: str = ''

    def add(self, step: Step) -> Pipeline:
        self.steps.append(step)
        return self

    def run(self, *, on_skip: Callable[[int, str], bool] | None = None) -> OpResult:
        """执行全部步骤。

        on_skip(index, reason) -> bool：某步可跳过时回调，返回 True 跳过。
        任何一步失败 → PipelineAbortedError（携带失败原因），已执行步骤不回滚
        （回滚由 UseCase 层负责，如 start_dev 失败调用 ModeMachine.rollback）。
        """
        if not self.steps:
            return OpResult.failure('Pipeline 没有步骤')
        total = len(self.steps)
        start = time.monotonic()
        if self.bus:
            self.bus.publish(PipelineStarted(name=self.name, steps=total, trace_id=self.trace_id))
        for index, step in enumerate(self.steps, 1):
            result = step.run(on_update=lambda state, step=step, index=index: self._publish_step(
                step.name, index, total, state,
            ))
            if result.skipped:
                self._publish_step(step.name, index, total, STATE_SKIPPED, result.reason)
                continue
            if not result.ok:
                self._publish_step(step.name, index, total, STATE_FAILED, result.reason)
                if self.bus:
                    self.bus.publish(PipelineFinished(
                        name=self.name, ok=False, reason=result.reason,
                        duration_ms=int((time.monotonic() - start) * 1000),
                        trace_id=self.trace_id,
                    ))
                raise PipelineAbortedError(result.reason)
        if self.bus:
            self.bus.publish(PipelineFinished(
                name=self.name, ok=True,
                duration_ms=int((time.monotonic() - start) * 1000),
                trace_id=self.trace_id,
            ))
        return OpResult.success(detail=f'{total} 步全部完成')

    def _publish_step(self, step: str, index: int, total: int, state: str, detail: str = '') -> None:
        if self.bus:
            self.bus.publish(StepUpdated(
                pipeline=self.name, step=step, index=index, total=total,
                state=state, detail=detail, trace_id=self.trace_id,
            ))

    def should_skip(self, index: int, reason: str) -> bool:
        """默认跳过策略：子类可覆写（如 Redis 缺失仅警告不中止）。"""
        return False


# Pipeline 的步骤函数需要能返回 OpResult 或抛异常；此处提供便捷封装
def op_step(fn: Callable[[], Any]) -> Callable[[], OpResult]:
    """把返回 bool/None 的函数包装为 OpResult（True/无异常=成功）。"""

    def wrapper() -> OpResult:
        try:
            value = fn()
        except Exception as exc:
            return OpResult.failure(f'{type(exc).__name__}: {exc}')
        if value is False:
            return OpResult.failure('返回 False')
        return OpResult.success()

    return wrapper
