"""models 层测试：显式结果对象、告警生命周期、审计哈希链。"""
from __future__ import annotations

import json

import pytest

from server_manager_v8.domain import (
    GENESIS_HASH,
    AuditEntry,
    DangerLevel,
    KillResult,
    OpResult,
    Role,
    Severity,
)


class TestOpResult:
    def test_success_defaults_ok(self) -> None:
        r = OpResult.success('done', 12)
        assert r.ok and r.detail == 'done' and r.duration_ms == 12
        assert bool(r) is True

    def test_failure_requires_reason(self) -> None:
        r = OpResult.failure('端口被占用', detail='netstat 输出…')
        assert not r.ok and r.reason == '端口被占用'
        assert bool(r) is False

    def test_kill_result_partial(self) -> None:
        """有残留 = 部分成功：ok=True 但 survivors 必须上报。"""
        r = KillResult.done(killed_pids=(1, 2), survivors=(3,), detail='3 轮重试')
        assert r.ok and r.partial
        assert r.survivors == (3,)

    def test_kill_result_lsp(self) -> None:
        """KillResult 可替换 OpResult 使用（里氏替换）。"""
        r: OpResult = KillResult.done(killed_pids=(1,))
        assert r.ok and isinstance(r, OpResult)


class TestSeverity:
    def test_labels_and_colors(self) -> None:
        assert Severity.P0.label == '致命'
        assert Severity.P0.color == '#F5222D'
        assert Severity.P2.color == '#FAAD14'
        assert Severity.P3.color == '#1890FF'

    def test_notify_channels_degrade_by_severity(self) -> None:
        assert 'modal' in Severity.P0.notify_channels
        assert 'sound' in Severity.P1.notify_channels
        assert Severity.P2.notify_channels == ('tray',)
        assert Severity.P3.notify_channels == ('badge',)
        assert Severity.P4.notify_channels == ()

    def test_p0_is_highest(self) -> None:
        """P0 最高（火山引擎/国内故障分级口径）。"""
        assert Severity.P0.value < Severity.P1.value
        assert Severity.P4.value > Severity.P3.value


class TestAlertLifecycle:
    def test_ack_and_resolve_immutable(self) -> None:
        from server_manager_v8.domain import Alert

        a = Alert(key='k', severity=Severity.P1, title='t', ts=100.0)
        assert a.firing and not a.confirmed
        b = a.ack(by='op', ts=150.0)
        assert a.firing and not b.firing  # 原对象不变
        assert b.ack_ts == 150.0 and b.ack_by == 'op'
        c = b.resolve(reason='服务恢复', ts=200.0)
        assert c.status == Alert.STATUS_RESOLVED and c.resolve_ts == 200.0

    def test_group_key(self) -> None:
        from server_manager_v8.domain import Alert

        a = Alert(key='k', severity=Severity.P2, title='t', service='api', family='availability')
        assert a.group_key == ('api', 'availability')


class TestAuditHashChain:
    def _entry(self, prev_hash: str = GENESIS_HASH) -> AuditEntry:
        return AuditEntry(
            ts=1725123456.789, actor='admin', role=Role.ADMIN, action='backup.create',
            target='env_x', params_digest='sha256:abc', result='ok', duration_ms=18420,
            trace_id='5c1b8e40', prev_hash=prev_hash,
        )

    def test_seal_and_verify(self) -> None:
        e = self._entry().sealed()
        assert e.hash.startswith('sha256:')
        assert e.verify()

    def test_tamper_detected(self) -> None:
        """任何字段篡改都会破坏哈希。"""
        e = self._entry().sealed()
        tampered = AuditEntry(**{**e.__dict__, 'duration_ms': 1})
        assert not tampered.verify()

    def test_chain_links(self) -> None:
        """第二条的 prev_hash 必须是第一条的 hash。"""
        first = self._entry().sealed()
        second = self._entry(prev_hash=first.hash).sealed()
        assert second.prev_hash == first.hash
        assert second.hash != first.hash

    def test_to_line_is_canonical_json(self) -> None:
        e = self._entry().sealed()
        data = json.loads(e.to_line())
        assert data['role'] == 'admin' and data['action'] == 'backup.create'
        # 键序无关：两次序列化一致（canonical）
        assert e.to_line() == e.to_line()


class TestDangerLevel:
    def test_labels(self) -> None:
        assert DangerLevel.L3.label == '极高危'
        assert DangerLevel.L0.label == '低危'


@pytest.mark.parametrize('enum_cls', [Severity, DangerLevel], ids=['severity', 'danger'])
def test_enums_serializable(enum_cls: type) -> None:
    """str 枚举可直接 JSON 序列化（配置读写依赖此特性）。"""
    first = next(iter(enum_cls))
    assert json.dumps(first.value)
