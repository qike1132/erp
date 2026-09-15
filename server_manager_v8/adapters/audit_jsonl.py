"""审计日志适配器 —— append-only JSONL + sha256 hash 链。

═══════════════════════════════════════════════════════════════════
设计目标（v8 方案 §2.5「4A：认证/授权/账号/审计」）
═══════════════════════════════════════════════════════════════════

堡垒机 4A 的审计要求两条：
    1. **完整** —— 高危操作必须留痕，被拒的操作同样必须留痕
       （「谁在什么权限下被拦下」是安全事件的关键线索）
    2. **不可篡改** —— 事后改一条记录就能掩盖行为，审计就失去意义

第 1 条靠「所有高危操作统一走 `record()`」的约定（在 Application 层强制）。
第 2 条靠 **hash 链**：每条记录含 `prev_hash`，其 `entry_hash` 由
（本记录内容 + prev_hash）算出。改动任何一条历史记录，其后所有 hash 都对不上。

═══════════════════════════════════════════════════════════════════
★ 为什么 hash 链是「弱不可篡改」—— 必须如实说明
═══════════════════════════════════════════════════════════════════

本实现**没有密钥**（无 HMAC），所以能防的和不能防的要讲清楚：

能防：
    · 事后手工编辑某条记录（改金额、改操作人）→ 链校验立刻发现
    · 不小心重复写入 / 顺序错乱 → 链校验发现
    · 整段删除中间若干行 → 链校验发现

**不能防**：
    · 攻击者拿到文件写权限后，从断点**重算其后所有 hash** —— 链会「自洽」

这不是实现缺陷，而是「无密钥 hash 链」的数学上限。
要真正防重算需要 HMAC + 密钥保护（密钥又存在哪？），
对单机桌面工具而言收益与复杂度不成比例。

**所以本实现的定位是「防误操作 + 防事后顺手篡改」，不是「防有权限的攻击者」。**
这个边界必须写在代码里，否则后人会误以为它提供了它并不具备的保证。

═══════════════════════════════════════════════════════════════════
★ 与 Port 契约的张力：`record()` 要求永不抛出，但失败不能静默
═══════════════════════════════════════════════════════════════════

两个要求看似矛盾：
    · `AuditPort.record()` 契约：永不抛出（审计失败不能阻断业务操作）
    · 项目铁律「禁止静默失败」

折中方案：**抛出改为回调**。写入失败时调用注入的 `on_error` 回调，
把失败事实交给调用方（通常是 Application 层 → 转发成 Toast + stderr）。
既不阻断业务，也不静默。
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from pathlib import Path
from typing import Any, Callable

from ..domain.results import (
    AuditEntry,
    AuditFilter,
    AuditOutcome,
    ChainVerifyResult,
)

#: 链的起点（第一条记录的 prev_hash）
GENESIS_HASH = '0' * 64

#: 参与 hash 计算的字段（顺序固定，改此列表等于让所有历史链失效）
HASHED_FIELDS: tuple[str, ...] = (
    'ts', 'actor', 'action', 'target', 'outcome', 'reason', 'trace_id', 'detail',
)


def compute_hash(entry: AuditEntry, prev_hash: str) -> str:
    """计算一条记录的 entry_hash。

    ★ 用**规范化 JSON**（sort_keys + 紧凑分隔符）而非字符串拼接：
      拼接容易因字段顺序或空格差异导致同一逻辑内容算出不同 hash，
      产生「明明没改却报链断」的假告警。
    """
    payload: dict[str, Any] = {
        'prev': prev_hash,
    }
    for name in HASHED_FIELDS:
        value = getattr(entry, name)
        # Enum 要转成它的 value，否则 repr 里带类名，跨版本可能变
        payload[name] = value.value if isinstance(value, AuditOutcome) else value

    blob = json.dumps(payload, ensure_ascii=False, sort_keys=True,
                      separators=(',', ':')).encode('utf-8')
    return hashlib.sha256(blob).hexdigest()


def _default_on_error(exc: BaseException) -> None:
    """默认失败回调：写到 stderr。

    不用 `logging` —— 适配层不该在 import 时假设日志系统已配置。
    stderr 在 GUI 模式下不显眼，但**至少不是静默的**；
    真正的用户提示由 Application 层通过注入的 on_error 完成。
    """
    import sys
    print(f'[audit] 写入审计失败: {type(exc).__name__}: {exc}', file=sys.stderr)


class JsonlAuditLog:
    """append-only JSONL 审计日志。

    实现 `domain.ports.AuditPort`。
    """

    def __init__(self, path: str | Path,
                 on_error: Callable[[BaseException], None] | None = None) -> None:
        self._path = Path(path)
        self._on_error = on_error or _default_on_error
        self._last_hash: str | None = None

    @property
    def path(self) -> Path:
        return self._path

    # ── 读取 ──────────────────────────────────────────────────────

    def _iter_lines(self) -> list[str]:
        try:
            text = self._path.read_text(encoding='utf-8')
        except FileNotFoundError:
            return []
        except OSError as exc:
            self._on_error(exc)
            return []
        return [ln for ln in text.splitlines() if ln.strip()]

    def _tail_hash(self) -> str:
        """取最后一条记录的 entry_hash（作为下一条的 prev_hash）。

        损坏行（无法解析的 JSON）会被跳过 —— 链校验会单独报出来，
        不该让一条坏行阻断后续所有写入。
        """
        lines = self._iter_lines()
        for line in reversed(lines):
            try:
                data = json.loads(line)
            except json.JSONDecodeError:
                continue
            value = data.get('entry_hash')
            if isinstance(value, str) and value:
                return value
        return GENESIS_HASH

    # ── 写入（Port 实现）──────────────────────────────────────────

    def record(self, entry: AuditEntry) -> None:
        """追加一条审计。**永不抛出**（契约要求），失败走 on_error 回调。"""
        try:
            prev = self._last_hash if self._last_hash is not None else self._tail_hash()
            entry_hash = compute_hash(entry, prev)

            # frozen dataclass → 用 replace 语义生成带 hash 的副本
            import dataclasses
            stamped = dataclasses.replace(entry, prev_hash=prev, entry_hash=entry_hash)

            payload = asdict(stamped)
            payload['outcome'] = stamped.outcome.value

            self._path.parent.mkdir(parents=True, exist_ok=True)
            with self._path.open('a', encoding='utf-8') as fh:
                fh.write(json.dumps(payload, ensure_ascii=False) + '\n')

            self._last_hash = entry_hash
        except BaseException as exc:  # noqa: BLE001  —— 契约要求永不抛出
            self._on_error(exc)

    def query(self, flt: AuditFilter) -> list[AuditEntry]:
        """按条件查询。无法解析的行跳过（计入链校验，不在此处报错）。"""
        results: list[AuditEntry] = []
        for line in self._iter_lines():
            try:
                data = json.loads(line)
                entry = _from_dict(data)
            except (json.JSONDecodeError, KeyError, TypeError, ValueError):
                continue

            if flt.since is not None and entry.ts < flt.since:
                continue
            if flt.until is not None and entry.ts > flt.until:
                continue
            if flt.actor is not None and entry.actor != flt.actor:
                continue
            if flt.action is not None and entry.action != flt.action:
                continue
            if flt.outcome is not None and entry.outcome is not flt.outcome:
                continue
            results.append(entry)

        if flt.limit is not None and flt.limit >= 0:
            results = results[-flt.limit:] if flt.limit else []
        return results

    def verify_chain(self) -> ChainVerifyResult:
        """逐条重算 hash，验证链完整性。

        报告**第一个**断点（`broken_at`）—— 只说「断了」不说断在哪，
        运维无法定位处置。
        """
        lines = self._iter_lines()
        if not lines:
            return ChainVerifyResult(ok=True, total=0)

        prev = GENESIS_HASH
        for index, line in enumerate(lines):
            try:
                data = json.loads(line)
                entry = _from_dict(data)
            except Exception as exc:  # noqa: BLE001
                return ChainVerifyResult(
                    ok=False, total=len(lines), broken_at=index,
                    reason=f'第 {index} 行无法解析: {type(exc).__name__}',
                )

            if entry.prev_hash != prev:
                return ChainVerifyResult(
                    ok=False, total=len(lines), broken_at=index,
                    reason=f'第 {index} 行 prev_hash 不匹配（记录被移动或缺失）',
                )

            expected = compute_hash(entry, prev)
            if entry.entry_hash != expected:
                return ChainVerifyResult(
                    ok=False, total=len(lines), broken_at=index,
                    reason=f'第 {index} 行内容与 hash 不符（该行已被修改）',
                )
            prev = entry.entry_hash

        return ChainVerifyResult(ok=True, total=len(lines))


def _from_dict(data: dict[str, Any]) -> AuditEntry:
    """dict → AuditEntry（JSON 反序列化）。"""
    outcome_raw = data.get('outcome', 'ok')
    try:
        outcome = AuditOutcome(outcome_raw)
    except ValueError:
        # 未知 outcome 不致命，按 FAILED 处理并保留原文（宁可保守）
        outcome = AuditOutcome.FAILED

    return AuditEntry(
        ts=float(data.get('ts', 0.0)),
        actor=str(data.get('actor', '')),
        action=str(data.get('action', '')),
        target=str(data.get('target', '')),
        outcome=outcome,
        reason=str(data.get('reason', '')),
        trace_id=str(data.get('trace_id', '')),
        detail=str(data.get('detail', '')),
        prev_hash=str(data.get('prev_hash', '')),
        entry_hash=str(data.get('entry_hash', '')),
    )


__all__ = [
    'GENESIS_HASH',
    'HASHED_FIELDS',
    'JsonlAuditLog',
    'compute_hash',
]
