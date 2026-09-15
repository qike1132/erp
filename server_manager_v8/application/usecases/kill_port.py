"""清理端口占用 —— 找出占着端口的进程并终止。

═══════════════════════════════════════════════════════════════════
迁移来源：server_manager.py v5.40 `_release_port()` / `_get_port_occupier()`
═══════════════════════════════════════════════════════════════════

旧实现的两处核心逻辑已经拆到别处（本模块不复制）：

    · **谁算占用者** → `domain.port_contract.parse_netstat_occupiers`
      （含两种口径：LISTENING_ONLY 用于击杀、LISTENING_OR_ESTABLISHED 用于留痕）
    · **怎么杀进程树** → `ProcessPort.kill_tree`（五条进程安全约定的落点）

本模块只编排：

    ① 探测占用者（★ 用窄口径 —— 见下方「两种口径」）
    ② 留痕（★ 在杀之前 —— 见下方「留痕必须在杀之前」）
    ③ 逐个终止
    ④ 复查端口是否已释放

═══════════════════════════════════════════════════════════════════
★ 两种口径绝不混用
═══════════════════════════════════════════════════════════════════

`find_port_pids(port, listening_only=True)`  → 决定**杀谁**
`find_port_pids(port, listening_only=False)` → 给用户看的**占用者名单**

若用留痕口径（含 ESTABLISHED）去杀人，会把所有连到这个端口的客户端
进程一起杀掉 —— 例如 6379 上有 143 个 ESTABLISHED 连接，
那些都是客户端（业务进程），不是占用者。

★ 本模块的 `execute()` **只调一次** `listening_only=True`，
  留痕用的宽口径名单由 `inspect()` 单独提供（只读、不杀）。

═══════════════════════════════════════════════════════════════════
★ 留痕必须在杀之前
═══════════════════════════════════════════════════════════════════

进程一旦被杀，「它当时是谁」就再也查不到了（PID 会被复用）。
所以审计条目必须在**真正终止之前**写入，且要带上：
    · 每个 PID 的进程名（`resolve_process_name`）
    · 端口号（哪个端口被清理）
    · 操作者与原因（来自 `ConfirmationToken.reason`，L2+ 要求填）

若审计写失败（`AuditPort.record` 永不抛出，但内部可能失败），
本模块**仍然继续** —— 审计不阻断业务是既定契约。但会通过返回值
明确告知「本次清理没有被成功留痕」，不静默。

═══════════════════════════════════════════════════════════════════
★ 为什么终止失败不能算「清理成功」
═══════════════════════════════════════════════════════════════════

旧实现是 `_taskkill_many(pids)` 之后直接报成功，**不复查端口**。
后果：进程处于「正在终止」状态时 taskkill 返回成功，但端口还没释放，
用户随即点「启动」仍然绑定失败 —— 而界面刚说「清理成功」。

本实现④复查：仍有 LISTENING 占用者则整体失败，理由带上残留 PID。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ...domain.permissions import Action
from ...domain.port_contract import DEFAULT_PORTS, is_valid_port
from ...domain.results import OpResult
from ..auth.guard import ConfirmationToken, require
from .deps import Deps

#: 复查端口时最多重试几次（每次间隔由 `deps.clock.sleep` 承担）
RECHECK_ATTEMPTS = 3
#: 复查间隔（秒）
RECHECK_INTERVAL_S = 0.5


@dataclass
class PortOccupierInfo:
    """给用户看的占用者信息（含进程名，供留痕与展示）。

    ★ 名字里的 `Info` 是刻意的：`domain.port_contract` 已有一个
      `PortOccupier(pid, local_addr, state)`。两者同名不同型会让
      `from ... import PortOccupier` 产生语义歧义 —— 本类多一个 `name` 字段
      （来自 I/O 查询）与 `from_kill_probe` 标记。

      `adapters.process_win` 里也有一个同名类，P3 起统一用本定义
      （应用层需要的形态就是「带进程名」这种）。
    """

    port: int
    pid: int
    name: str = ''
    local_addr: str = ''
    state: str = ''

    @property
    def label(self) -> str:
        """一行可读描述。"""
        who = self.name or '未知进程'
        return f'PID {self.pid} ({who})'


@dataclass
class KillPortContext:
    """端口清理的上下文。"""

    deps: Deps
    port: int = 0
    trace_id: str = ''
    occupiers: tuple[PortOccupierInfo, ...] = ()
    killed: tuple[int, ...] = ()
    remaining: tuple[int, ...] = ()
    reason: str = ''
    notes: list[str] = field(default_factory=list)


class KillPort:
    """清理指定端口的占用进程。

    这是 L2 高危操作（清理端口占用），需要 Operator+ 与二次确认。
    """

    def __init__(self, deps: Deps) -> None:
        self._deps = deps

    # ── 主流程 ────────────────────────────────────────────────────

    @require(Action.KILL_PORT, target_arg='port')
    def execute(
        self,
        port: int,
        *,
        session: object,
        confirm: ConfirmationToken | None = None,
        event_bus: object = None,
        audit: object = None,
        trace_id: str = '',
    ) -> OpResult:
        """终止占用 `port` 的进程。

        ★ `port` 是**位置参数**，因为 `@require(target_arg='port')`
          要把它取出来做 L3 的名称确认比对（若哪天升级为 L3）。
          当前 KILL_PORT 是 L2，`target` 比对不生效，但保留该接线。
        """
        deps = self._deps

        if not is_valid_port(port):
            return OpResult.failure('端口非法', f'期望 1-65535 的整数，得到 {port!r}')

        ctx = KillPortContext(deps=deps, port=int(port), trace_id=trace_id)

        # ── ① 探测（★ 窄口径：只认 LISTENING）──
        pids = deps.process.find_port_pids(int(port), listening_only=True)
        if not pids:
            return OpResult.success(f'端口 {port} 空闲，无需清理')

        ctx.occupiers = tuple(
            PortOccupierInfo(port=int(port), pid=pid,
                             name=deps.process.resolve_process_name(pid))
            for pid in pids
        )

        # ── ② 留痕（★ 必须在杀之前）──
        self._record_before_kill(ctx, confirm)

        # ── ③ 逐个终止 ──
        killed: list[int] = []
        failures: list[str] = []
        for info in ctx.occupiers:
            result = deps.process.kill_tree(info.pid)
            if result.ok and result.targeted > 0:
                killed.append(info.pid)
            elif result.ok and result.targeted == 0:
                # ★ 「没找到可杀的目标」不是成功 —— 端口仍然被占
                failures.append(f'{info.label}: 未找到可终止的进程')
            else:
                failures.append(f'{info.label}: {result.error or "终止失败"}')

        ctx.killed = tuple(killed)

        # ── ④ 复查（★ 旧实现缺这一步）──
        remaining = self._recheck(ctx)
        ctx.remaining = tuple(remaining)

        if remaining:
            return OpResult.failure(
                f'端口 {port} 仍被占用',
                detail=(f'残留 PID: {", ".join(str(p) for p in remaining)}；'
                        f'已终止: {", ".join(str(p) for p in killed) or "无"}'),
            )
        if failures:
            # 有失败但复查通过：说明端口实际已释放（可能失败的是无关进程）
            return OpResult.success(
                f'端口 {port} 已释放（含 {len(failures)} 个未成功的终止尝试）'
                + '；' + '; '.join(failures)
            )

        names = ', '.join(i.label for i in ctx.occupiers)
        return OpResult.success(f'端口 {port} 已释放（清理 {names}）')

    # ── 只读巡查（供 UI 显示，不杀）──────────────────────────────

    def inspect(self, port: int) -> list[PortOccupierInfo]:
        """列出端口占用者（**宽口径**，含 ESTABLISHED，供展示）。

        ★ 这个方法**绝不**用于决定杀谁 —— 它的返回值里包含客户端进程。
          独立成方法而不是给 `execute` 加参数，就是为了让「口径」在
          调用点一眼可见（`execute` 只有一种口径，不可能混）。
        """
        if not is_valid_port(port):
            return []
        deps = self._deps
        pids = deps.process.find_port_pids(int(port), listening_only=False)
        return [
            PortOccupierInfo(port=int(port), pid=pid,
                             name=deps.process.resolve_process_name(pid))
            for pid in pids
        ]

    # ── 内部 ──────────────────────────────────────────────────────

    def _record_before_kill(self, ctx: KillPortContext,
                            confirm: ConfirmationToken | None) -> None:
        """写入「即将终止」的审计条目。

        ★ 这是**唯一**在杀之前留痕的机会。进程死后 PID 会被复用，
          「当时是谁」就永久丢失了。

        ★ 审计失败不阻断（`AuditPort.record` 的契约是永不抛出），
          但要把「未留痕」这个事实带回给用户（见 notes）。
        """
        ctx.reason = (confirm.reason if confirm and confirm.reason else '')
        recorded = True
        try:
            from ...domain.results import AuditEntry, AuditOutcome  # noqa: PLC0415

            ctx.deps.audit.record(AuditEntry(
                ts=0.0,
                actor=ctx.deps.actor,
                action=Action.KILL_PORT.value,
                target=str(ctx.port),
                outcome=AuditOutcome.OK,
                reason=ctx.reason or '未填写原因',
                trace_id=ctx.trace_id,
                detail='即将终止: ' + '; '.join(i.label for i in ctx.occupiers),
            ))
        except BaseException:  # noqa: BLE001
            recorded = False

        if not recorded:
            # ★ 不静默：告诉用户这次操作没进审计
            ctx.notes.append('审计写入失败，本次清理未留痕')

    def _recheck(self, ctx: KillPortContext) -> list[int]:
        """复查端口是否真正释放（最多 `RECHECK_ATTEMPTS` 次）。

        ★ 为什么要复查：`taskkill` 返回成功时进程可能仍在「正在终止」
          状态，端口还没释放。若此时报成功，用户接着点「启动」会绑定失败。
        """
        deps = ctx.deps
        last: list[int] = []
        for attempt in range(RECHECK_ATTEMPTS):
            last = deps.process.find_port_pids(ctx.port, listening_only=True)
            if not last:
                return []
            if attempt < RECHECK_ATTEMPTS - 1:
                deps.clock.sleep(RECHECK_INTERVAL_S)
        return last


def build_kill_port(deps: Deps) -> KillPort:
    """工厂函数（供 container 使用）。"""
    return KillPort(deps)


def default_ports() -> dict[str, int]:
    """默认端口映射（'backend'/'frontend'/'redis' → 端口号）。

    注册到 `Deps.ports` 的名字统一用 'backend'/'frontend'/'redis'，
    与 `PortConfig` 的 api/web/redis 一一对应 —— 两种叫法并存是旧代码的
    遗留（`_PORTS.api` vs UI 上的「后端端口」），此处给出唯一映射。
    """
    return {
        'backend': DEFAULT_PORTS.api,
        'frontend': DEFAULT_PORTS.web,
        'redis': DEFAULT_PORTS.redis,
    }


__all__ = [
    'KillPort',
    'KillPortContext',
    'PortOccupierInfo',
    'RECHECK_ATTEMPTS',
    'RECHECK_INTERVAL_S',
    'build_kill_port',
    'default_ports',
]
