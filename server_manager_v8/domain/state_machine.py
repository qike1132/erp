"""模式互斥状态机 —— 纯逻辑，零 I/O。

本模块从 server_manager.py（v5.40）迁移而来：
    `_ensure_production_stopped`（L1545）与 `_ensure_development_stopped`（L1597）
    的**判定逻辑**，剥离 subprocess / psutil / 消息队列等副作用。

═══════════════════════════════════════════════════════════════════
这是全项目最高风险、也是投入防护最多的逻辑
═══════════════════════════════════════════════════════════════════

它守的是什么事故？
    「开发模式与生产模式互相厮杀」—— 开发模式启动前若未能确认生产已停，
    就会抢占 5002/3000 端口，与仍在运行的生产服务互杀。
    这个事故在 v5.36 被堵住、在 v5.39 又因 sc 输出子串误判换个入口复发（审查 #1），
    在 v5.40 才真正修好。

核心安全性质（v5.40 交付报告自证断言 A5）：
    状态「未知」且无法在超时内确认 STOPPED → ok=False，切换被中止
    （既不释放端口、也不启动），**绝不静默放行**。

设计要点：
    1. 每个服务独立判定，逐个给出「放行 / 需停止 / 中止」
    2. 「未安装」放行（服务不存在无需停止）
    3. 「未知」按运行中保守处理 —— 必须尝试停止并等待确认
    4. 任一服务确认不了停止 → **整体中止**（不是跳过）
    5. 结果用不可变 dataclass 表达（对应原 `_ProdStopResult` NamedTuple，
       从类型层面杜绝 v5.33 的「超时分支返回 2 元组 / 调用方解包 3 元组」崩溃）
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from .models import RunMode, ServiceKind
from .service_state import ServiceStatus

# ═══════════════════════════════════════════════════════════════════
# 前置停止的结果（对应原 _ProdStopResult NamedTuple）
# ═══════════════════════════════════════════════════════════════════


@dataclass(frozen=True)
class StopResult:
    """前置停止的结果。

    对应原 `_ProdStopResult(ok, reason, stopped_any)` ——
    **三个字段固定存在**，从类型层面杜绝 v5.33 的解包崩溃（§6.1）：

        v5.33 的超时分支只返回 2 元组，而调用方按 3 元组解包
        → `not enough values to unpack (expected 3, got 2)`
        → 开发模式 100% 启动失败

    改用 frozen dataclass 后，字段数由类型定义固定，不可能「少返回一个」。
    """

    ok: bool
    reason: str | None = None
    stopped_any: bool = False

    def __post_init__(self) -> None:
        # 失败必须带真实原因（v5.33「停不掉」的教训：不能是空洞的失败）
        if not self.ok and not self.reason:
            raise ValueError('StopResult 失败时必须提供 reason（禁止空洞的失败）')

    # ── 兼容旧调用点的元组解包（迁移保真）────────────────────────────
    # 原实现是 NamedTuple，调用点写作 `ok, reason, stopped_any = result`。
    # 用 frozen dataclass 替代时若不加 __iter__，这些调用点会集体
    # TypeError —— 等于把 §6.1 的崩溃从「少返回一个」换成「根本不可迭代」，
    # 换汤不换药。所以显式保留三字段的迭代能力。
    #
    # 注意：这只解决解包，不解决「字段缺失」—— 字段数由 dataclass 定义固定。
    def __iter__(self):
        return iter((self.ok, self.reason, self.stopped_any))

    def __len__(self) -> int:
        return 3

    @property
    def _fields(self) -> tuple[str, ...]:
        """对齐 NamedTuple._fields，便于下游做反射式字段遍历。"""
        return ('ok', 'reason', 'stopped_any')

    @staticmethod
    def success(stopped_any: bool) -> StopResult:
        return StopResult(ok=True, reason=None, stopped_any=stopped_any)

    @staticmethod
    def abort(reason: str) -> StopResult:
        """中止切换。stopped_any 恒为 False —— 中止即未真正停止任何东西。"""
        return StopResult(ok=False, reason=reason, stopped_any=False)


# ═══════════════════════════════════════════════════════════════════
# 单个服务的判定
# ═══════════════════════════════════════════════════════════════════


class ServiceDisposition(Enum):
    """单个服务在前置停止流程里应采取的动作。"""

    SKIP_ABSENT = 'skip_absent'
    """未安装 —— 无需停止，直接放行。"""

    ALREADY_STOPPED = 'already_stopped'
    """已确认 STOPPED —— 直接放行。"""

    MUST_STOP = 'must_stop'
    """需尝试停止并等待确认（运行中 / 中间态 / 未知）。"""

    @property
    def needs_stop_attempt(self) -> bool:
        return self is ServiceDisposition.MUST_STOP


@dataclass(frozen=True)
class ServiceDecision:
    """对单个服务的判定结果。"""

    service: str
    status: ServiceStatus
    disposition: ServiceDisposition
    is_unknown: bool = False

    @property
    def needs_stop_attempt(self) -> bool:
        return self.disposition.needs_stop_attempt

    @property
    def releases_immediately(self) -> bool:
        """是否无需停止即可放行。"""
        return self.disposition in (
            ServiceDisposition.SKIP_ABSENT,
            ServiceDisposition.ALREADY_STOPPED,
        )


def decide_service_action(service_name: str, status: ServiceStatus) -> ServiceDecision:
    """判定单个服务应采取的动作。

    迁移自 `_ensure_production_stopped` 的循环体（L1559-1574）：

        state = self._svc_state(name)
        if self._svc_absent(state):        continue          # → SKIP_ABSENT
        unknown = self._svc_unknown(state)
        if unknown:                        # 按运行中保守处理
            self._msg_queue.put(('log', {...'WARNING'}))
        elif 'STOPPED' in state:           continue          # → ALREADY_STOPPED
        # → MUST_STOP
    """
    if status is ServiceStatus.ABSENT:
        return ServiceDecision(service_name, status, ServiceDisposition.SKIP_ABSENT)
    if status is ServiceStatus.STOPPED:
        return ServiceDecision(service_name, status, ServiceDisposition.ALREADY_STOPPED)
    # RUNNING / PENDING / UNKNOWN 一律必须尝试停止
    return ServiceDecision(
        service_name, status, ServiceDisposition.MUST_STOP,
        is_unknown=(status is ServiceStatus.UNKNOWN),
    )


# ═══════════════════════════════════════════════════════════════════
# 前置停止编排（判定部分）
# ═══════════════════════════════════════════════════════════════════


@dataclass
class PreflightPlan:
    """模式切换的前置停止计划。"""

    decisions: list[ServiceDecision] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def services_to_stop(self) -> list[str]:
        return [d.service for d in self.decisions if d.needs_stop_attempt]

    @property
    def unknown_services(self) -> list[str]:
        return [d.service for d in self.decisions if d.is_unknown]

    @property
    def needs_any_stop(self) -> bool:
        return bool(self.services_to_stop)


def plan_production_stop(
    snapshots: dict[str, ServiceStatus],
) -> PreflightPlan:
    """为「停生产」生成计划。

    参数 `snapshots` 形如 {'erp-prod': ServiceStatus.RUNNING, 'erp-arq': ServiceStatus.ABSENT}
    —— 由 adapter 查询后传入（领域层零 I/O）。

    迁移自 `_ensure_production_stopped` 的前半段。`unknown` 的 WARNING 文案
    保持原文：

        f'无法查询 {name} 状态（sc 查询失败），按运行中保守处理'
    """
    plan = PreflightPlan()
    for name, status in snapshots.items():
        decision = decide_service_action(name, status)
        plan.decisions.append(decision)
        if decision.is_unknown:
            plan.warnings.append(f'无法查询 {name} 状态（sc 查询失败），按运行中保守处理')
    return plan


def build_stop_abort_reason(service: str, status: ServiceStatus) -> str:
    """构造「确认不了停止」的中止原因。

    迁移自 L1571-1572，两种文案按是否「未知」区分：

        reason = (f'{name} 状态未知且未能在超时内确认 STOPPED，已中止切换' if unknown
                  else f'{name} 停止超时（STOP_PENDING 未确认），已中止切换')
    """
    if status is ServiceStatus.UNKNOWN:
        return f'{service} 状态未知且未能在超时内确认 STOPPED，已中止切换'
    return f'{service} 停止超时（STOP_PENDING 未确认），已中止切换'


# ═══════════════════════════════════════════════════════════════════
# 模式切换守卫
# ═══════════════════════════════════════════════════════════════════


@dataclass(frozen=True)
class SwitchGuard:
    """模式切换的前置条件判定。

    对应原 `_ensure_production_stopped` / `_ensure_development_stopped`
    的「是否需要先停对方」判定。
    """

    current: RunMode
    target: RunMode

    @property
    def is_noop(self) -> bool:
        """已处于目标模式（原实现里表现为按钮仍可点，但实际无需切换）。"""
        return self.current is self.target

    @property
    def must_stop_first(self) -> RunMode | None:
        """启动 target 前必须先停的模式。

        NONE 与任何模式都不冲突；DUAL_DEV 与 PROD 互斥。
        """
        if self.current is RunMode.NONE or self.current is self.target:
            return None
        return self.current

    @property
    def involves_production(self) -> bool:
        """本次切换是否涉及生产模式（决定是否需要 NSSM guard）。"""
        return RunMode.PROD in (self.current, self.target)


def needs_restart_guard(target: RunMode, nssm_available: bool) -> bool:
    """是否需要挂 NSSM 崩溃自动重启 guard。

    迁移自 `_ensure_production_stopped` 的：

        nssm_existed = self._find_nssm() is not None
        if nssm_existed:
            self._service_restart_guard(False)
        try: ...
        finally:
            if nssm_existed:
                self._service_restart_guard(True)

    ★ D6 语义（勿误读）：guard 只对 **NSSM 托管的 erp-prod / erp-arq 有效**
      （AppExit 是 NSSM 特有概念），对原生 Windows 服务 (erp-redis 等)
      完全没有作用。因此本函数的判定只看「是否有 nssm」。

    注意：原实现在 `_ensure_production_stopped`（停生产）里挂 guard，
    因为那一步会杀 prod_runner 残留进程 —— 正是需要防「5 秒复活」的场景。
    """
    return bool(nssm_available)


class GuardKind(Enum):
    """guard 的两种取值（对应 AppExit 的 Restart / Exit）。"""

    DISABLE = 'Exit'
    ENABLE = 'Restart'


def guard_sequence(nssm_available: bool) -> tuple[GuardKind, ...]:
    """返回该切换需要的 guard 调用序列（成对出现，finally 保证恢复）。

    原实现（L1556-1557, L1593-1595）：

        if nssm_existed: guard(False)      # 停止前禁用
        try: ...
        finally:
            if nssm_existed: guard(True)   # 无论如何恢复

    ★ v5.38 的 D11 教训：guard(True) 恢复**必须晚于**残留扫描
      （否则 guard 窗口没覆盖它本该保护的残留扫描期）。
      本函数只表达「需要哪些调用」，时序由应用层的 try/finally 保证。
    """
    if not nssm_available:
        return ()
    return (GuardKind.DISABLE, GuardKind.ENABLE)


# ═══════════════════════════════════════════════════════════════════
# 残留进程保护（迁移自 _ensure_production_stopped 的 psutil 段）
# ═══════════════════════════════════════════════════════════════════


def build_protected_pids(
    self_pid: int, service_pids: dict[str, int | None]
) -> frozenset[int]:
    """构造「绝不能杀」的 PID 集合。

    迁移自 L1576-1580：

        protected = {os.getpid()}
        for name in (_SVC_API, _SVC_ARQ):
            pid = self._svc_pid(name)
            if pid:
                protected.add(pid)

    ★ 这是 v5.33 P0-3「宽特征扫描误杀 NSSM 被管进程 → 5 秒复活死循环」的修复点。
      自身 PID 与自己管理的服务 PID 必须绝对保护。
    """
    protected = {self_pid}
    protected.update(pid for pid in service_pids.values() if pid)
    return frozenset(protected)


def is_residual_prod_runner(
    cmdline: list[str] | tuple[str, ...] | None,
    pid: int,
    protected: frozenset[int],
) -> bool:
    """判定某进程是否为「需清理的残留 prod_runner」。

    迁移自 L1581-1589：

        for p in psutil.process_iter(['pid','name','cmdline']):
            pid = p.info['pid']
            if not pid or pid in protected:            → False
            if 'prod_runner' in ' '.join(p.info['cmdline'] or []):  → True

    ★ 注意这是**精准特征**（'prod_runner'），不是 v5.33 的宽特征扫描
      （python/node）—— 后者会误杀 NSSM 监管中的进程。
      精准特征 + PID 白名单双保险，是本题的正确解法。
    """
    if not pid or pid in protected:
        return False
    if not cmdline:
        return False
    return 'prod_runner' in ' '.join(cmdline)


# ═══════════════════════════════════════════════════════════════════
# 开发模式停止（迁移自 _ensure_development_stopped）
# ═══════════════════════════════════════════════════════════════════


@dataclass(frozen=True)
class DevProcessSpec:
    """开发模式的子进程描述（用于停止决策）。"""

    role_label: str
    pid: int | None


def select_dev_processes_to_stop(
    processes: list[DevProcessSpec],
) -> list[DevProcessSpec]:
    """筛出需要终止的开发子进程。

    迁移自 `_ensure_development_stopped` 的循环条件：

        for proc, name in ((self._frontend_process, '前端'), (self._process, '后端')):
            if proc and proc.poll() is None:      # 仍在运行
                终止...

    ★ 关键语义（原实现注释强调）：**只停开发子进程，不动 Redis**。
      Redis 是生产与开发共用的基础设施，停它会波及生产。
    """
    return [p for p in processes if p.pid]
