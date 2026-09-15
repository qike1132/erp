"""切换运行模式 —— 统一入口（生产 ⇄ 开发）。

═══════════════════════════════════════════════════════════════════
迁移来源：server_manager.py v5.40 `_switch_mode()` / `_on_mode_change()`
═══════════════════════════════════════════════════════════════════

旧实现里「切到开发」与「切到生产」走两条完全不同的代码路径，
但**前置检查是同构的**：

    1. 查当前真实模式（不是查 self._mode 那个可能过期的缓存值）
    2. 若已在目标模式 → 直接返回（幂等，不重复操作）
    3. 否则：先停互斥模式，再启动目标模式

第 1 步是旧实现踩过的坑：`self._mode` 是内存里的意图值，用户直接
用 `sc stop` 停了服务后，`self._mode` 还是 `'prod'` —— 据此判断
「已经是生产模式了，不用动」就会得到错误结论。**真实状态必须重新探测**。

═══════════════════════════════════════════════════════════════════
★ 本模块的定位：编排器，不重复实现停止/启动细节
═══════════════════════════════════════════════════════════════════

切换 = 「必要时停 A」+「启动 B」。这两件事 `StopAll` / `StartDev` /
`StartProd` 已经实现，本模块**只做三件事**：

    ① 探测当前真实模式（`detect_mode()`）
    ② 幂等判定（已在目标模式则跳过）
    ③ 委派给对应的用例

★ 绝不在此复制「挂守卫 / 等状态」这类细节 —— 一旦复制，
  修 `StopAll` 的守卫时序就得记得同步改这里，注释里也说不出谁才是权威。

═══════════════════════════════════════════════════════════════════
幂等的边界（如实登记，这不是「完美幂等」）
═══════════════════════════════════════════════════════════════════

「已在目标模式」的判定基于**服务状态 + 端口占用**的瞬时快照，因此：

    · 生产已 RUNNING 但端口还没监听 → 判定为「已在生产」→ 不会重复启动
      （这是期望行为：重复启动 NSSM 服务是空操作，但会污染审计日志）
    · 开发进程占着端口但服务没装 → 判定为「已在开发」→ 不会重复启动
    · 两套同时部分存在（异常残留）→ 判定为冲突，走完整停止流程（保守方向）

★ 第三种情况是刻意保守的：宁可多停一次，不可留下两套进程抢端口。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ...domain.models import MANAGED_NSSM_SERVICES, RunMode
from ...domain.permissions import Action
from ...domain.results import OpResult
from ...domain.service_state import ServiceStatus
from ..auth.guard import ConfirmationToken, require
from .deps import Deps
from .start_dev import StartDev, StartDevContext
from .start_prod import StartProd, StartProdContext
from .stop_all import StopAll, StopAllContext

#: 探测开发模式时查的端口名（与 `start_prod.DEFAULT_PROD_PORTS` 同源）
DEV_PROBE_PORTS: tuple[str, ...] = ('backend', 'frontend')


@dataclass
class ModeSnapshot:
    """当前真实模式的探测结果。"""

    mode: RunMode = RunMode.NONE
    prod_services_running: tuple[str, ...] = ()
    prod_services_unknown: tuple[str, ...] = ()
    dev_port_holders: tuple[int, ...] = ()
    notes: list[str] = field(default_factory=list)

    @property
    def is_conflicting(self) -> bool:
        """是否两套同时存在（异常残留，需要清场）。"""
        return bool(self.prod_services_running) and bool(self.dev_port_holders)

    @property
    def ambiguous(self) -> bool:
        """是否存在「状态未知」导致模式判定不确定。

        ★ 未知时不能宣称「已在目标模式」—— 那样会跳过必要的停止，
          把互杀风险留给运行时。
        """
        return bool(self.prod_services_unknown)


@dataclass
class SwitchModeContext:
    """切换流程的上下文。"""

    deps: Deps
    target: RunMode = RunMode.PROD
    trace_id: str = ''
    before: RunMode = RunMode.NONE
    skipped: bool = False
    notes: list[str] = field(default_factory=list)


class SwitchMode:
    """切换运行模式。

    这是 L2 高危操作（切换运行模式），需要 Operator+ 与二次确认。
    """

    def __init__(self, deps: Deps) -> None:
        self._deps = deps

    @require(Action.SWITCH_MODE)
    def execute(
        self,
        *,
        session: object,
        confirm: ConfirmationToken | None = None,
        event_bus: object = None,
        audit: object = None,
        mode: str = 'prod',
        trace_id: str = '',
    ) -> OpResult:
        """切换到 `mode`（'prod' / 'dev' / 'dual_dev'）。

        ★ 参数名是 `mode` 而不是 `target` —— 与 `@require` 的 `target_arg`
          无关（本操作的目标是模式本身，不是某个服务/端口），
          因此守卫只做权限 + 确认检查，不比对名称。
        """
        deps = self._deps
        target = _parse_mode(mode)
        if target is None:
            # ★ 非法参数是调用方的编程错误，但不该抛出（UI 会传用户输入）
            return OpResult.failure(
                '无效的目标模式', f'期望 prod / dev，得到 {mode!r}',
            )

        ctx = SwitchModeContext(deps=deps, target=target, trace_id=trace_id)

        snapshot = detect_mode(deps)
        ctx.before = snapshot.mode
        ctx.notes.extend(snapshot.notes)

        # ── 幂等：已在目标模式且没有冲突残留 → 不重复操作 ──
        if snapshot.mode is target and not snapshot.is_conflicting and not snapshot.ambiguous:
            ctx.skipped = True
            return OpResult.success(
                f'已经是{target.label}，无需切换',
            )

        # ── 有未知状态：保守中止，不擅自切换 ──
        if snapshot.ambiguous:
            return OpResult.failure(
                '无法确认当前模式（保守中止）',
                detail=(f'服务状态未知: {", ".join(snapshot.prod_services_unknown)}；'
                        f'在确认不了当前状态时切换模式可能造成互杀'),
            )

        # ── 委派给对应用例 ──
        if target is RunMode.PROD:
            return self._to_prod(ctx, session=session, confirm=confirm,
                                 event_bus=event_bus, audit=audit)
        return self._to_dev(ctx, session=session, confirm=confirm,
                            event_bus=event_bus, audit=audit)

    # ── 切换到生产 ────────────────────────────────────────────────

    def _to_prod(self, ctx: SwitchModeContext, *, session: object,
                 confirm: ConfirmationToken | None, event_bus: object,
                 audit: object) -> OpResult:
        """生产模式：`StartProd` 的第 ① 步已经包含「清开发残留」，
        因此不需要在此额外调 `StopAll`。

        ★ 这是有意的委派而不是遗漏：若在这里再停一次，
          会出现「先全面停 → 再启动时又清一遍端口」的重复工作，
          而且两次停止的失败语义不同会互相覆盖（一次成功一次失败 = 结果不明）。
        """
        del confirm, event_bus, audit    # 已由 @require 检查；子用例是内部调用
        result = self._run_start_prod(ctx)
        if result.ok:
            return OpResult.success(
                f'已从{ctx.before.label}切换到生产模式',
                duration_ms=result.duration_ms,
            )
        return OpResult.failure(
            result.reason or '切换到生产模式失败',
            detail=_with_notes(result.detail, ctx.notes),
            duration_ms=result.duration_ms,
        )

    def _run_start_prod(self, ctx: SwitchModeContext) -> OpResult:
        """调 `StartProd` 的内部执行（绕过权限装饰器）。

        ★ 为什么要绕过：`SwitchMode.execute` 已经在 `@require(SWITCH_MODE)`
          下放行了，若直接调 `StartProd.execute(session=...)`，
          会**再查一次权限**（无害）但更重要的是**再要一次确认令牌** ——
          而切换场景下用户只确认了一次。两次要求确认是糟糕的体验，
          且在 UI 上表现成「确认后没反应」（第二个弹窗被上层忽略）。

        实现方式是直接调它的流水线（与 `StartDev._stop_production`
        复用 `StopAll._build_pipeline` 同一手法）。
        """
        deps = ctx.deps
        start = StartProd(deps)
        prod_ctx = StartProdContext(deps=deps, label='生产模式', trace_id=ctx.trace_id)
        pipeline_result = start._build_pipeline().run(prod_ctx, trace_id=ctx.trace_id)
        if pipeline_result.ok:
            return OpResult.success(
                f'{len(prod_ctx.ready_services)} 个服务就绪',
                duration_ms=pipeline_result.duration_ms,
            )
        return OpResult.failure(
            pipeline_result.reason or '生产模式启动失败',
            detail=start._describe_failure(pipeline_result, prod_ctx),
            duration_ms=pipeline_result.duration_ms,
        )

    # ── 切换到开发 ────────────────────────────────────────────────

    def _to_dev(self, ctx: SwitchModeContext, *, session: object,
                confirm: ConfirmationToken | None, event_bus: object,
                audit: object) -> OpResult:
        """开发模式：`StartDev` 的第 ① 步包含「停生产」且是 critical，
        同一理由，不在此额外编排。"""
        del confirm, event_bus, audit
        deps = ctx.deps
        start = StartDev(deps)
        dev_ctx = StartDevContext(deps=deps, label='开发模式', trace_id=ctx.trace_id)
        pipeline_result = start._build_pipeline().run(dev_ctx, trace_id=ctx.trace_id)

        if pipeline_result.ok:
            return OpResult.success(
                f'已从{ctx.before.label}切换到开发模式',
                duration_ms=pipeline_result.duration_ms,
            )
        return OpResult.failure(
            pipeline_result.reason or '切换到开发模式失败',
            detail=_with_notes(
                start._describe_failure(pipeline_result, dev_ctx), ctx.notes,
            ),
            duration_ms=pipeline_result.duration_ms,
        )


def _parse_mode(mode: str) -> RunMode | None:
    """把用户输入的模式字符串解析为 RunMode。

    ★ 同时接受 'dev' 与 'dual_dev'（旧代码里两个写法都出现过），
      但**只返回 DUAL_DEV** —— 不给同一个概念造出两个枚举值。
    """
    normalized = str(mode).strip().lower()
    if normalized in ('prod', 'production'):
        return RunMode.PROD
    if normalized in ('dev', 'dual_dev', 'development'):
        return RunMode.DUAL_DEV
    return None


def detect_mode(deps: Deps) -> ModeSnapshot:
    """探测当前**真实**运行模式（不信任何缓存值）。

    判定顺序（有意的先后）：
        ① 未知服务优先 —— 状态查不出来时不做任何「已在某模式」的结论
        ② 生产服务 RUNNING → PROD 候选
        ③ 生产端口被占 → DUAL_DEV 候选（开发模式的裸进程不注册为服务）
        ④ 两者都有 → CONFLICT（保守：调用方会走完整停止流程）

    ★ 为什么不看「Redis 在不在跑」：Redis 两种模式都需要，
      它不能区分模式（旧实现曾用它判断，是错的）。
    """
    snap = ModeSnapshot()
    deps_ = deps

    running: list[str] = []
    unknown: list[str] = []
    for service in MANAGED_NSSM_SERVICES:
        status = deps_.service.state(service.name)
        if status is ServiceStatus.UNKNOWN:
            unknown.append(service.name)
        elif status is ServiceStatus.RUNNING or status is ServiceStatus.PENDING:
            running.append(service.name)

    snap.prod_services_running = tuple(running)
    snap.prod_services_unknown = tuple(unknown)

    holders: list[int] = []
    for port_name in DEV_PROBE_PORTS:
        port = deps_.ports.get(port_name)
        if not port:
            continue
        # ★ 窄口径：只算 LISTENING 的占用者。
        #   用 LISTENING_OR_ESTABLISHED 会把「正在连后端」的客户端也算进来，
        #   导致任何时刻都判定「端口被占」= 永远认为开发模式在跑。
        for pid in deps_.process.find_port_pids(int(port), listening_only=True):
            if pid not in holders:
                holders.append(pid)
    snap.dev_port_holders = tuple(holders)

    if unknown and not running and not holders:
        # 状态未知且无其它证据 → 不做结论（由调用方保守中止）
        snap.mode = RunMode.NONE
        snap.notes.append(f'服务状态未知: {", ".join(unknown)}')
        return snap

    if running and holders:
        snap.mode = RunMode.PROD      # 有服务在跑，按生产处理（保守）
        snap.notes.append(
            f'检测到生产服务运行且端口被占（PID {holders}）—— 按生产处理'
        )
        return snap

    if running:
        snap.mode = RunMode.PROD
        return snap

    if holders:
        snap.mode = RunMode.DUAL_DEV
        snap.notes.append(f'端口被占用（PID {holders}），判定为开发模式')
        return snap

    snap.mode = RunMode.NONE
    return snap


def _with_notes(detail: str, notes: list[str]) -> str:
    """把探测备注追加到失败描述里（不覆盖原有内容）。"""
    if not notes:
        return detail
    return f'{detail}; 备注: {"；".join(notes)}'


def build_switch_mode(deps: Deps) -> SwitchMode:
    """工厂函数（供 container 使用）。"""
    return SwitchMode(deps)


__all__ = [
    'DEV_PROBE_PORTS',
    'ModeSnapshot',
    'SwitchMode',
    'SwitchModeContext',
    'build_switch_mode',
    'detect_mode',
]
