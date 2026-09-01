"""审计适配器测试：append-only、哈希链完整性与篡改检出、永不抛出。"""
from __future__ import annotations

from pathlib import Path

from server_manager_v8.adapters.audit_jsonl import AuditJsonlStore, decode_line
from server_manager_v8.domain import AuditEntry, Role


def _entry(ts: float, action: str = 'backup.create', prev: str | None = None) -> AuditEntry:
    return AuditEntry(
        ts=ts, actor='admin', role=Role.ADMIN, action=action, target='env_x',
        result='ok', duration_ms=100, trace_id='t1', prev_hash=prev or 'sha256:' + '0' * 64,
    )


class TestRecordAndQuery:
    def test_record_appends_sealed(self, tmp_path: Path) -> None:
        store = AuditJsonlStore(tmp_path / 'audit.jsonl')
        store.record(_entry(ts=1.0))
        store.record(_entry(ts=2.0, action='alert.raise'))
        lines = (tmp_path / 'audit.jsonl').read_text(encoding='utf-8').strip().splitlines()
        assert len(lines) == 2
        first = decode_line(lines[0])
        assert first is not None and first.hash  # 已封印

    def test_hash_chain_linked(self, tmp_path: Path) -> None:
        store = AuditJsonlStore(tmp_path / 'audit.jsonl')
        store.record(_entry(ts=1.0))
        store.record(_entry(ts=2.0))
        entries = store.query()
        assert entries[1].prev_hash == entries[0].hash  # 第二条链上第一条

    def test_query_filters(self, tmp_path: Path) -> None:
        store = AuditJsonlStore(tmp_path / 'audit.jsonl')
        store.record(_entry(ts=1.0, action='backup.create'))
        store.record(_entry(ts=2.0, action='alert.raise'))
        store.record(_entry(ts=3.0, action='switch_mode'))
        assert len(store.query(action='alert.raise')) == 1
        assert len(store.query(ts_from=2.0)) == 2
        assert len(store.query(ts_to=2.0)) == 2
        assert len(store.query(role='admin')) == 3

    def test_record_never_throws(self, tmp_path: Path) -> None:
        """写不进去也必须不抛（审计不能影响主流程）→ 失败计数上报。"""
        blocker = tmp_path / 'blocker.txt'
        blocker.write_text('我是文件不是目录', encoding='utf-8')
        store = AuditJsonlStore(blocker / 'audit.jsonl')
        store.record(_entry(ts=1.0))
        store.record(_entry(ts=2.0))
        assert store.stats()['failed_writes'] == 2
        assert store.stats()['entries'] == 0


class TestVerifyChain:
    def test_verify_ok(self, tmp_path: Path) -> None:
        store = AuditJsonlStore(tmp_path / 'audit.jsonl')
        for i in range(5):
            store.record(_entry(ts=float(i), action=f'act{i}'))
        result = store.verify_chain()
        assert result.ok and '5 条' in result.detail

    def test_tamper_detected(self, tmp_path: Path) -> None:
        store = AuditJsonlStore(tmp_path / 'audit.jsonl')
        store.record(_entry(ts=1.0, action='aaa'))
        store.record(_entry(ts=2.0, action='bbb'))
        path = tmp_path / 'audit.jsonl'
        # 篡改第一条的 action 字段（哈希链应立即断裂；canonical JSON 无空格）
        lines = path.read_text(encoding='utf-8').splitlines()
        tampered = lines[0].replace('"action":"aaa"', '"action":"hacked"')
        path.write_text('\n'.join([tampered, *lines[1:]]) + '\n', encoding='utf-8')
        result = store.verify_chain()
        assert not result.ok and '断裂' in result.reason

    def test_mid_chain_tamper_breaks_second_link(self, tmp_path: Path) -> None:
        store = AuditJsonlStore(tmp_path / 'audit.jsonl')
        for i in range(3):
            store.record(_entry(ts=float(i)))
        path = tmp_path / 'audit.jsonl'
        lines = path.read_text(encoding='utf-8').splitlines()
        lines[1] = lines[1].replace('"result":"ok"', '"result":"fail"', 1)
        path.write_text('\n'.join(lines) + '\n', encoding='utf-8')
        assert not store.verify_chain().ok

    def test_empty_chain_ok(self, tmp_path: Path) -> None:
        assert AuditJsonlStore(tmp_path / 'audit.jsonl').verify_chain().ok


class TestDecodeLine:
    def test_corrupt_line_returns_none(self) -> None:
        assert decode_line('{ 这不是 JSON') is None
        assert decode_line('[]') is None  # 非对象

    def test_roundtrip(self, tmp_path: Path) -> None:
        store = AuditJsonlStore(tmp_path / 'a.jsonl')
        store.record(_entry(ts=7.0))
        entry = store.query()[0]
        assert entry.ts == 7.0 and entry.action == 'backup.create'
        assert entry.role is Role.ADMIN
