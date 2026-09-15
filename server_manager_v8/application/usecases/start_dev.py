"""启动开发模式 —— 5 步流水线（★ 对齐旧 `_startup_steps` 的步骤名）。

═══════════════════════════════════════════════════════════════════
迁移来源：server_manager.py v5.40
═══════════════════════════════════════════════════════════════════

旧实现把 5 步硬编码在两个方法里接力（`_start_dual_worker` → `_start_dual_thread`），
且进度存在 `self._startup_progress` 上（两次启动会互相覆盖）。

新实现把步骤变成**声明式数据**，且状态全在局部变量里：

    ① 停止生产模式   ← `_ensure_production_stopped` 的编排
    ② 检查Redis服务  ← `_ensure_redis_ready` 的编排
    ③ 启动后端服务
    ④ 启动前端服务
    ⑤ 完成

★ 步骤名**逐字保留**旧实现 `_startup_steps` 的字符串 ——
  它们直接显示在 UI 进度条上，改动等于改用户可见文案。

═══════════════════════════════════════════════════════════════════
★ 核心安全语义（不可回退）
═══════════════════════════════════════════════════════════════════

第 ① 步是**互斥防护**：启动开发模式前必须确认生产已停。
若这一步失败（含「状态未知、无法确认已停」），整条流水线**必须中止** ——
不能继续启动后端，否则开发模式抢占 5002/3000 与仍在跑的生产互杀。

这个事故 v5.36 堵住、v5.39 又因 sc 输出子串误判换个入口复发、v5.40 才修好。
本实现通过把第 ① 步标为 `critical=True`（默认）来保证中止。

═══════════════════════════════════════════════════════════════════
⚠ 本阶段未完成的部分（如实标注，不假装成功）
═══════════════════════════════════════════════════════════════════

③ ④ 两步（启动后端/前端）需要 `ProcessPort.spawn()`，而该能力
**当前 Protocol 里还没有**（P2 的 process_win 只实现了「终止」方向）。

因此这两步返回明确的失败（「未接入」），而不是假装成功 ——
假装成功会让 UI 显示「已启动」但实际什么都没有，比报错更糟。
`ProcessPort.spawn()` 应在 P4 随进程启动需求一起补上。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ...domain.models import MANAGED_NSSM_SERVICES
from ...domain.permissions import Action
from ...domain.results import OpResult, ServiceCmd
from ...domain.service_state import ServiceStatus
from ..auth.guard import ConfirmationToken, require
from ..pipeline import Pipeline, PipelineResult, Step
from .deps import Deps
from .stop_all import REDIS_SERVICES, StopAll, StopAllContext

#: ★ 逐字保留旧实现的步骤名（UI 进度条直接显示它们）
STARTUP_STEPS: tuple[str, ...] = (
    '停止生产模式',
    '检查Redis服务',
    '启动后端服务',
    '启动前端服务',
    '完成',
)

#: 需要「已停止」判定的状态集合
#:
#: ★ 「未知」**不在**其中 —— 它算运行中（保守方向）
_STOPPED_STATES = (ServiceStatus.STOPPED, ServiceStatus.ABSENT)


@dataclass
class StartDevContext:
    """开发模式启动的上下文。"""

    deps: Deps
    label: str = '开发模式'
    trace_id: str = ''
    stopped_prod: bool = False
    backend_pid: int | None = None
    frontend_pid: int | None = None
    notes: list[str] = field(default_factory=list)


class StartDev:
    """启动开发模式（后端 + 前端 + Redis）。

    这是 L2 高危操作（切换运行模式），需要 Operator+ 与二次确认。
    """

    def __init__(self, deps: Deps, *, stop_all: StopAll | None = None) -> None:
        self._deps = deps
        self._stop_all = stop_all or StopAll(deps)

    @require(Action.SWITCH_MODE, target_arg='target')
    def execute(
        self,
        *,
        session: object,
        confirm: ConfirmationToken | None = None,
        event_bus: object = None,
        audit: object = None,
        target: str = 'dev',
        trace_id: str = '',
        label: str = '开发模式',
    ) -> OpResult:
        pipeline = self._build_pipeline()
        ctx = StartDevContext(deps=self._deps, label=label, trace_id=trace_id)

        result = pipeline.run(ctx, trace_id=trace_id)

        if result.ok:
            return OpResult.success(
                f'{label}已启动'
                + (f'（后端 PID {ctx.backend_pid}）' if ctx.backend_pid else ''),
                duration_ms=result.duration_ms,
            )
        return OpResult.failure(
            result.reason or f'{label}启动失败',
            detail=self._describe_failure(result, ctx),
            duration_ms=result.duration_ms,
        )

    def _build_pipeline(self) -> Pipeline:
        """构建 5 步流水线（步骤名与旧实现逐字一致）。"""
        return Pipeline(
            'start_dev',
            [
                Step(STARTUP_STEPS[0], self._stop_production),
                Step(STARTUP_STEPS[1], self._ensure_redis),
                Step(STARTUP_STEPS[2], self._start_backend),
                Step(STARTUP_STEPS[3], self._start_frontend),
                Step(STARTUP_STEPS[4], self._finish),
            ],
            clock=self._deps.clock,
            emit=self._deps.event_bus.emit,
        )

    # ── ① 停止生产模式（★ 互斥防护，最关键的一步）──────────────

    def _stop_production(self, ctx: StartDevContext) -> OpResult:
        """确认生产已停。

        ★ 用 `StopAll` 复用停止流程，但**不需要** Redis 也停 ——
          开发模式同样需要 Redis（它只与生产服务互斥，不与自己互斥）。
        """
        deps = ctx.deps

        # 先快速判定：生产服务是否本来就没在跑？
        # 若都不在跑，跳过整个停止流程（省掉挂守卫等副作用）
        if not _any_production_running(deps):
            ctx.stopped_prod = False
            ctx.notes.append('生产服务未运行，无需停止')
            return OpResult.success('生产未运行')

        # 有生产在跑 → 走完整停止流程（含守卫、确认等待）
        stop = StopAll(deps)
        stop_ctx = StopAllContext(deps=deps, trace_id=ctx.trace_id)
        result = stop._build_pipeline(stop_redis=False, target='prod').run(
            stop_ctx, trace_id=ctx.trace_id,
        )
        if not result.ok:
            # ★ 中止语义：这一步失败，后面一步都不能执行
            return OpResult.failure(
                '无法停止生产模式（保守中止，避免互杀）',
                detail='; '.join(
                    f'{s.step}: {s.summary}' for s in result.steps if not s.ok
                ),
            )

        ctx.stopped_prod = True
        ctx.notes.append('已自动停止生产模式')
        return OpResult.success('生产模式已停')

    # ── ② 检查 Redis ──────────────────────────────────────────────

    def _ensure_redis(self, ctx: StartDevContext) -> OpResult:
        """确保 Redis 服务就绪。

        ★ Redis 未安装是**警告而非失败** —— 旧实现的行为是
          「记 WARNING 继续」（`Redis 未安装，请在配置中指定路径或安装`）。
          开发模式的后端是否依赖 Redis 取决于配置，直接失败会让
          没装 Redis 的机器完全无法启动开发模式。
        """
        deps = ctx.deps
        missing: list[str] = []
        started: list[str] = []

        for name in REDIS_SERVICES:
            status = deps.service.state(name)
            if status is ServiceStatus.ABSENT:
                missing.append(name)
                continue
            if status is ServiceStatus.RUNNING:
                continue

            result = deps.service.control(name, ServiceCmd.START)
            if result.ok:
                started.append(name)
            else:
                # 单个 Redis 启不起来不算致命（另一个可能可用）
                ctx.notes.append(f'{name} 启动失败: {result.reason}')

        if missing and len(missing) == len(REDIS_SERVICES):
            ctx.notes.append('Redis 服务未安装，后端可能无法使用缓存')
            return OpResult.success('Redis 未安装（继续）')

        detail = f'已启动: {", ".join(started)}' if started else '全部就绪'
        return OpResult.success(detail)

    # ── ③ 启动后端 ────────────────────────────────────────────────

    def _start_backend(self, ctx: StartDevContext) -> OpResult:
        """启动开发模式后端（⚠ 依赖尚未实现的 `ProcessPort.spawn()`）。"""
        return OpResult.failure(
            '开发模式后端启动未接入',
            'ProcessPort.spawn() 尚未实现（P2 只做了终止方向），需 P4 补齐',
        )

    # ── ④ 启动前端 ────────────────────────────────────────────────

    def _start_frontend(self, ctx: StartDevContext) -> OpResult:
        """启动开发模式前端（⚠ 同 ③）。"""
        return OpResult.failure(
            '开发模式前端启动未接入',
            'ProcessPort.spawn() 尚未实现，需 P4 补齐',
        )

    # ── ⑤ 完成 ────────────────────────────────────────────────────

    def _finish(self, ctx: StartDevContext) -> OpResult:
        return OpResult.success('；'.join(ctx.notes) if ctx.notes else '完成')

    @staticmethod
    def _describe_failure(result: PipelineResult, ctx: StartDevContext) -> str:
        parts = [f'{s.step}: {s.summary}' for s in result.steps if not s.ok]
        if result.aborted_at:
            parts.append(f'（已中止于「{result.aborted_at}」，后续步骤未执行）')
        if ctx.notes:
            parts.append('备注: ' + '；'.join(ctx.notes))
        return '; '.join(parts)


def _any_production_running(deps: Deps) -> bool:
    """是否任一生产服务（含「未知」）处于运行中。

    ★ 「未知」算运行中（保守方向）—— 确认不了停止就不能继续启动。
      这是 A5 安全性质在编排层的体现。
    """
    for service in MANAGED_NSSM_SERVICES:
        if deps.service.state(service.name).is_conservatively_running:
            return True
    return False


def build_start_dev(deps: Deps) -> StartDev:
    return StartDev(deps)


__all__ = [
    'STARTUP_STEPS',
    'StartDev',
    'StartDevContext',
    'build_start_dev',
]
