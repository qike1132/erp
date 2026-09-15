"""Domain → JSON DTO 序列化。

═══════════════════════════════════════════════════════════════════
为什么序列化要单独成一层，而不是在 bridge 里随手 json.dumps
═══════════════════════════════════════════════════════════════════

三个具体理由：

**① Enum 不能直接过 JSON。**
`ServiceStatus.RUNNING` 是 enum，`json.dumps` 会炸。而如果各处随手写
`str(status)`，得到的是 `'ServiceStatus.RUNNING'` —— 前端拿到这个字符串
没法判断，只能去 `includes('RUNNING')`，于是**领域判定又在前端复活了**。
所以这里统一给出 `status`（机器用的短码）+ `status_label`（给人看的中文），
前端只做「显示什么」，不做「怎么判定」。

**② 「失败原因」不能丢。**
`OpResult` 有 `ok/reason/detail` 三元组。若序列化时只取 `ok` 和
`detail`，`reason` 就丢了 —— 而 UI 往往要按 `reason` 分类展示
（「权限不足」要弹提权，「端口被占」要弹清理）。所以三个字段全保留。

**③ 时间戳要带单位说明。**
`ts` 是 monotonic 秒（不是 wall clock），前端不能拿它去 `new Date()`。
字段名统一加 `_s` 后缀（`ts_s` / `remaining_s`），并在此注明 ——
让「这是个秒数」在字段名上就能看出来。

═══════════════════════════════════════════════════════════════════
★ 一条纪律：这里不做任何判定
═══════════════════════════════════════════════════════════════════

本模块只做「翻译」，不做「判断」。所有 `is_xxx` / `should_xxx` 的结论
必须来自 domain 层已经算好的属性，而不是在这里重新写一遍条件。

例如 `ServiceSnapshot.status_label` 用的是 `domain.service_state` 的分类结果，
不是 `if code == 'RUNNING': return '运行中'` —— 后者就是复制领域判定，
将来领域层改了口径这里不会跟着改。
"""

from __future__ import annotations

from enum import Enum
from typing import Any

from ..domain.permissions import Action, DangerLevel, Role

# ═══════════════════════════════════════════════════════════════════
# 基础原语
# ═══════════════════════════════════════════════════════════════════


def enum_value(value: Any) -> Any:
    """Enum → 其 `value`（不是 `str(enum)`）。

    ★ 必须用 `.value`：`str(ServiceStatus.RUNNING)` 得到
      `'ServiceStatus.RUNNING'`，前端拿这个字符串只能做子串匹配，
      等于把枚举判定搬到前端。`.value` 得到 `'RUNNING'` 这个稳定短码。
    """
    if isinstance(value, Enum):
        return value.value
    return value


def op_result(result: Any) -> dict[str, Any]:
    """`OpResult` → DTO。

    ★ `reason` 必须保留：UI 要按它分类（权限不足 → 弹提权；
      端口被占 → 弹清理）。只给 `detail` 的话前端只能正则匹配文案，
      文案一改就失效。
    """
    if result is None:
        return {'ok': False, 'reason': '内部错误', 'detail': '结果为空'}
    return {
        'ok': bool(getattr(result, 'ok', False)),
        'reason': getattr(result, 'reason', '') or '',
        'detail': getattr(result, 'detail', '') or '',
    }


def permission_check(check: Any) -> dict[str, Any]:
    """`PermissionCheck` → DTO（前端据此决定按钮是否锁定）。

    ★ 字段是 `action` 不是 `required` —— 它带的是「这个检查针对哪个操作」。
      前端要的「需要什么角色」由 `required_role(action)` 单独取，
      不在这个 DTO 里重复（重复就有两份来源）。
    """
    if check is None:
        return {}
    out: dict[str, Any] = {}
    for field in ('allowed', 'role', 'reason'):
        if not hasattr(check, field):
            continue
        value = getattr(check, field)
        out[field] = enum_value(value) if isinstance(value, Enum) else value

    action = getattr(check, 'action', None)
    if action is not None:
        out['action'] = action.value if isinstance(action, Action) else str(action)
    return out


# ═══════════════════════════════════════════════════════════════════
# 权限与角色
# ═══════════════════════════════════════════════════════════════════


def role_info(role: Role) -> dict[str, Any]:
    return {
        'value': role.value,
        'label': role.label,
        'level': role.level,
    }


