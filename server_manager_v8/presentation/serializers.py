"""Domain → JSON DTO 序列化（Presentation 层边界）。

pywebview JS API 只接受 JSON 安全值；所有 domain 对象在此转为 dict。
StrEnum 一律取 .value；时间戳原样浮点；frozen dataclass 展开为字段字典。
"""

from __future__ import annotations

from typing import Any

from server_manager_v8.application import (
    Alert,
    AuditEntry,
    HealthSample,
    MetricsSample,
    OpResult,
    Session,
    Silence,
)

__all__ = [
    'alert',
    'audit_entry',
    'health_sample',
    'metrics',
    'op_result',
    'plan',
    'service_state',
    'session',
    'silence',
]


def _enum_value(value: Any) -> Any:
    return value.value if hasattr(value, 'value') else value


def op_result(result: OpResult) -> dict[str, Any]:
    """通用操作结果（CLI/UI 共用视图）。"""
    data: dict[str, Any] = {
        'ok': result.ok,
        'reason': result.reason,
        'detail': result.detail,
        'duration_ms': result.duration_ms,
    }
    # KillResult 附加字段（存在时带上）
    for extra in ('killed_pids', 'survivors'):
        if hasattr(result, extra):
            data[extra] = list(getattr(result, extra))
    return data


def alert(a: Alert) -> dict[str, Any]:
    return {
        'key': a.key,
        'severity': a.severity.value,
        'severity_label': a.severity.label,
        'severity_color': a.severity.color,
        'title': a.title,
        'desc': a.desc,
        'service': a.service,
        'family': a.family,
        'status': a.status,
        'firing': a.firing,
        'confirmed': a.confirmed,
        'count': a.count,
        'ts': a.ts,
        'last_ts': a.last_ts,
        'ack_ts': a.ack_ts,
        'ack_by': a.ack_by,
        'resolve_ts': a.resolve_ts,
        'runbook': a.runbook,
        'suggested_action': a.suggested_action,
    }


def session(s: Session, ttl_remaining: float = 0.0) -> dict[str, Any]:
    return {
        'base_role': s.base_role.value,
        'elevated': s.elevated.value if s.elevated else None,
        'elevated_active': s.elevated_active,
        'expires_at': s.expires_at,
        'ttl_remaining': ttl_remaining,
    }


def audit_entry(e: AuditEntry) -> dict[str, Any]:
    return {
        'ts': e.ts,
        'actor': e.actor,
        'role': e.role.value,
        'action': e.action,
        'target': e.target,
        'result': e.result,
        'duration_ms': e.duration_ms,
        'trace_id': e.trace_id,
        'reason': e.reason,
        'hash': e.hash[:24],
    }


def silence(s: Silence) -> dict[str, Any]:
    return {
        'id': s.id,
        'service': s.service,
        'family': s.family,
        'start_ts': s.start_ts,
        'end_ts': s.end_ts,
        'reason': s.reason,
        'created_by': s.created_by,
    }


def metrics(m: MetricsSample) -> dict[str, Any]:
    return {
        'cpu': m.cpu,
        'mem': m.mem,
        'disk': m.disk,
        'net_dn_mb': m.net_dn_mb,
        'net_up_kb': m.net_up_kb,
        'saturation': round(m.saturation, 1),
        'procs': [list(p) for p in m.procs],
    }


def health_sample(s: HealthSample) -> dict[str, Any]:
    return {
        'ok': s.ok,
        'latency_ms': s.latency_ms,
        'status_code': s.status_code,
        'error': s.error,
        'consecutive_fail': s.consecutive_fail,
    }


def plan(p: object) -> dict[str, Any]:
    """SwitchPlan 序列化（UI 展示 teardown/startup 步骤）。"""
    return {
        'action': _enum_value(getattr(p, 'action', '')),
        'target': _enum_value(getattr(p, 'target', '')),
        'teardown': _enum_value(getattr(p, 'teardown', '')),
        'startup': _enum_value(getattr(p, 'startup', '')),
        'from_mode': _enum_value(getattr(p, 'from_mode', '')),
    }


def service_state(state: object) -> dict[str, Any]:
    return {'state': _enum_value(state)}
