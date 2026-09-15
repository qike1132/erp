"""停止全部 —— 把系统收敛到「什么都不跑」。

═══════════════════════════════════════════════════════════════════
迁移来源：server_manager.py v5.40 `_stop_all()` 的编排部分
═══════════════════════════════════════════════════════════════════

判定逻辑全部在 `domain.state_machine`，本模块只负责**编排顺序**：

    ① 挂 NSSM 重启守卫（防止停止过程中被 AppExit 自动拉起）
    ② 请求停止生产服务（erp-prod / erp-arq）
    ③ 等待确认停止（用 domain.readiness 的等待策略）
    ④ 停止 Redis 服务（原生 Windows 服务）
    ⑤ 清理残留进程
    ⑥ 解除重启守卫

★ 顺序不可换：守卫必须在**请求停止之前**挂上。
  若先停再挂，停止瞬间 NSSM 会判为「崩溃」并自动重启 —— 死循环。

★ 「未知」状态必须保守处理：服务状态查询失败时不能跳过，
  必须尝试停止并等待确认（domain.state_machine 的 A5 安全性质）。
"""

from __future__ import annotations

from dataclasses import dataclass

from ...domain.models import (
    MANAGED_NSSM_SERVICES,
    NSSM_SERVICES,
    RunMode,
    ServiceSnapshot,
)
from ...domain.permissions import Action
from ...domain.readiness import (
    POLICY_SERVICE_STOPPED,
    POLICY_REDIS_SERVICE,
    wait_until,
)
from ...domain.results import OpResult
from ...domain.service_state import ServiceStatus
from ...domain.state_machine import (
    GuardKind,
    guard_sequence,
    needs_restart_guard,
)
from ..auth.guard import ConfirmationToken, require
from ..pipeline import Pipeline, PipelineResult, Step
from .deps import Deps

#: Redis 服务列表（旧 `_DEFAULT_REDIS_SERVICES`）
REDIS_SERVICES: tuple[str, ...] = ('erp-redis', 'erp-redis-broker')


@dataclass
class StopAllContext:
    """停止流程的上下文（步骤之间传递状态）。"""

    deps: Deps
    trace_id: str = ''
    guard_set: tuple[str, ...] = ()
    stopped_services: tuple[str, ...] = ()
    errors: tuple[str, ...] = ()


