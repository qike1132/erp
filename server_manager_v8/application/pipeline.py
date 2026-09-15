"""流水线编排 —— Step / StepResult / Pipeline（SOPS 步骤模型）。

═══════════════════════════════════════════════════════════════════
迁移来源：server_manager.py v5.40 的启动流程
═══════════════════════════════════════════════════════════════════

旧实现的开发模式启动是**硬编码的 5 步**，而且分散在两个方法里接力：

    `_start_dual_worker()`:
        ① startup_progress[0] '停止生产模式' → _ensure_production_stopped()
        → 然后调 _start_dual_thread() 继续

    `_start_dual_thread()`:
        ② startup_progress[1] '检查Redis服务'
        ③ startup_progress[2] '启动后端服务'
        ④ startup_progress[3] '启动前端服务'
        ⑤ startup_progress[4] '完成'

问题有三：

1. **步骤清单散落**：`self._startup_steps = [...]` 是一份列表，
   但实际执行顺序靠两个方法体的调用链隐式表达。列表与代码可能不一致 ——
   改了列表忘了改代码，进度条就会错位。

2. **失败处理靠手工 return**：每一步失败都要手写「记日志 + 发
   dual_failed + return」。漏写一处，失败就被吞掉（这正是 D5 静默失败的
   具体形态）。而且 `_start_dual_worker` 的 `try` 块里，异常路径与
   正常路径的日志写法不一致。

3. **不可复用**：生产模式启动、停止全部、模式切换都是同构的「一串步骤」，
   但因为写成了具体方法，每加一个流程就要抄一遍骨架。

本模块把「一串步骤」抽象为数据：

    Pipeline(name, steps=[
        Step('停止生产模式', stop_prod),
        Step('检查Redis服务', check_redis),
        ...
    ])

═══════════════════════════════════════════════════════════════════
★ 保真要求：中止语义必须与旧实现一致
═══════════════════════════════════════════════════════════════════

旧实现的行为是**任一关键步骤失败即整体中止**（不跳过、不继续）。
`_start_dual_worker` 里 `if not result.ok: ... return` 就是这个语义。

新实现通过 `Step.critical` 表达：
    · `critical=True`（默认）→ 失败即中止整条流水线
    · `critical=False` → 失败继续，但**必须记录**（不静默）

★ `critical=False` 是**新增能力**，不是对旧行为的改变 ——
  旧实现里没有「可失败步骤」，所有步骤都是关键的。
  它存在是为了让「停机释放端口」这类「尽力而为」的步骤可以继续执行
  （这与 `adapters.process_win.run_quiet` 的「尽力而为」语义一致）。

═══════════════════════════════════════════════════════════════════
与事件总线的解耦
═══════════════════════════════════════════════════════════════════

Pipeline **不认识** EventBus —— 它只调用注入的 `emit` 回调。
这样可以用一个纯 list 收集事件来做测试，不必构造总线。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from ..domain.results import OpResult
from .events import Event, PipelineAborted, StepFinished, StepStarted

#: 步骤函数签名：接收上下文，返回 OpResult（或 None 表示成功）
StepFn = Callable[[Any], "OpResult | None"]


@dataclass(frozen=True)
class Step:
    """一个流水线步骤。

    `name` 是**用户可见**的步骤名（旧实现里 `_startup_steps` 的字符串，
    直接显示在进度条上），因此改动它等于改 UI 文案，需要谨慎。
    """

    name: str
    fn: StepFn
    critical: bool = True
    detail: str = ''

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError('Step.name 不能为空（它是进度条上显示的文案）')
        if not callable(self.fn):
            raise TypeError(f'Step.fn 必须可调用，得到 {type(self.fn).__name__}')


@dataclass(frozen=True)
class StepResult:
    """一步的执行结果。

    `reason` 是「为什么失败」（简短），`detail` 是补充说明。
    两者分开是因为 UI 上显示的位置不同：
        进度条下方一行小字 → reason（如「端口被占用」）
        展开详情 / 日志     → detail（如「2 个进程仍在监听: 1234, 5678」）
    """

    step: str
    ok: bool
    duration_ms: int = 0
    detail: str = ''
    reason: str = ''
    skipped: bool = False

    def __post_init__(self) -> None:
        if not self.ok and not self.detail and not self.reason and not self.skipped:
            raise ValueError('StepResult 失败时必须提供 reason 或 detail')

    @property
    def summary(self) -> str:
        """给用户看的一行摘要：优先 reason，其次 detail。"""
        return self.reason or self.detail


@dataclass(frozen=True)
class PipelineResult:
    """整条流水线的执行结果。"""

    pipeline: str
    ok: bool
    steps: tuple[StepResult, ...] = ()
    aborted_at: str | None = None
    reason: str = ''
    duration_ms: int = 0

    def __post_init__(self) -> None:
        if not self.ok and not self.reason:
            raise ValueError('PipelineResult 失败时必须提供 reason（禁止空洞的失败）')

    @property
    def completed(self) -> int:
        """已完成的步骤数（不含被跳过与被中止后的）。"""
        return sum(1 for s in self.steps if s.ok or s.skipped)

    @property
    def failed_step(self) -> str | None:
        for s in self.steps:
            if not s.ok and not s.skipped:
                return s.step
        return None


class Pipeline:
    """一串有序步骤。

    ★ 本类**不持有可变状态**（`run()` 的中间状态全在局部变量里）——
      同一个 Pipeline 实例可以被多个线程同时 `run()`，互不干扰。
      旧实现把进度存在 `self._startup_progress` 上，两次启动会互相覆盖。
    """

    def __init__(self, name: str, steps: list[Step] | tuple[Step, ...], *,
                 clock: Any = None, emit: Callable[[Event], Any] | None = None) -> None:
        if not name:
            raise ValueError('Pipeline.name 不能为空')
        if not steps:
            raise ValueError('Pipeline 至少需要一个步骤')
        self._name = name
        self._steps = list(steps)
        self._clock = clock
        self._emit = emit or (lambda event: None)

    @property
    def name(self) -> str:
        return self._name

    @property
    def step_names(self) -> tuple[str, ...]:
        """步骤名清单（旧实现 `_startup_steps` 的对应物，供 UI 预渲染进度条）。"""
        return tuple(s.name for s in self._steps)

    @property
    def total(self) -> int:
        return len(self._steps)

    def _now(self) -> float:
        if self._clock is None:
            import time  # noqa: PLC0415
            return time.monotonic()
        return self._clock.monotonic()

    def _emit_event(self, event: Event) -> None:
        """发事件。

        ★ 事件发布失败**不能中断流水线** —— 通知机制不该影响业务
          （与 `NotifyPort` / `AuditPort` 的「永不抛出」同一原则）。
          但也不静默：交由 emit 实现自己负责留痕。
        """
        try:
            self._emit(event)
        except BaseException:  # noqa: BLE001
            pass

    def run(self, context: Any = None, *, trace_id: str = '') -> PipelineResult:
        """顺序执行所有步骤。

        `context` 是任意对象，会原样传给每个步骤函数 ——
        用于在步骤之间传递数据（如已启动的 PID）。
        """
        started = self._now()
        results: list[StepResult] = []
        any_failed = False

        for index, step in enumerate(self._steps):
            self._emit_event(StepStarted(
                ts=self._now(), trace_id=trace_id, pipeline=self._name,
                step=step.name, index=index + 1, total=self.total,
            ))

            step_started = self._now()
            ok, reason, detail = self._run_step(step, context)
            duration_ms = max(0, int((self._now() - step_started) * 1000))

            results.append(StepResult(
                step=step.name, ok=ok, duration_ms=duration_ms,
                detail=detail, reason=reason,
            ))
            if not ok:
                any_failed = True

            self._emit_event(StepFinished(
                ts=self._now(), trace_id=trace_id, step=step.name, ok=ok,
                duration_ms=duration_ms, detail=detail or reason,
            ))

            if not ok and step.critical:
                abort_reason = f'{step.name} 失败: {reason or detail}'
                self._emit_event(PipelineAborted(
                    ts=self._now(), trace_id=trace_id, pipeline=self._name,
                    failed_step=step.name, reason=abort_reason,
                    completed=len(results) - 1, total=self.total,
                ))
                return PipelineResult(
                    pipeline=self._name, ok=False, steps=tuple(results),
                    aborted_at=step.name, reason=abort_reason,
                    duration_ms=max(0, int((self._now() - started) * 1000)),
                )

        # ★ 整体 ok 的判定：只要**有任何一步失败**，整条流水线就不算成功 ——
        #   即使失败的是非关键步骤（流程没被阻断，但确实有环节没做成）。
        #   若此处返回 ok=True，调用方会以为「一切都好」，
        #   而实际上「释放端口失败」这类问题被掩盖 —— 正是 D5 静默失败的形态。
        if any_failed:
            failed = [s for s in results if not s.ok]
            summary = '; '.join(f'{s.step}: {s.summary}' for s in failed)
            return PipelineResult(
                pipeline=self._name, ok=False, steps=tuple(results),
                aborted_at=None, reason=f'{len(failed)} 个步骤未成功: {summary}',
                duration_ms=max(0, int((self._now() - started) * 1000)),
            )

        return PipelineResult(
            pipeline=self._name, ok=True, steps=tuple(results),
            duration_ms=max(0, int((self._now() - started) * 1000)),
        )

    @staticmethod
    def _run_step(step: Step, context: Any) -> tuple[bool, str, str]:
        """执行单个步骤，归一化为 `(ok, reason, detail)`。

        三种返回形态都接受：
            · `OpResult`        → 取 ok / reason / detail
            · `None`            → 视为成功（方便写「无返回值的动作」）
            · 抛异常            → 视为失败，reason 记异常类型，detail 记文本

        ★ 异常时 reason 用异常类型名（短语），detail 用完整文本 ——
          理由同 `StepResult` 的字段分工：一行摘要 vs 详情。
        """
        try:
            outcome = step.fn(context)
        except BaseException as exc:  # noqa: BLE001
            return False, type(exc).__name__, str(exc)

        if outcome is None:
            return True, '', ''

        if isinstance(outcome, OpResult):
            if outcome.ok:
                return True, '', outcome.detail
            return False, outcome.reason or '未说明原因', outcome.detail

        # 步骤返回了不认识的东西 —— 不静默放过（它多半是写错了）
        return (False, '步骤返回值类型非法',
                f'{type(outcome).__name__}（应为 OpResult 或 None）')


def ok_step(name: str, detail: str = '') -> Step:
    """构造一个「永远成功」的步骤（测试与占位用）。"""
    return Step(name, lambda ctx: OpResult.success(detail))


def fail_step(name: str, reason: str, detail: str = '') -> Step:
    """构造一个「永远失败」的步骤（测试用）。"""
    return Step(name, lambda ctx: OpResult.failure(reason, detail))


__all__ = [
    'Pipeline',
    'PipelineResult',
    'Step',
    'StepFn',
    'StepResult',
    'fail_step',
    'ok_step',
]
