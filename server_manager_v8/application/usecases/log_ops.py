"""日志与审计查询 —— 只读操作用例。

═══════════════════════════════════════════════════════════════════
迁移来源：server_manager.py v5.40 `_refresh_logs()` / `_open_log_file()` 等
═══════════════════════════════════════════════════════════════════

旧实现里「日志」是内存里的一个环形列表（`self._logs`），由 UI 线程直接读。
问题：
    · **不是真相**：进程重启后内存日志全丢，事故复盘时什么都没了
    · **无检索**：只有「最近 N 条」，没有按时间/级别/来源筛选
    · **与审计混在一起**：运维日志（服务起停）与审计（谁做了什么）
      在同一个列表里，后者需要 append-only 与 hash 链，前者需要可轮转

新实现把两者分开：
    运维日志          → 事件总线（`LogAppended` 事件，实时流 + UI 展示）
    **审计**（本模块）→ `AuditPort`（append-only JSONL + hash 链，可查询可校验）

★ 本模块**不做**「读文件」这件事 —— 它通过 `AuditPort.query()` 拿数据。
  读哪个文件、怎么解码（GBK/UTF-8）、怎么处理轮转，都是 L1 适配器的职责。

═══════════════════════════════════════════════════════════════════
日志清理（CLEAR_LOGS）为什么是 L1 而不是 L0
═══════════════════════════════════════════════════════════════════

清空日志是**破坏证据**的操作。L1 的管控是「轻确认 + Toast 撤销」，
但仍然需要 Operator 权限而不是 Viewer ——
若只读用户能一键清空日志，事故后第一件事就是有人点了它。

★ 本模块只提供 `verify_chain()` 让用户**主动校验**审计完整性，
  不做任何「自动修复」。链断了就是断了，自动修复等于帮人掩盖篡改。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ...domain.permissions import Action
from ...domain.results import AuditEntry, AuditFilter, ChainVerifyResult, OpResult
from ..auth.guard import ConfirmationToken, require
from .deps import Deps

#: 单次查询默认返回条数上限（防止 UI 一次拉十万条卡死）
DEFAULT_QUERY_LIMIT = 200
#: 允许的最大条数（超过则截断，并在结果里说明）
MAX_QUERY_LIMIT = 5000


@dataclass
class AuditQueryContext:
    """审计查询上下文。"""

    deps: Deps
    entries: tuple[AuditEntry, ...] = ()
    truncated: bool = False
    notes: list[str] = field(default_factory=list)


class LogOps:
    """日志与审计的只读查询 + 完整性校验。

    查询本身是 L0（任何角色都能看）；本模块不涉及清理动作 ——
    清理在 `pipeline` 之外由 UI 直接调用 `ClearLogs`（同为 L1）实现，
    这里只做**查询与校验**，保持职责单一。
    """

    def __init__(self, deps: Deps) -> None:
        self._deps = deps

    @require(Action.EXPORT_LOGS)
    def query(
        self,
        *,
        session: object,
        confirm: ConfirmationToken | None = None,
        event_bus: object = None,
        audit: object = None,
        since: float | None = None,
        until: float | None = None,
        actor: str | None = None,
        action: str | None = None,
        limit: int | None = None,
    ) -> OpResult:
        """按条件查询审计条目。

        ★ 返回值只带 `detail`（一行摘要）—— 真正的数据通过
          `result_entries()` 或直接调 `AuditPort.query()` 取。
          这样设计的理由：`OpResult` 是「操作是否成功」的载体，
          不适合塞一个上万条的列表（会让日志/事件里出现巨型字符串）。

          调用方（UI）通常会直接用查询结果渲染表格，
          因此本方法同时把结果存到 `ctx` 并由 `last_entries` 暴露。
        """
        deps = self._deps
        effective_limit = limit if limit is not None else DEFAULT_QUERY_LIMIT
        truncated = False
        if effective_limit > MAX_QUERY_LIMIT:
            effective_limit = MAX_QUERY_LIMIT
            truncated = True

        flt = AuditFilter(
            since=since, until=until, actor=actor, action=action,
            limit=effective_limit + 1,     # ★ 多取一条用于判断「是否还有更多」
        )
        entries = list(deps.audit.query(flt))

        if len(entries) > effective_limit:
            entries = entries[:effective_limit]
            truncated = True

        self._last_entries = tuple(entries)
        ctx = AuditQueryContext(
            deps=deps, entries=tuple(entries), truncated=truncated,
        )
        if truncated:
            ctx.notes.append(
                f'结果已截断至 {effective_limit} 条（上限 {MAX_QUERY_LIMIT}）'
            )

        return OpResult.success(
            f'查询到 {len(entries)} 条审计记录'
            + ('（已截断）' if truncated else '')
        )

    @property
    def last_entries(self) -> tuple[AuditEntry, ...]:
        """最近一次 `query()` 的结果（供 UI 取数据）。"""
        return getattr(self, '_last_entries', ())

    @require(Action.VIEW_ALL)
    def verify_chain(
        self,
        *,
        session: object,
        confirm: ConfirmationToken | None = None,
        event_bus: object = None,
        audit: object = None,
    ) -> OpResult:
        """校验审计 hash 链的完整性。

        ★ 链断裂**不是操作失败** —— 校验这个动作本身成功了。
          所以返回 `OpResult.success`，把结论放进 `detail`。
          若返回 failure，UI 会当成「校验失败，请重试」，
          而真实含义是「校验完成，发现审计被改过」—— 完全不同的事。

        ★ 断链位置必须说清：只说「链断了」运维无从处置
          （`ChainVerifyResult.broken_at` 就是为此存在的）。
        """
        del confirm, event_bus, audit
        result = self._deps.audit.verify_chain()
        self._last_verify = result

        if result.ok:
            return OpResult.success(f'审计链完整（{result.total} 条）')
        return OpResult.success(
            f'审计链已断裂：第 {result.broken_at} 条起校验失败（共 {result.total} 条）'
            f'—— {result.reason}'
        )

    @property
    def last_verify(self) -> ChainVerifyResult | None:
        """最近一次 `verify_chain()` 的结果（供 UI 取结构化数据）。"""
        return getattr(self, '_last_verify', None)


def build_log_ops(deps: Deps) -> LogOps:
    return LogOps(deps)


__all__ = [
    'AuditQueryContext',
    'DEFAULT_QUERY_LIMIT',
    'LogOps',
    'MAX_QUERY_LIMIT',
    'build_log_ops',
]
