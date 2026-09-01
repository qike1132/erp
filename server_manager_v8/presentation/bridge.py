"""JS Bridge — 一个方法 = 一个 UseCase（pywebview JS API 的纯 Python 定义）。

设计：
    - Bridge 不依赖 pywebview：webview_host 负责把方法 expose 给 JS，并把
      事件总线事件序列化后推送进页面（window.__push）
    - 权限边界：每个操作执行方法都走 guard.authorize（TOCTOU 防护）；
      另提供 authorize() 供 UI 预检（决定置灰/弹确认/弹提权）
    - 返回值全部是 JSON 安全 dict（serializers 产出）
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from server_manager_v8.application import (
    Action,
    HealthTarget,
    OpResult,
    PermissionDeniedError,
    Role,
)
from server_manager_v8.application.events import (
    AlertRaised,
    AlertResolved,
    AuthChanged,
    Event,
    LogAppended,
    MetricsUpdated,
    ModeChanged,
    PipelineFinished,
    PipelineStarted,
    StepUpdated,
    ToastRequested,
)
from server_manager_v8.container import Container
from server_manager_v8.presentation import serializers as ser

__all__ = ['Bridge']


class BridgeQueriesMixin:
    """只读查询与权限预检（R4：每类方法 ≤20）。"""

    def __init__(self, container: Container) -> None:
        self._c = container

    # ===================== 只读查询 =====================

    def status(self) -> dict[str, Any]:
        """运行模式 / 服务状态 / Redis / 进程快照 / 告警计数。"""
        c = self._c
        services = []
        if c.service is not None:
            for name in ('erp-prod', 'erp-arq'):
                state = c.service.state(name)
                services.append({'name': name, 'state': state.value,
                                 'pid': c.service.pid(name)})
        redis = c.health.probe(HealthTarget(name='redis', kind='redis', port=6379))
        return {
            'mode': c.machine.mode.value,
            'switching': c.machine.switching,
            'services': services,
            'redis_ok': redis.ok,
            'redis_error': redis.error,
            'handles': c.state.snapshot(),
            'alerts_unconfirmed': c.center.unconfirmed_count(),
            'audit_entries': c.audit.stats()['entries'] if c.audit else 0,
        }

    def alerts(self) -> dict[str, Any]:
        c = self._c
        return {
            'items': [ser.alert(a) for a in c.center.alerts],
            'stats': c.center.stats(),
            'silences': [ser.silence(s) for s in c.silences.items],
        }

    def config(self) -> dict[str, Any]:
        return self._c.config.load() if self._c.config else {}

    def logs(self, source: str = '', limit: int = 500) -> dict[str, Any]:
        if self._c.logs is None:
            return {'files': [], 'content': '', 'error': '日志模块未装配'}
        result = self._c.logs.export(source=source, limit=limit)
        return {
            'files': [{'name': f[0], 'size': f[1]} for f in self._c.logs.list_files()],
            'content': result.detail if result.ok else '',
            'error': '' if result.ok else result.reason,
        }

    def metrics(self) -> dict[str, Any] | None:
        if self._c.metrics is None or not self._c.metrics.available():
            return None
        sample = self._c.metrics.sample()
        return ser.metrics(sample) if sample else None

    def guard_state(self) -> dict[str, Any]:
        """当前会话 + 全部操作的控制元数据（UI 据此渲染权限态）。"""
        guard = self._c.guard
        session = guard.current()
        ops = {}
        for action in Action:
            auth = guard.control(action)
            ops[action.value] = {
                'allowed': auth.allowed,
                'danger': auth.danger.value,
                'control': auth.control,
                'role': auth.role.value,
                'elevate_to': auth.elevate_to.value if auth.elevate_to else None,
            }
        return {
            'session': ser.session(session, guard.ttl_remaining()),
            'ops': ops,
        }

    def audit(self, limit: int = 100) -> list[dict[str, Any]]:
        if self._c.audit is None:
            return []
        return [ser.audit_entry(e) for e in self._c.audit.query()[-limit:]]

    # ===================== 权限预检（不执行） =====================

    def authorize(self, action: str, reason: str = '') -> dict[str, Any]:
        """UI 预检：决定置灰 / 弹确认 / 弹提权（禁用而非隐藏）。"""
        auth = self._c.guard.control(Action(action))
        return {
            'action': action,
            'allowed': auth.allowed,
            'danger': auth.danger.value,
            'control': auth.control,
            'elevate_to': auth.elevate_to.value if auth.elevate_to else None,
            'reason': '' if auth.allowed else auth.reason,
        }

    def elevate(self, to: str, pin: str) -> dict[str, Any]:
        """提权。PIN 校验由 host 层的密码服务完成；此处仅更新会话。"""
        result = self._c.guard.elevate(Role(to))
        if not result.ok:
            return ser.op_result(result)
        self._c.guard.touch()
        return {'ok': True, 'role': to}

    def degrade(self) -> dict[str, Any]:
        self._c.guard.degrade()
        return {'ok': True}

    # ===================== 事件推送（host 层调用） =====================

    def event_payload(self, event: Event) -> dict[str, Any] | None:
        """事件 → JS 推送负载。None = 该事件无需推前端。"""
        if isinstance(event, LogAppended):
            return {'type': 'log', 'level': event.level, 'source': event.source,
                    'text': event.text, 'ts': event.ts}
        if isinstance(event, MetricsUpdated):
            return {'type': 'metrics', 'sample': event.sample}
        if isinstance(event, ModeChanged):
            return {'type': 'mode', 'old': event.old, 'new': event.new}
        if isinstance(event, PipelineStarted):
            return {'type': 'pipeline_start', 'name': event.name, 'steps': event.steps}
        if isinstance(event, StepUpdated):
            return {'type': 'step', 'pipeline': event.pipeline, 'step': event.step,
                    'index': event.index, 'total': event.total, 'state': event.state,
                    'detail': event.detail}
        if isinstance(event, PipelineFinished):
            return {'type': 'pipeline_finish', 'name': event.name, 'ok': event.ok,
                    'reason': event.reason, 'duration_ms': event.duration_ms}
        if isinstance(event, AlertRaised):
            return {'type': 'alert_raised', 'key': event.key, 'severity': event.severity,
                    'title': event.title, 'desc': event.desc}
        if isinstance(event, AlertResolved):
            return {'type': 'alert_resolved', 'key': event.key, 'reason': event.reason}
        if isinstance(event, AuthChanged):
            return {'type': 'auth', 'role': event.role, 'elevated': event.elevated,
                    'expires_at': event.expires_at}
        if isinstance(event, ToastRequested):
            return {'type': 'toast', 'level': event.level, 'text': event.text,
                    'undo_token': event.undo_token, 'undo_ttl_s': event.undo_ttl_s}
        return None

class BridgeActionsMixin:
    """变更操作（一个方法 = 一个 UseCase，权限经 _run 裁决）。"""
    # ===================== 操作（进 UseCase） =====================

    def start_dev(self, reason: str = '') -> dict[str, Any]:
        return self._run(Action.SWITCH_MODE, reason, lambda: self._do_start_dev())

    def start_prod(self, reason: str = '') -> dict[str, Any]:
        return self._run(Action.SWITCH_MODE, reason, lambda: self._do_start_prod())

    def stop_all(self, reason: str = '') -> dict[str, Any]:
        return self._run(Action.STOP_SERVICE, reason, lambda: self._c.stop_all.run())

    def switch_mode(self, target: str, reason: str = '') -> dict[str, Any]:
        return self._run(Action.SWITCH_MODE, reason, lambda: self._c.switch.run(target))

    def kill_port(self, port: int) -> dict[str, Any]:
        return self._run(Action.KILL_PORT, '', lambda: self._c.kill_port.run(port))

    def install_services(self, reason: str) -> dict[str, Any]:
        return self._run(Action.INSTALL_SERVICES, reason, lambda: self._do_install(reason))

    def uninstall_services(self, reason: str) -> dict[str, Any]:
        return self._run(Action.UNINSTALL_SERVICES, reason, lambda: self._do_uninstall(reason))

    def alerts_ack(self, key: str) -> dict[str, Any]:
        return self._run(Action.ACK_ALERT, '', lambda: self._c.alerts.ack(key, by='gui'))

    def alerts_ack_all(self) -> dict[str, Any]:
        return self._run(Action.ACK_ALERT, '', lambda: self._c.alerts.ack_all(by='gui'))

    def silence_add(self, service: str, duration_s: float, reason: str) -> dict[str, Any]:
        return self._run(Action.SILENCE_ALERT, '', lambda: self._c.alerts.add_silence(
            service, duration_s, reason, created_by='gui'))

    def silence_remove(self, silence_id: str) -> dict[str, Any]:
        return self._run(Action.SILENCE_ALERT, '', lambda: self._c.alerts.remove_silence(silence_id))

    def config_save(self, patch: dict[str, Any]) -> dict[str, Any]:
        return self._run(Action.EDIT_CONFIG, '', lambda: self._c.config.save(patch))

    def config_migrate(self) -> dict[str, Any]:
        return self._run(Action.EDIT_CONFIG, '', lambda: self._c.config.migrate())


    def _run(self, action: Action, reason: str, fn: Callable[[], OpResult]) -> dict[str, Any]:
        """执行入口：权限裁决（TOCTOU）→ UseCase → 结果 + 控制元数据。"""
        try:
            auth = self._c.guard.authorize(action, reason)
        except PermissionDeniedError as exc:
            return {
                'ok': False,
                'denied': True,
                'action': action.value,
                'elevate_to': exc.elevate_to.value if exc.elevate_to else None,
                'reason': exc.reason,
            }
        result = fn()
        data = ser.op_result(result)
        data['danger'] = auth.danger.value
        data['control'] = auth.control
        data['action'] = action.value
        if result.ok:
            self._c.guard.touch()
        return data

    def _do_start_dev(self) -> OpResult:
        from server_manager_v8.application.usecases import DevStartSpec

        cfg = self.config()
        project = cfg.get('paths', {}).get('project') or ''
        return self._c.start_dev.run(DevStartSpec(
            python_exe=cfg.get('paths', {}).get('python') or __import__('sys').executable,
            project_dir=project,
            frontend_dir=f'{project}\\frontend-vite' if project else '',
            api_port=int(cfg.get('ports', {}).get('api', 5002)),
            web_port=int(cfg.get('ports', {}).get('web', 3000)),
            redis_port=int(cfg.get('ports', {}).get('redis', 6379)),
            redis_exe=cfg.get('paths', {}).get('redis_exe', ''),
        ), trace_id='gui')

    def _do_start_prod(self) -> OpResult:
        from server_manager_v8.application.usecases import ProdStartSpec

        cfg = self.config()
        return self._c.start_prod.run(ProdStartSpec(
            api_port=int(cfg.get('ports', {}).get('api', 5002)),
        ), trace_id='gui')

    def _do_install(self, reason: str) -> OpResult:
        from server_manager_v8.application.usecases import InstallSpec

        cfg = self.config()
        return self._c.install_services.run(InstallSpec(
            python_exe=cfg.get('paths', {}).get('python') or __import__('sys').executable,
            project_dir=cfg.get('paths', {}).get('project') or '',
        ), reason=reason)

    def _do_uninstall(self, reason: str) -> OpResult:
        return self._c.uninstall_services.run(reason=reason)


class Bridge(BridgeQueriesMixin, BridgeActionsMixin):
    """pywebview JS API 聚合（查询 + 操作 + 事件推送）。

    拆分动机：JS API 方法天然多（一个方法 = 一个 UseCase），
    若单类直写会重蹈 v6 上帝类覆辙 —— 按读写拆分满足门禁 R4（每类 ≤20 方法）。
    """
