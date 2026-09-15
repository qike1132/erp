"""Domain 层 —— 纯业务逻辑，零 I/O。

═══════════════════════════════════════════════════════════════════
本层不可违反的约束（由 scripts/check_domain_purity.py 强制门禁）
═══════════════════════════════════════════════════════════════════

禁止导入：subprocess / os / sys / shutil / pathlib / socket / psutil /
          logging / time / datetime / tkinter / webview / glob /
          tempfile / signal / ctypes / winreg / http / urllib /
          requests / httpx

原因不是「洁癖」，而是可测性：
    · 时间与睡眠必须由调用方注入（否则测试只能靠 sleep 等待）
    · 进程与网络必须由 adapter 提供（否则 domain 无法在 CI 里跑）
    · 日志是 I/O，由 adapters / presentation 承担

这个门禁是**非棘轮**的 —— 任何一处违规即失败，不设基线豁免。

═══════════════════════════════════════════════════════════════════
模块导览
═══════════════════════════════════════════════════════════════════

    service_state    服务四态语义（RUNNING/STOPPED/未知/未安装）
    readiness        就绪判定原语 wait_until（对标 kind 的 wait_until）
    port_contract    端口契约与占用判定（含 TIME_WAIT / 双栈处理）
    models           领域模型（Process/Service/HealthProbe/Dependency）
    config_schema    配置 schema 与类型归一化
    state_machine    模式互斥状态机（互杀防护，全项目最高风险逻辑）
    results          Port 契约的结果类型（OpResult/KillResult/HealthSample…）
    ports            依赖倒置的 Protocol 契约（仅定义，无实现）
"""

from __future__ import annotations

__all__ = [
    # 服务状态
    'ServiceStatus',
    'STATE_ABSENT',
    'STATE_UNKNOWN',
    'parse_sc_query_output',
    # 就绪判定
    'WaitPolicy',
    'WaitOutcome',
    'WaitStatus',
    'wait_until',
    'POLICY_SERVICE_STOPPED',
    'POLICY_SERVICE_RUNNING',
    'POLICY_REDIS_SERVICE',
    'POLICY_HTTP_BACKEND',
    'POLICY_HTTP_FRONTEND',
    'combine_all_cached',
    'is_running_predicate',
    'is_stopped_predicate',
    'is_not_conservatively_running',
    # 端口
    'PortFilter',
    'PortConfig',
    'PortOccupier',
    'parse_netstat_occupiers',
    'extract_port_pids',
    'parse_tasklist_name',
    'is_valid_port',
    'parse_port_from_address',
    # 领域模型
    'SVC_API',
    'SVC_ARQ',
    'NSSM_SERVICES',
    'DEFAULT_REDIS_SERVICES',
    'ServiceKind',
    'ProbeKind',
    'ProcessRole',
    'RunMode',
    'Service',
    'HealthProbe',
    'ProcessRef',
    'Dependency',
    'ServiceSnapshot',
    'build_probes',
    'probes_for_service',
    'detect_dependencies',
    # 配置
    'ConfigWarning',
    'NormalizedConfig',
    'normalize_config',
    'parse_config_text',
    'extract_ports',
    # 状态机
    'StopResult',
    'ServiceDisposition',
    'ServiceDecision',
    'PreflightPlan',
    'SwitchGuard',
    'GuardKind',
    'DevProcessSpec',
    'decide_service_action',
    'plan_production_stop',
    'build_stop_abort_reason',
    'needs_restart_guard',
    'guard_sequence',
    'build_protected_pids',
    'is_residual_prod_runner',
    'select_dev_processes_to_stop',
    # 结果类型（Port 契约的返回类型，必须定义在 domain 层）
    'OpResult',
    'KillResult',
    'HealthSample',
    'MetricsSample',
    'AuditOutcome',
    'AuditEntry',
    'AuditFilter',
    'ChainVerifyResult',
    'ServiceCmd',
    'Severity',
    'UndoToken',
    # Ports（仅 Protocol，无实现）
    'ClockPort',
    'ProcessPort',
    'ServicePort',
    'HealthPort',
    'MetricsPort',
    'StoragePort',
    'AuditPort',
    'NotifyPort',
    # 权限
    'Role',
    'Action',
    'DangerLevel',
    'PermissionCheck',
    'GRANTS',
    'DANGER_MATRIX',
    'ACTION_LABELS',
    'actions_for',
    'check',
    'danger_actions_at',
    'is_allowed',
    'required_role',
]


def __getattr__(name: str):
    """惰性再导出。

    用 __getattr__ 而非模块级 import，是为了让「导入 domain 包」本身
    不产生任何子模块加载副作用 —— 需要哪个取哪个。

    例：
        from server_manager_v8.domain import ServiceStatus
    """
    if name not in __all__:
        raise AttributeError(f'module {__name__!r} has no attribute {name!r}')

    from . import (  # noqa: PLC0415
        config_schema,
        models,
        permissions,
        port_contract,
        ports,
        readiness,
        results,
        service_state,
        state_machine,
    )

    for _module in (
        service_state,
        readiness,
        port_contract,
        models,
        config_schema,
        state_machine,
        results,
        ports,
        permissions,
    ):
        if hasattr(_module, name):
            return getattr(_module, name)

    raise AttributeError(f'module {__name__!r} has no attribute {name!r}')


def __dir__() -> list[str]:
    return sorted(__all__)
