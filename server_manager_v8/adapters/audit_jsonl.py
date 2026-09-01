"""审计流水适配器 — 实现 domain.ports.AuditPort（append-only + sha256 哈希链）。

字节 Romaster 裁剪（v8 方案 §2.3）：append-only JSONL，每条记录携带前一条的
SHA-256，形成哈希链；任何中间篡改都会被 verify_chain 检出。

契约（ports.py 明文规定）：
    - record() **永不抛出** —— 审计失败不能影响主流程（写失败记入失败计数，
      由 stats() 上报，而不是静默）
    - verify_chain() 返回 OpResult，detail 携带首个断裂位置
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from server_manager_v8.domain import GENESIS_HASH, AuditEntry, OpResult, Role

__all__ = ['AuditJsonlStore', 'decode_line']


def decode_line(line: str) -> AuditEntry | None:
    """解析 JSONL 一行。损坏行返回 None（由调用方统计，不静默）。"""
    try:
        data = json.loads(line)
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None
    try:
        role_raw = str(data.get('role', 'viewer'))
        try:
            role = Role(role_raw)
        except ValueError:
            role = Role.VIEWER  # 未知角色兜底为只读（安全默认）
        return AuditEntry(
            ts=float(data.get('ts', 0)),
            actor=str(data.get('actor', '')),
            role=role,
            action=str(data.get('action', '')),
            target=str(data.get('target', '')),
            params_digest=str(data.get('params_digest', '')),
            result=str(data.get('result', 'ok')),
            duration_ms=int(data.get('duration_ms', 0)),
            trace_id=str(data.get('trace_id', '')),
            reason=str(data.get('reason', '')),
            prev_hash=str(data.get('prev_hash', GENESIS_HASH)),
            hash=str(data.get('hash', '')),
        )
    except (TypeError, ValueError):
        return None


class AuditJsonlStore:
    """append-only 审计存储。构造时注入路径。"""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self._failed_writes = 0
        self._corrupt_lines = 0

    # ---- AuditPort 实现 ----

    def record(self, entry: AuditEntry) -> None:
        """追加一条并自动接链（prev_hash = 文件尾哈希）。**永不抛出**。"""
        try:
            prev = self._tail_hash()
            linked = AuditEntry(**{**entry.__dict__, 'prev_hash': prev})
            sealed = linked.sealed()
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open('a', encoding='utf-8') as fh:
                fh.write(sealed.to_line() + '\n')
        except OSError:
            self._failed_writes += 1

    def query(self, **filters: Any) -> list[AuditEntry]:
        """按字段过滤（actor / role / action / result / 时间范围）。"""
        out: list[AuditEntry] = []
        for entry in self._read_all():
            if not self._match(entry, filters):
                continue
            out.append(entry)
        return out

    def verify_chain(self) -> OpResult:
        """端到端重算哈希链，检出中间篡改。"""
        entries = self._read_all()
        if not entries:
            return OpResult.success(detail='空审计，链完整')
        prev = GENESIS_HASH
        for index, entry in enumerate(entries, 1):
            expected = entry.sealed().hash if entry.hash else ''
            if entry.prev_hash != prev or (entry.hash and entry.hash != expected):
                return OpResult.failure(
                    f'审计链在 #{index}（{entry.action}）处断裂',
                    detail=f'prev_hash 期望 {prev[:24]}… 实得 {entry.prev_hash[:24]}…',
                )
            prev = entry.hash
        return OpResult.success(detail=f'共 {len(entries)} 条，链完整')

    def stats(self) -> dict[str, int]:
        """写入失败数与当前条数（失败不静默）。"""
        return {
            'entries': len(self._read_all()),
            'failed_writes': self._failed_writes,
            'corrupt_lines': self._corrupt_lines,
        }

    # ---- 内部 ----

    def _tail_hash(self) -> str:
        """读取文件尾哈希作为新条目的 prev_hash（链尾为空则 GENESIS）。"""
        if not self.path.is_file():
            return GENESIS_HASH
        try:
            with self.path.open('r', encoding='utf-8') as fh:
                last_hash = GENESIS_HASH
                for line in fh:
                    if not line.strip():
                        continue
                    entry = decode_line(line.strip())
                    if entry is not None and entry.hash:
                        last_hash = entry.hash
                return last_hash
        except OSError:
            return GENESIS_HASH

    def _read_all(self) -> list[AuditEntry]:
        if not self.path.is_file():
            return []
        out: list[AuditEntry] = []
        corrupt = 0
        try:
            with self.path.open('r', encoding='utf-8') as fh:
                for line in fh:
                    if not line.strip():
                        continue
                    entry = decode_line(line.strip())
                    if entry is None:
                        corrupt += 1
                        continue
                    out.append(entry)
        except OSError:
            self._corrupt_lines = corrupt
            return []
        self._corrupt_lines = corrupt
        return out

    @staticmethod
    def _match(entry: AuditEntry, filters: dict[str, Any]) -> bool:
        for key, want in filters.items():
            if want is None:
                continue
            if key == 'ts_from':
                if entry.ts < float(want):
                    return False
                continue
            if key == 'ts_to':
                if entry.ts > float(want):
                    return False
                continue
            value = getattr(entry, key, None)
            if value is None:
                return False
            actual = value.value if hasattr(value, 'value') else value
            if str(actual) != str(want):
                return False
        return True
