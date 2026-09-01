"""Bridge 层测试：DTO 序列化、权限裁决（TOCTOU）、事件推送负载。

用最小 Fake 容器 —— Bridge 不依赖完整 Container 的字段，只要用到的不为 None。
"""
from __future__ import annotations

from server_manager_v8.application import AuthGuard, EventBus, RuntimeState
from server_manager_v8.application.events import (
    AlertRaised,
    AuthChanged,
    LogAppended,
    MetricsUpdated,
    ModeChanged,
    PipelineFinished,
    StepUpdated,
    ToastRequested,
)
from server_manager_v8.application.usecases import AlertOpsUseCase, ConfigOpsUseCase
from server_manager_v8.container import Container
from server_manager_v8.domain import (
    Alert,
    AlertCenter,
    AuthPolicy,
    HealthSample,
    HealthTarget,
    ModeMachine,
    Role,
    Session,
    Severity,
    SilenceBook,
)
from server_manager_v8.presentation.bridge import Bridge


class FakeHealth:
    def probe(self, target: HealthTarget) -> HealthSample:
        return HealthSample.healthy(latency_ms=3)


class FakeService:
    def state(self, name: str):
        return __import__('server_manager_v8.domain', fromlist=['ServiceState']).ServiceState.STOPPED

    def pid(self, name: str):
        return None


class FakeStorage:
    def __init__(self) -> None:
        self.data = {'schema_version': 2, 'app': {'theme': 'dark'}}

    def load(self) -> dict:
        return self.data

    def save(self, data: dict):
        self.data = data
        return __import__('server_manager_v8.domain', fromlist=['OpResult']).OpResult.success()

    def migrate(self, data: dict):
        return data, False


def make_bridge(viewer: bool = True):
    c = Container(
        bus=EventBus(),
        machine=ModeMachine(),
        state=RuntimeState(),
        guard=AuthGuard(AuthPolicy(), clock=lambda: 1000.0),
        center=AlertCenter(),
        silences=SilenceBook(),
        health=FakeHealth(),
        service=FakeService(),
    )
    c.config = ConfigOpsUseCase(FakeStorage(), {})
    c.alerts = AlertOpsUseCase(c.center, c.silences)
    if not viewer:
        c.guard.set_session(Session(base_role=Role.OPERATOR))
    return Bridge(c), c


class TestQueries:
    def test_status_shape(self) -> None:
        bridge, _ = make_bridge()
        s = bridge.status()
        assert s['mode'] == 'idle'
        assert isinstance(s['services'], list)
        assert 'redis_ok' in s and 'alerts_unconfirmed' in s

    def test_alerts_shape(self) -> None:
        bridge, c = make_bridge()
        c.center.ingest(Alert(key='k', severity=Severity.P1, title='t', service='api', ts=0.0), ts=0.0)
        data = bridge.alerts()
        assert data['items'][0]['severity'] == 'P1'
        assert data['items'][0]['severity_label'] == '严重'
        assert data['items'][0]['severity_color'] == '#FA8C16'
        assert data['stats']['firing'] == 1

    def test_config_shape(self) -> None:
        bridge, _ = make_bridge()
        assert bridge.config()['schema_version'] == 2

    def test_guard_state_ops_matrix(self) -> None:
        bridge, _ = make_bridge()
        g = bridge.guard_state()
        assert g['session']['base_role'] == 'viewer'
        assert g['ops']['view']['allowed'] is True
        assert g['ops']['uninstall_services']['elevate_to'] == 'admin'

    def test_audit_empty_when_unconfigured(self) -> None:
        bridge, _ = make_bridge()
        assert bridge.audit() == []


class TestAuthorization:
    def test_viewer_denied_stop(self) -> None:
        bridge, _ = make_bridge(viewer=True)
        auth = bridge.authorize('stop_service')
        assert not auth['allowed']
        assert auth['elevate_to'] == 'operator'
        assert auth['danger'] == 'L2'

    def test_operator_allowed_stop(self) -> None:
        bridge, _ = make_bridge(viewer=False)
        auth = bridge.authorize('stop_service')
        assert auth['allowed']
        assert auth['control'] == 'confirm_impact'

    def test_stop_all_denied_for_viewer(self) -> None:
        bridge, _ = make_bridge(viewer=True)
        r = bridge.stop_all()
        assert r['denied'] is True and r['ok'] is False
        assert r['elevate_to'] == 'operator'

    def test_ack_allowed_for_viewer(self) -> None:
        bridge, c = make_bridge(viewer=True)
        c.center.ingest(Alert(key='k', severity=Severity.P3, title='t', ts=0.0), ts=0.0)
        r = bridge.alerts_ack_all()
        assert r['ok'] and c.center.unconfirmed_count() == 0

    def test_elevate_degrade_flow(self) -> None:
        bridge, _ = make_bridge(viewer=True)
        assert bridge.elevate('operator', pin='x')['ok']
        assert bridge.guard_state()['session']['elevated'] == 'operator'
        assert bridge.degrade()['ok']
        assert bridge.guard_state()['session']['elevated_active'] is False


class TestEventPayload:
    def _bridge(self):
        bridge, _ = make_bridge()
        return bridge

    def test_log(self) -> None:
        p = self._bridge().event_payload(LogAppended(level='ERROR', text='boom'))
        assert p['type'] == 'log' and p['level'] == 'ERROR'

    def test_metrics(self) -> None:
        p = self._bridge().event_payload(MetricsUpdated(sample={'cpu': 1.0}))
        assert p['type'] == 'metrics' and p['sample']['cpu'] == 1.0

    def test_mode(self) -> None:
        p = self._bridge().event_payload(ModeChanged(old='idle', new='dev'))
        assert p['type'] == 'mode' and p['new'] == 'dev'

    def test_step_and_finish(self) -> None:
        b = self._bridge()
        s = b.event_payload(StepUpdated(pipeline='p', step='s', index=1, total=4, state='running'))
        assert s['state'] == 'running'
        f = b.event_payload(PipelineFinished(name='p', ok=True, duration_ms=12))
        assert f['ok'] and f['duration_ms'] == 12

    def test_alerts(self) -> None:
        b = self._bridge()
        assert b.event_payload(AlertRaised(key='k', severity='P1', title='t'))['type'] == 'alert_raised'
        assert b.event_payload(AlertRaised(key='k', severity='P1', title='t'))['severity'] == 'P1'

    def test_auth_and_toast(self) -> None:
        b = self._bridge()
        assert b.event_payload(AuthChanged(role='viewer'))['type'] == 'auth'
        t = b.event_payload(ToastRequested(level='warn', text='x'))
        assert t['type'] == 'toast' and t['undo_ttl_s'] == 5.0