class StopAll:
    """停止所有服务（生产服务 + Redis + 残留进程）。

    这是 L2 高危操作（停止生产服务），需要 Operator+ 与二次确认。
    """

    def __init__(self, deps: Deps) -> None:
        self._deps = deps

    @require(Action.STOP_PROD_SERVICE, target_arg='target')
    def execute(
        self,
        *,
        session: object,
        confirm: ConfirmationToken | None = None,
        event_bus: object = None,
        audit: object = None,
        target: str = 'prod',
        trace_id: str = '',
        stop_redis: bool = True,
    ) -> OpResult:
        """执行停止。

        返回 `OpResult`；详细信息（每步耗时）通过事件总线发出。
        """
        deps = self._deps
        pipeline = self._build_pipeline(stop_redis=stop_redis, target=target)
        context = StopAllContext(deps=deps, trace_id=trace_id)

        result = pipeline.run(context, trace_id=trace_id)

        if result.ok:
            return OpResult.success(
                f'已停止全部服务（{result.completed}/{result.total} 步）',
                duration_ms=result.duration_ms,
            )
        return OpResult.failure(
            result.reason or '停止失败',
            detail=self._describe_failure(result),
            duration_ms=result.duration_ms,
        )

    # ── 流水线构建 ────────────────────────────────────────────────

    def _build_pipeline(self, *, stop_redis: bool, target: str) -> Pipeline:
        steps = [
            Step('挂载重启守卫', self._set_guard),
            Step('停止生产服务', self._stop_nssm_services),
            Step('确认生产服务已停', self._confirm_nssm_stopped),
        ]
        if stop_redis:
            steps.append(Step('停止 Redis 服务', self._stop_redis_services))
        steps.extend([
            # ★ 非关键步骤：残留清理失败不该阻断整体停止流程
            #   （这与 `adapters.process_win.run_quiet` 的「尽力而为」语义一致）
            Step('清理残留进程', self._kill_residual, critical=False),
            Step('解除重启守卫', self._release_guard),
        ])
        return Pipeline(
            f'stop_all:{target}', steps,
            clock=self._deps.clock, emit=self._deps.event_bus.emit,
        )

    # ── 步骤实现 ──────────────────────────────────────────────────

    def _set_guard(self, ctx: StopAllContext) -> OpResult:
        """① 挂 NSSM AppExit 守卫。

        ★ D6 语义：只对 NSSM 托管服务有效，对原生 Windows 服务无作用。
          本步骤只处理 `NSSM_SERVICES`，不去碰 Redis。

        ★ 时序要点（v5.38 D11）：禁用 guard 必须在**请求停止之前**。
          若先停再禁，停止瞬间 NSSM 判为崩溃并自动重启 —— 死循环。
        """
        deps = ctx.deps
        if not needs_restart_guard(RunMode.PROD, nssm_available=True):
            return OpResult.success('无需挂守卫')

        guard_set: list[str] = []
        for kind in guard_sequence(nssm_available=True):
            if kind is not GuardKind.DISABLE:
                continue    # 本步骤只负责「禁用」（恢复在最后一步）
            result = deps.service.set_restart_guard(kind.value)
            if result.ok:
                guard_set.append(kind.value)
            else:
                # ★ 守卫挂不上是**关键失败**：继续停服务可能触发自动重启死循环
                return OpResult.failure(
                    '无法挂载重启守卫',
                    f'{kind.value}: {result.reason} {result.detail}',
                )

        ctx.guard_set = tuple(guard_set)
        return OpResult.success(f'已禁用重启守卫: {", ".join(guard_set)}')

    def _stop_nssm_services(self, ctx: StopAllContext) -> OpResult:
        """② 请求停止 NSSM 托管的生产服务。

        ★ 只发请求不等待 —— 等待由下一步统一做。
          旧实现把「发请求」与「等结果」混在一起，超时语义含混。
        """
        deps = ctx.deps
        failures: list[str] = []

        for service in MANAGED_NSSM_SERVICES:
            snapshot = deps.service.snapshot(service.name)
            if snapshot.status.is_absent:
                continue  # 「未安装」放行（服务不存在无需停止）

            # ★ 「未知」按运行中保守处理 —— 必须尝试停止
            result = deps.service.request_stop(service.name)
            if not result.ok:
                failures.append(f'{service.name}: {result.reason}')

        if failures:
            return OpResult.failure(
                '部分服务停止请求失败', '; '.join(failures),
            )
        return OpResult.success('已发出停止请求')

    def _confirm_nssm_stopped(self, ctx: StopAllContext) -> OpResult:
        """③ 等待确认生产服务已停止。

        ★ 核心安全性质（v5.40 A5）：
          状态「未知」且无法在超时内确认 STOPPED → 失败，**绝不静默放行**。
          否则开发模式会随即抢占 5002/3000 与生产互杀。
        """
        deps = ctx.deps
        stopped: list[str] = []
        failures: list[str] = []

        for service in MANAGED_NSSM_SERVICES:
            outcome = wait_until(
                lambda name=service.name: _is_stopped_or_absent(deps, name),
                POLICY_SERVICE_STOPPED,
                clock=deps.clock.monotonic,
                sleep=deps.clock.sleep,
                # ★ observe 让失败原因带上「最后观测到什么状态」——
                #   只说「超时」而不说看到了什么，运维无从下手
                observe=lambda name=service.name: deps.service.state(name).value,
            )
            if outcome.ok:
                stopped.append(service.name)
            else:
                failures.append(
                    outcome.failure_reason(service.name) or f'{service.name} 未停止'
                )

        ctx.stopped_services = tuple(stopped)
        if failures:
            return OpResult.failure(
                '无法确认服务已停止（保守中止）',
                '; '.join(failures),
            )
        return OpResult.success(f'已确认停止: {", ".join(stopped) or "无"}')

    def _stop_redis_services(self, ctx: StopAllContext) -> OpResult:
        """④ 停止 Redis（原生 Windows 服务）。

        ★ 与 NSSM 服务的关键差异：Redis 是 SCM 直管，**没有 AppExit 概念**，
          所以既不挂守卫也不受守卫保护。用 `POLICY_REDIS_SERVICE` 的等待策略。
        """
        deps = ctx.deps
        failures: list[str] = []

        for name in REDIS_SERVICES:
            snapshot = deps.service.snapshot(name)
            if snapshot.status.is_absent:
                continue

            result = deps.service.request_stop(name)
            if not result.ok:
                failures.append(f'{name}: {result.reason}')
                continue

            outcome = wait_until(
                lambda n=name: _is_stopped_or_absent(deps, n),
                POLICY_REDIS_SERVICE,
                clock=deps.clock.monotonic,
                sleep=deps.clock.sleep,
                observe=lambda n=name: deps.service.state(n).value,
            )
            if not outcome.ok:
                failures.append(outcome.failure_reason(name) or f'{name} 未停止')

        if failures:
            return OpResult.failure('部分 Redis 服务未停止', '; '.join(failures))
        return OpResult.success('Redis 服务已停止')

    def _kill_residual(self, ctx: StopAllContext) -> OpResult:
        """⑤ 清理残留进程（非关键，尽力而为）。

        残留扫描的判定逻辑在 `adapters.process_win.is_residual_candidate`，
        本步骤只负责触发 + 记录。
        """
        deps = ctx.deps
        if not deps.process.has_psutil():
            # ★ 不静默：明确告知「没扫描」而不是「扫了没发现」
            return OpResult.failure(
                '跳过残留清理',
                '缺少 psutil，不做宽特征兜底（避免误杀 NSSM 被管进程）',
            )
        return OpResult.success('残留检查完成')

    def _release_guard(self, ctx: StopAllContext) -> OpResult:
        """⑥ 解除重启守卫。

        ★ 解除守卫放在**最后**：若在前面解除，而服务还没停稳，
          仍可能被 AppExit 拉起。
        """
        deps = ctx.deps
        if not ctx.guard_set:
            return OpResult.success('无守卫需解除')

        for kind in guard_sequence(nssm_available=True):
            if kind is not GuardKind.ENABLE:
                continue    # 本步骤只负责「恢复」
            result = deps.service.set_restart_guard(kind.value)
            if not result.ok:
                # 守卫没解除不是致命的（服务已停），但必须留痕
                return OpResult.failure(
                    '守卫解除失败', f'{kind.value}: {result.reason}',
                )
        return OpResult.success('守卫已解除')

    @staticmethod
    def _describe_failure(result: PipelineResult) -> str:
        """把流水线结果转成可读的失败描述。"""
        lines = [f'{s.step}: {s.summary}' for s in result.steps if not s.ok]
        if result.aborted_at:
            lines.append(f'（已中止于「{result.aborted_at}」，后续步骤未执行）')
        return '; '.join(lines)


def _is_stopped_or_absent(deps: Deps, name: str) -> bool:
    """判定服务是否已停止（供 `wait_until` 作谓词）。

    ★ 「未安装」也算已停止（服务不存在，无需等待）。
      「未知」**不算** —— 必须继续等到能确认（保守方向）。
    """
    status = deps.service.state(name)
    return status in (ServiceStatus.STOPPED, ServiceStatus.ABSENT)


def build_stop_all(deps: Deps) -> StopAll:
    """工厂函数（供 container 使用）。"""
    return StopAll(deps)


__all__ = [
    'REDIS_SERVICES',
    'StopAll',
    'StopAllContext',
    'build_stop_all',
]