def session_state(session: Any) -> dict[str, Any]:
    """会话快照（前端顶栏与角色徽章用）。"""
    state = session.state()
    return {
        'role': enum_value(state.role),
        'role_label': getattr(state.role, 'label', ''),
        'expires_at': state.expires_at,
        'remaining_s': round(float(state.remaining_s), 1),
        'elevated': bool(state.elevated),
    }


def action_meta(action: Action) -> dict[str, Any]:
    """操作的展示元数据（标题 / 危险等级 / 确认方式）。

    ★ 前端**不应**自己维护一份「哪个操作是 L2」的表 —— 两份表必然漂移，
      而漂移之后是权限绕过（前端以为是 L1 就只给轻确认，后端却按 L3 拒了，
      用户看到的是「确认了但没反应」）。
    """
    level = action.danger
    return {
        'value': action.value,
        'label': action.label,
        'danger': level.value,
        'danger_label': level.label,
        'requires_reason': level.requires_reason,
        'requires_typed': level.requires_typed_confirmation,
        'requires_modal': level.requires_modal_confirm,
        'supports_undo': level.supports_undo,
    }


def danger_level(level: DangerLevel) -> dict[str, Any]:
    return {
        'value': level.value,
        'label': level.label,
        'requires_reason': level.requires_reason,
        'requires_typed': level.requires_typed_confirmation,
        'requires_modal': level.requires_modal_confirm,
        'supports_undo': level.supports_undo,
    }


# ═══════════════════════════════════════════════════════════════════
# 服务与进程
# ═══════════════════════════════════════════════════════════════════


#: 服务状态 → 中文名。
#:
#: ★ 这份表**放在展示层**而不是 domain，是刻意的职责划分：
#:   `ServiceStatus` 的**判定**（哪些算运行中、哪些算未知）是领域规则，
#:   已在 domain 里；而「RUNNING 显示成『运行中』」是**文案**，
#:   换语言 / 换措辞不该动领域层。
#:
#: 反面例子：把文案塞进 domain 的 `label` 属性 —— 于是领域层为了
#: 一个 UI 字符串而存在，且中文翻译要改就得改业务内核。
SERVICE_STATUS_LABELS: dict[str, str] = {
    'running': '运行中',
    'stopped': '已停止',
    'pending': '状态变更中',
    'unknown': '状态未知',
    'absent': '未安装',
}

#: 服务状态 → 视觉色调（前端 CSS 变量名，不含 var() 外壳）
SERVICE_STATUS_TONES: dict[str, str] = {
    'running': 'success',
    'stopped': 'text-3',
    'pending': 'warning',
    'unknown': 'warning',   # ★ 未知用 warning 而非灰色：它需要用户注意
    'absent': 'text-3',
}


def service_status_label(status: Any) -> str:
    code = enum_value(status)
    return SERVICE_STATUS_LABELS.get(str(code), str(code))


def service_status_tone(status: Any) -> str:
    code = enum_value(status)
    return SERVICE_STATUS_TONES.get(str(code), 'text-3')


def service_snapshot(snapshot: Any) -> dict[str, Any]:
    """`ServiceSnapshot` → DTO。

    ★ 字段名是 `service` 不是 `name`（domain 层的实际定义），
      这里额外补一个 `name` 别名给前端用 —— 但**保留原始 `service`**，
      免得将来有人只改前端忘了后端时两边对不上。
    """
    if snapshot is None:
        return {}
    out: dict[str, Any] = {
        'service': getattr(snapshot, 'service', ''),
        'raw_state': getattr(snapshot, 'raw_state', ''),
    }
    out['name'] = out['service']

    status = getattr(snapshot, 'status', None)
    if status is not None:
        out['status'] = enum_value(status)
        #: ★ 判定取自 domain（is_* 系列），文案取自本模块的映射表
        out['status_label'] = service_status_label(status)
        out['tone'] = service_status_tone(status)
        out['is_absent'] = bool(getattr(status, 'is_absent', False))
        out['is_unknown'] = bool(getattr(status, 'is_unknown', False))
        out['running'] = bool(getattr(status, 'is_conservatively_running', False))

    pid = getattr(snapshot, 'pid', None)
    out['pid'] = pid
    out['has_pid'] = bool(pid)
    #: ★「阻断模式切换」的结论来自 domain，不在前端重算
    out['blocks_switch'] = bool(getattr(snapshot, 'blocks_switch', False))
    return out


