"""启动生产模式 —— 停止开发端口占用 → 确保 Redis → 启动生产服务 → 确认就绪。

═══════════════════════════════════════════════════════════════════
迁移来源：server_manager.py v5.40 `_start_prod()` / `_ensure_dev_stopped()`
═══════════════════════════════════════════════════════════════════

与 `StartDev` 高度对称，但有**三处关键差异**（都是安全相关，不可抹平）：

    ① **互斥对象相反**：生产模式要防的是「开发模式占着 5002/3000」。
       开发模式的服务是**裸进程**（没有 SCM 记录），所以互斥检查必须走
       **端口占用**而不是服务状态 —— 这是本模块与 `StartDev` 最大的不同。

    ② **Redis 是硬依赖**：开发模式下 Redis 缺失只是警告（后端可能不依赖），
       但生产模式下 Redis 缺失会让 ERP 直接不可用，因此**必须失败**。

    ③ **启动后要等就绪**：生产服务是 NSSM 托管的，`sc start` 返回时
       进程可能还没监听端口。旧实现等的是「服务状态 = RUNNING」，
       但 RUNNING 不等于「能接受请求」——本实现额外用 `HealthPort`
       探一次 HTTP，把「进程起来了」与「服务可用了」区分开。

═══════════════════════════════════════════════════════════════════
★ 为什么第 ① 步必须走端口而不是服务状态
═══════════════════════════════════════════════════════════════════

开发模式启动的后端/前端是 `subprocess.Popen` 出来的裸进程，
**不注册为 Windows 服务**，因此 `deps.service.state()` 对它们一无所知。

若照抄 `StartDev` 的「查服务状态」写法，会得到「开发模式没在跑」的
错误结论，进而直接启动生产 —— 两套进程抢同一个端口（v5.36 的事故形态）。

正确做法：查**生产端口**是否有非生产进程在监听。生产服务的进程
可以在启动后从 `snapshot()` 拿到 PID，与端口监听者比对，
**监听者不是生产服务自己的进程 = 开发残留** → 必须先清掉。

═══════════════════════════════════════════════════════════════════
⚠ 未完成部分（如实标注）
═══════════════════════════════════════════════════════════════════

旧实现里开发模式残留进程的清理方式是 `taskkill /PID`（依赖
`ProcessPort`）。本阶段 `ProcessPort` 已具备 `find_port_pids()` 与
`kill_tree()`，因此第 ① 步可以完整实现 —— 这是与 `StartDev` 的
③④ 步（依赖尚未实现的 `spawn()`）不同的地方。

但「按端口找 PID」在 `FakeProcess` 下需要测试显式配置，
否则默认返回空列表 —— 这意味着「开发残留」的场景在单测里
必须主动构造，不会自然出现。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ...domain.models import (
    MANAGED_NSSM_SERVICES,
    SERVICE_API,
    probes_for_service,
)
from ...domain.permissions import Action
from ...domain.readiness import POLICY_SERVICE_RUNNING, wait_until
from ...domain.results import OpResult, ServiceCmd
from ...domain.service_state import ServiceStatus
from ..auth.guard import ConfirmationToken, require
from ..pipeline import Pipeline, PipelineResult, Step
from .deps import Deps
from .stop_all import REDIS_SERVICES

#: ★ 逐字保留旧实现的步骤名（UI 进度条直接显示它们）
PROD_START_STEPS: tuple[str, ...] = (
    '停止开发模式',
    '检查Redis服务',
    '启动生产服务',
    '等待服务就绪',
    '完成',
)

#: 生产端口清单（从 deps.ports 取不到时的兜底默认值）
DEFAULT_PROD_PORTS: tuple[str, ...] = ('backend', 'frontend')


@dataclass
class StartProdContext:
    """生产模式启动的上下文。"""

    deps: Deps
    label: str = '生产模式'
    trace_id: str = ''
    killed_pids: tuple[int, ...] = ()
    started_services: tuple[str, ...] = ()
    ready_services: tuple[str, ...] = ()
    notes: list[str] = field(default_factory=list)


class StartProd:
    """启动生产模式（NSSM 托管服务 + Redis）。

    这是 L2 高危操作（切换运行模式），需要 Operator+ 与二次确认。
    """

    def __init__(self, deps: Deps) -> None:
        self._deps = deps

    @require(Action.SWITCH_MODE, target_arg='target')
    def execute(
        self,
        *,
        session: object,
        confirm: ConfirmationToken | None = None,
        event_bus: object = None,
        audit: object = None,
        target: str = 'prod',
        trace_id: str = '',
        label: str = '生产模式',
    ) -> OpResult:
        pipeline = self._build_pipeline()
        ctx = StartProdContext(deps=self._deps, label=label, trace_id=trace_id)

        result = pipeline.run(ctx, trace_id=trace_id)

        if result.ok:
            return OpResult.success(
                f'{label}已启动（{len(ctx.ready_services)} 个服务就绪）',
                duration_ms=result.duration_ms,
            )
        return OpResult.failure(
            result.reason or f'{label}启动失败',
            detail=self._describe_failure(result, ctx),
            duration_ms=result.duration_ms,
        )

    # ── 流水线构建 ────────────────────────────────────────────────

    def _build_pipeline(self) -> Pipeline:
        return Pipeline(
            'start_prod',
            [
                Step(PROD_START_STEPS[0], self._stop_dev_residual),
                Step(PROD_START_STEPS[1], self._ensure_redis),
                Step(PROD_START_STEPS[2], self._start_services),
                Step(PROD_START_STEPS[3], self._wait_ready),
                Step(PROD_START_STEPS[4], self._finish),
            ],
            clock=self._deps.clock,
            emit=self._deps.event_bus.emit,
        )

    # ── ① 清掉开发模式残留（★ 互斥防护）──────────────────────────

    def _stop_dev_residual(self, ctx: StartProdContext) -> OpResult:
        """清理开发模式占着生产端口的残留进程。

        ★ 判定口径：拿「生产端口上正在监听的 PID」减去「生产服务自己的
          进程 PID」。差集里的进程就是开发残留（或别的东西占了生产端口），
          两种都必须清掉 —— 否则生产服务起来后绑不上端口。

        ★ 清不干净 → 中止（critical）。这与 `StartDev` 的互斥防护等位：
          两套进程抢同一端口会互相杀，事故形态见 v5.36。
        """
        deps = ctx.deps
        own_pids = self._production_service_pids()
        intruders: list[int] = []
        #: 端口 → 占用者 PID（用于给出可读的失败原因）
        holders: list[str] = []

        for port_name in DEFAULT_PROD_PORTS:
            port = deps.ports.get(port_name)
            if not port:
                continue
            # ★ 只取 LISTENING：决定「杀谁」时必须用窄口径，
            #   否则会把「正在连出去」的客户端进程当做占用者杀掉
            pids = deps.process.find_port_pids(int(port), listening_only=True)
            for pid in pids:
                if pid in own_pids or pid in intruders:
                    continue
                intruders.append(pid)
                holders.append(f'{port_name}:{port} ← PID {pid}')

        if not intruders:
            ctx.notes.append('生产端口空闲')
            return OpResult.success('无需清理')

        killed: list[int] = []
        failures: list[str] = []
        for pid in intruders:
            result = deps.process.kill_tree(pid)
            if not result.ok:
                failures.append(f'PID {pid}: {result.error or "未知错误"}')
            elif result.targeted == 0:
                # ★ 「没找到可杀的目标」不是成功 —— 端口仍然被占。
                #   只断言 result.ok 会把这种情况当成清理成功（D5 静默失败的形态）。
                failures.append(f'PID {pid}: 未找到可终止的进程')
            else:
                killed.append(pid)

        ctx.killed_pids = tuple(killed)

        if failures:
            return OpResult.failure(
                '开发残留进程清理失败（保守中止，避免端口互抢）',
                detail=f'占用者: {"; ".join(holders)}|失败: {"; ".join(failures)}',
            )

        # ★ 再复查一次端口：与 `KillPort` 的第 ④ 步同一理由 ——
        #   `kill_tree` 返回成功时进程可能仍在「正在终止」状态，端口还没释放。
        remaining = self._recheck_ports()
        if remaining:
            return OpResult.failure(
                '端口清理后仍被占用（保守中止）',
                detail='残留: ' + '; '.join(remaining),
            )

        return OpResult.success(f'已清理 {len(killed)} 个残留进程')

    def _recheck_ports(self) -> list[str]:
        """复查生产端口是否真的空闲。返回残留描述（空表示已释放）。"""
        deps = self._deps
        own_pids = self._production_service_pids()
        remaining: list[str] = []
        for port_name in DEFAULT_PROD_PORTS:
            port = deps.ports.get(port_name)
            if not port:
                continue
            for pid in deps.process.find_port_pids(int(port), listening_only=True):
                if pid not in own_pids:
                    remaining.append(f'{port_name}:{port} ← PID {pid}')
        return remaining

    def _production_service_pids(self) -> set[int]:
        """取生产服务当前拥有的进程 PID。

        ★ 为什么要排除它们：生产服务正在运行时，它自己就占着生产端口。
          若不排除，每次「重启动生产」都会把自己的进程当成残留杀掉 ——
          变成「先自杀再启动」，行为诡异且会丢掉正在处理的请求。
        """
        deps = self._deps
        own: set[int] = set()
        for service in MANAGED_NSSM_SERVICES:
            pid = deps.service.pid(service.name)
            if pid:
                own.add(int(pid))
        return own

    # ── ② 检查 Redis（★ 这里是硬依赖）───────────────────────────

    def _ensure_redis(self, ctx: StartProdContext) -> OpResult:
        """确保 Redis 就绪；缺失即失败。

        ★ 与 `StartDev._ensure_redis` 的差异（有意保留，不是抄漏了）：
          开发模式 Redis 缺失 → 警告继续（后端可能不依赖缓存）
          生产模式 Redis 缺失 → **失败中止**（ERP 生产依赖缓存，
          带着没有缓存的状态启动生产比不启动更危险）
        """
        deps = ctx.deps
        missing: list[str] = []
        failures: list[str] = []

        for name in REDIS_SERVICES:
            status = deps.service.state(name)
            if status is ServiceStatus.ABSENT:
                missing.append(name)
                continue
            if status is ServiceStatus.RUNNING:
                continue

            result = deps.service.control(name, ServiceCmd.START)
            if not result.ok:
                failures.append(f'{name}: {result.reason}')

        if failures:
            return OpResult.failure('Redis 服务启动失败', '; '.join(failures))

        if len(missing) == len(REDIS_SERVICES):
            return OpResult.failure(
                'Redis 未安装',
                f'生产模式需要 Redis，未找到服务: {", ".join(missing)}',
            )

        if missing:
            ctx.notes.append(f'部分 Redis 未安装: {", ".join(missing)}')

        return OpResult.success('Redis 就绪')

    # ── ③ 启动生产服务 ────────────────────────────────────────────

    def _start_services(self, ctx: StartProdContext) -> OpResult:
        """启动 NSSM 托管的生产服务。

        ★ 只发启动请求、不在此等待 —— 等待统一交给下一步。
          （与 `StopAll` 的「请求/等待分离」同一结构，便于定位超时发生在哪。）
        """
        deps = ctx.deps
        started: list[str] = []
        failures: list[str] = []
        skipped: list[str] = []

        for service in MANAGED_NSSM_SERVICES:
            status = deps.service.state(service.name)
            if status is ServiceStatus.ABSENT:
                # ★ 未安装不是「启动失败」，但也不能当作成功 ——
                #   记录在 notes 里让用户知道这个服务没参与本次启动
                skipped.append(service.name)
                continue
            if status is ServiceStatus.RUNNING:
                started.append(service.name)
                continue

            result = deps.service.control(service.name, ServiceCmd.START)
            if result.ok:
                started.append(service.name)
            else:
                failures.append(f'{service.name}: {result.reason}')

        ctx.started_services = tuple(started)

        if skipped:
            ctx.notes.append(f'未安装（跳过）: {", ".join(skipped)}')
        if failures:
            return OpResult.failure('部分生产服务启动失败', '; '.join(failures))
        if not started:
            return OpResult.failure(
                '没有可启动的生产服务',
                f'全部未安装: {", ".join(skipped) or "无"}',
            )
        return OpResult.success(f'已请求启动: {", ".join(started)}')

    # ── ④ 等待就绪 ────────────────────────────────────────────────

    def _wait_ready(self, ctx: StartProdContext) -> OpResult:
        """等生产服务进入 RUNNING，再用 HTTP 探一次确认真的可用。

        ★ 两段式而不是一段式：服务状态 RUNNING 只说明**进程起来了**，
          不代表**端口在监听、请求能通**。旧实现只等到 RUNNING 就报
          「启动成功」，用户点开页面却连不上 —— 这是 D5 静默失败的一种：
          系统说了「成功」，但成功是假的。

        ★ HTTP 探活失败**不阻断**（降级为 notes）：
          NSSM 服务可能是不可 HTTP 的（如 erp-arq 是纯 worker，没有 HTTP 端口），
          强制探活会误报。状态确认通过即可，探活结果作为额外信息告知用户。

        ★ 探针只对 `SVC_API` 包含 nginx 探针 —— 由 `probes_for_service`
          承载该判定（迁移自旧 `need_web = name == _SVC_API`），
          本模块不复制这条领域规则。
        """
        deps = ctx.deps
        ready: list[str] = []
        failures: list[str] = []
        probe_notes: list[str] = []

        for service in MANAGED_NSSM_SERVICES:
            if service.name not in ctx.started_services:
                continue

            outcome = wait_until(
                lambda name=service.name: _is_running(deps, name),
                POLICY_SERVICE_RUNNING,
                clock=deps.clock.monotonic,
                sleep=deps.clock.sleep,
                observe=lambda name=service.name: deps.service.state(name).value,
            )
            if outcome.ok:
                ready.append(service.name)
            else:
                failures.append(
                    outcome.failure_reason(service.name) or f'{service.name} 未就绪'
                )
                continue

            # 状态已确认 → 再做一次 HTTP 探活（失败仅记 notes）
            for note in self._probe_http(service.name, ctx):
                probe_notes.append(note)

        ctx.ready_services = tuple(ready)
        ctx.notes.extend(probe_notes)

        if failures:
            return OpResult.failure(
                '生产服务未能就绪', '; '.join(failures),
            )
        return OpResult.success(f'已就绪: {", ".join(ready) or "无"}')

    def _probe_http(self, service_name: str, ctx: StartProdContext) -> list[str]:
        """对已确认 RUNNING 的服务做 HTTP 探活。返回给用户的备注行。

        ★ 端口缺失 → 明确说明「未探活」而不是「探活通过」。
          这在 FakeDeps（ports 为空）下就是常态，也是真实配置不完整时的实情。
        """
        deps = ctx.deps
        api_port = deps.ports.get('backend') or deps.ports.get('api')
        web_port = deps.ports.get('frontend') or deps.ports.get('web')
        if not api_port or not web_port:
            return [f'{service_name} 未做 HTTP 探活（配置中缺端口）']

        notes: list[str] = []
        try:
            probes = probes_for_service(service_name, int(api_port), int(web_port))
        except ValueError as exc:
            return [f'{service_name} 探针构造失败: {exc}']

        for probe in probes:
            sample = deps.health.probe(probe)
            if sample.ok:
                notes.append(f'{probe.name} 探活通过（{sample.latency_ms:.0f}ms）')
            else:
                notes.append(f'{probe.name} 探活未通过: {sample.detail}')
        return notes

    # ── ⑤ 完成 ────────────────────────────────────────────────────

    def _finish(self, ctx: StartProdContext) -> OpResult:
        return OpResult.success('；'.join(ctx.notes) if ctx.notes else '完成')

    @staticmethod
    def _describe_failure(result: PipelineResult, ctx: StartProdContext) -> str:
        parts = [f'{s.step}: {s.summary}' for s in result.steps if not s.ok]
        if result.aborted_at:
            parts.append(f'（已中止于「{result.aborted_at}」，后续步骤未执行）')
        if ctx.notes:
            parts.append('备注: ' + '；'.join(ctx.notes))
        return '; '.join(parts)


def build_start_prod(deps: Deps) -> StartProd:
    """工厂函数（供 container 使用）。"""
    return StartProd(deps)


def _is_running(deps: Deps, name: str) -> bool:
    """服务是否确认处于 RUNNING。

    ★ 用 `ServiceStatus.RUNNING` 严格比较，而不是 `'RUNNING' in state` ——
      STOP_PENDING 的文本里也可能带 RUNNING（视系统语言），
      子串判定会把「正在停」当成「已就绪」（v5.39 审查 #1 的同一类坑）。
    """
    return deps.service.state(name) is ServiceStatus.RUNNING


__all__ = [
    'DEFAULT_PROD_PORTS',
    'PROD_START_STEPS',
    'StartProd',
    'StartProdContext',
    'build_start_prod',
]