def port_occupier(info: Any) -> dict[str, Any]:
    """`PortOccupierInfo` → DTO。"""
    if info is None:
        return {}
    return {
        'port': getattr(info, 'port', 0),
        'pid': getattr(info, 'pid', 0),
        'name': getattr(info, 'name', ''),
        'local_addr': getattr(info, 'local_addr', ''),
        'state': getattr(info, 'state', ''),
        'label': getattr(info, 'label', ''),
    }


def kill_result(result: Any) -> dict[str, Any]:
    """`KillResult` → DTO。

    ★ `targeted` 必须传出：`targeted == 0` 表示「没找到可杀进程」，
      这是**失败**（端口仍被占）。前端只有拿到这个数才能正确提示
      「未找到可终止的进程」而不是误报「清理成功」。

    ★ `error` 与 `ok` 的关系要说清（domain 的注释已强调）：
      `ok = (error is None)` 只表示「命令没报错」，**不等于进程已死**。
      所以这里额外给出 `effective`（真的杀掉了目标），前端提示
      「已清理」时应当看它而不是看 `ok`。
    """
    if result is None:
        return {'ok': False, 'error': '内部错误', 'targeted': 0, 'effective': False}

    targeted = int(getattr(result, 'targeted', 0) or 0)
    error = getattr(result, 'error', None)
    ok = bool(getattr(result, 'ok', False))
    return {
        'ok': ok,
        'error': error or '',
        'targeted': targeted,
        'rounds': int(getattr(result, 'rounds', 0) or 0),
        'backend': getattr(result, 'backend', '') or '',
        'did_attempt': bool(getattr(result, 'did_attempt', ok)),
        #: ★ 真的杀掉了目标（而不只是「命令没报错」）
        'effective': ok and targeted > 0,
    }


# ═══════════════════════════════════════════════════════════════════
# 指标与健康
# ═══════════════════════════════════════════════════════════════════


def metrics_sample(sample: Any) -> dict[str, Any] | None:
    """`MetricsSample` → DTO。

    ★ `None` 透传为 `None`（不是全 0 字典）—— `psutil` 不可用时前端必须
      显示「指标不可用」，而显示 0% 会被读成「系统很空闲」。

    ★ 字段名为 domain 的实际定义：`mem_rss_mb`（本进程常驻内存）与
      `procs`（进程数）。不要臆造成 `mem_total_mb` / `proc_count` ——
      domain 不提供总内存（那是 `psutil.virtual_memory()` 的事，
      由前端或后续扩展决定，不该在这里编一个）。
    """
    if sample is None:
        return None
    return {
        'cpu_percent': getattr(sample, 'cpu_percent', None),
        'mem_percent': getattr(sample, 'mem_percent', None),
        'mem_rss_mb': getattr(sample, 'mem_rss_mb', None),
        'procs': getattr(sample, 'procs', None),
        'detail': getattr(sample, 'detail', '') or '',
    }


def health_sample(sample: Any) -> dict[str, Any]:
    """`HealthSample` → DTO。

    ★ domain 的 `HealthSample` **没有** `reason` 字段（只有
      `ok/latency_ms/status_code/detail`）—— 探针失败的原因是文本，
      没有分类码。这里不硬塞一个 `reason` 出来假装有分类。
    """
    if sample is None:
        return {}
    return {
        'ok': bool(getattr(sample, 'ok', False)),
        'latency_ms': getattr(sample, 'latency_ms', None),
        'status_code': getattr(sample, 'status_code', None),
        'detail': getattr(sample, 'detail', '') or '',
    }


# ═══════════════════════════════════════════════════════════════════
# 审计
# ═══════════════════════════════════════════════════════════════════


def audit_entry(entry: Any) -> dict[str, Any]:
    if entry is None:
        return {}
    return {
        'ts': getattr(entry, 'ts', 0.0),
        'actor': getattr(entry, 'actor', ''),
        'action': getattr(entry, 'action', ''),
        'target': getattr(entry, 'target', ''),
        'outcome': enum_value(getattr(entry, 'outcome', '')),
        'reason': getattr(entry, 'reason', ''),
        'detail': getattr(entry, 'detail', ''),
        'trace_id': getattr(entry, 'trace_id', ''),
        'entry_hash': getattr(entry, 'entry_hash', ''),
        'prev_hash': getattr(entry, 'prev_hash', ''),
    }


def chain_verify(result: Any) -> dict[str, Any]:
    """审计链校验结果 → DTO。

    ★ `ok=False` 时 `broken_at` 一定要给出来 —— 「链断了」但不告诉
      断在哪一条，运维没法定位被篡改的范围。

    ★ 计数字段名是 `total`（domain 的实际定义），不是 `checked`。
    """
    if result is None:
        return {'ok': None, 'total': 0}
    return {
        'ok': bool(getattr(result, 'ok', False)),
        'total': int(getattr(result, 'total', 0) or 0),
        'broken_at': getattr(result, 'broken_at', None),
        'reason': getattr(result, 'reason', '') or '',
    }


# ═══════════════════════════════════════════════════════════════════
# 告警
# ═══════════════════════════════════════════════════════════════════


#: 告警级别 → 中文名（★ 同样是展示层文案，不是领域规则）
SEVERITY_LABELS: dict[str, str] = {
    'P0': 'P0 紧急',
    'P1': 'P1 严重',
    'P2': 'P2 警告',
    'P3': 'P3 提示',
    'info': '信息',
}


def severity_label(severity: Any) -> str:
    code = enum_value(severity)
    return SEVERITY_LABELS.get(str(code), str(code))


def alert(alert_obj: Any) -> dict[str, Any]:
    if alert_obj is None:
        return {}
    severity = getattr(alert_obj, 'severity', None)
    return {
        'key': getattr(alert_obj, 'key', ''),
        'severity': enum_value(severity),
        #: ★ `Severity` 在 domain 里**没有** label 属性（它是纯分级枚举），
        #:   中文名由本模块的映射表提供，不硬塞一个 domain 属性。
        'severity_label': severity_label(severity),
        'is_page': bool(getattr(severity, 'is_page', False)),
        'title': getattr(alert_obj, 'title', ''),
        'body': getattr(alert_obj, 'body', ''),
        'raised_at': getattr(alert_obj, 'raised_at', 0.0),
        'acked_at': getattr(alert_obj, 'acked_at', None),
        'acked_by': getattr(alert_obj, 'acked_by', ''),
        'silenced_until': getattr(alert_obj, 'silenced_until', None),
        'silenced_by': getattr(alert_obj, 'silenced_by', ''),
        'is_acked': bool(getattr(alert_obj, 'is_acked', False)),
        'active': bool(getattr(alert_obj, 'active', False)),
    }


# ═══════════════════════════════════════════════════════════════════
# 配置
# ═══════════════════════════════════════════════════════════════════


def normalized_config(config: Any) -> dict[str, Any]:
    """归一化配置 → DTO（扁平 dict，字段与 config_schema 一致）。"""
    if config is None:
        return {}
    if isinstance(config, dict):
        return {k: enum_value(v) for k, v in config.items()}
    out: dict[str, Any] = {}
    for field in getattr(config, '__dataclass_fields__', {}):
        out[field] = enum_value(getattr(config, field))
    return out


# ═══════════════════════════════════════════════════════════════════
# 事件
# ═══════════════════════════════════════════════════════════════════


def event_payload(event: Any) -> dict[str, Any]:
    """事件 → 前端可用的 DTO。

    ★ 用 `__dataclass_fields__` 反射而不是逐类型手写映射 ——
      事件类型有 21 个，手写映射漏一个就是「某个事件前端收不到」，
      而且只在特定操作路径上才暴露。反射保证新增事件自动可用。
    """
    if event is None:
        return {}

    out: dict[str, Any] = {'kind': getattr(event, 'kind', type(event).__name__)}

    fields = getattr(event, '__dataclass_fields__', None)
    if fields:
        for name in fields:
            if name == 'kind':
                continue
            value = getattr(event, name, None)
            out[name] = _plain(value)
    return out


def _plain(value: Any) -> Any:
    """把任意值递归转成 JSON 可序列化的形态。"""
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, dict):
        return {str(k): _plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [_plain(v) for v in value]
    #: 带 __dataclass_fields__ 的（ServiceSnapshot / MetricsSample / AuditEntry…）
    fields = getattr(value, '__dataclass_fields__', None)
    if fields:
        return {name: _plain(getattr(value, name, None)) for name in fields}
    return str(value)


__all__ = [
    'action_meta',
    'alert',
    'audit_entry',
    'chain_verify',
    'danger_level',
    'enum_value',
    'event_payload',
    'health_sample',
    'kill_result',
    'metrics_sample',
    'normalized_config',
    'op_result',
    'permission_check',
    'port_occupier',
    'role_info',
    'service_snapshot',
    'session_state',
]
