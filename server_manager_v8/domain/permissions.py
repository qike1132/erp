"""权限与高危操作管控 — RBAC 三级角色 + 高危四级矩阵 + JIT 提权会话。

堡垒机 4A 裁剪为单机桌面版（详见 v8 方案 §2.5）：

    - 认证：本地 PIN（PBKDF2 哈希存配置），PIN 校验由 Adapter 层负责，
      Domain 只管「会话里当前是谁、能做什么、还剩多久过期」
    - 授权：默认拒绝，按角色显式授权；读写分离（只读诊断 ≠ 变更）
    - JIT：需要时提权，30 分钟滑动过期，UI 顶栏展示剩余时间与「立即降权」
    - 审计：所有操作（含 L0 查看类）都产生审计流水，由 Application 层落盘

交互硬规则：**无权限按钮禁用而非隐藏**（隐藏会被误解为功能缺失），
点击禁用按钮直接唤起提权，提权成功后自动继续原操作 ——
因此 authorize() 返回 elevate_to（建议提权到的最低角色），供 UI 弹提权框。
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from .models import DangerLevel, OpResult, Role

__all__ = [
    'CONTROL_BY_DANGER',
    'Action',
    'AuthPolicy',
    'Authorization',
    'Session',
]


class Action(StrEnum):
    """全部可授权操作。审计流水的 action 字段即此枚举值。"""

    # L0 低危（全角色）
    VIEW = 'view'
    EXPORT_LOGS = 'export_logs'
    ACK_ALERT = 'ack_alert'
    # L1 中危（Operator+）
    START_SERVICE = 'start_service'
    RESTART_SERVICE = 'restart_service'
    SILENCE_ALERT = 'silence_alert'
    RUN_BACKUP = 'run_backup'
    CLEAR_LOGS = 'clear_logs'
    # L2 高危（Operator+，二次确认列影响面）
    STOP_SERVICE = 'stop_service'
    KILL_PORT = 'kill_port'
    SWITCH_MODE = 'switch_mode'
    EDIT_CONFIG = 'edit_config'
    # L3 极高危（Admin 专属，键入操作名 + 变更原因）
    INSTALL_SERVICES = 'install_services'
    UNINSTALL_SERVICES = 'uninstall_services'
    RESTORE_BACKUP = 'restore_backup'
    RESET_CONFIG = 'reset_config'
    EDIT_PERMISSIONS = 'edit_permissions'


# ===================== 授权矩阵（角色 -> 操作集） =====================

_VIEWER: frozenset[Action] = frozenset({
    Action.VIEW, Action.EXPORT_LOGS, Action.ACK_ALERT,
})
_OPERATOR: frozenset[Action] = _VIEWER | frozenset({
    Action.START_SERVICE, Action.RESTART_SERVICE, Action.SILENCE_ALERT,
    Action.RUN_BACKUP, Action.CLEAR_LOGS,
    Action.STOP_SERVICE, Action.KILL_PORT, Action.SWITCH_MODE,
})
_ADMIN: frozenset[Action] = frozenset(Action)  # 全量

PERMISSIONS: dict[Role, frozenset[Action]] = {
    Role.VIEWER: _VIEWER,
    Role.OPERATOR: _OPERATOR,
    Role.ADMIN: _ADMIN,
}

# ===================== 高危分级与管控方式 =====================

DANGER: dict[Action, DangerLevel] = {
    Action.VIEW: DangerLevel.L0,
    Action.EXPORT_LOGS: DangerLevel.L0,
    Action.ACK_ALERT: DangerLevel.L0,
    Action.START_SERVICE: DangerLevel.L1,
    Action.RESTART_SERVICE: DangerLevel.L1,
    Action.SILENCE_ALERT: DangerLevel.L1,
    Action.RUN_BACKUP: DangerLevel.L1,
    Action.CLEAR_LOGS: DangerLevel.L1,
    Action.STOP_SERVICE: DangerLevel.L2,
    Action.KILL_PORT: DangerLevel.L2,
    Action.SWITCH_MODE: DangerLevel.L2,
    Action.EDIT_CONFIG: DangerLevel.L2,
    Action.INSTALL_SERVICES: DangerLevel.L3,
    Action.UNINSTALL_SERVICES: DangerLevel.L3,
    Action.RESTORE_BACKUP: DangerLevel.L3,
    Action.RESET_CONFIG: DangerLevel.L3,
    Action.EDIT_PERMISSIONS: DangerLevel.L3,
}

# 每级对应的确认交互（v8 方案 §5.3）：
#   L0 直接执行 / L1 Toast 内 5s 撤销 / L2 二次确认弹窗（列影响面） /
#   L3 键入操作名 + 强制变更原因
CONTROL_BY_DANGER: dict[DangerLevel, str] = {
    DangerLevel.L0: 'none',
    DangerLevel.L1: 'toast_undo',
    DangerLevel.L2: 'confirm_impact',
    DangerLevel.L3: 'type_name_reason',
}

# 每个操作所需的最低角色（低角色优先：VIEWER < OPERATOR < ADMIN，先到先得）
_MIN_ROLE_FOR_ACTION: dict[Action, Role] = {}
for _role in (Role.VIEWER, Role.OPERATOR, Role.ADMIN):
    for _action in PERMISSIONS[_role]:
        _MIN_ROLE_FOR_ACTION.setdefault(_action, _role)
del _role, _action


@dataclass(frozen=True)
class Session:
    """本地会话。PIN 校验通过后由 Application 层创建/更新。"""

    base_role: Role = Role.VIEWER
    elevated: Role | None = None  # JIT 提权到的角色；None = 未提权
    expires_at: float = 0.0  # 提权过期时间戳；未提权时无意义

    @property
    def elevated_active(self) -> bool:
        return self.elevated is not None


@dataclass(frozen=True)
class Authorization:
    """授权裁决。UI 依据它决定：置灰 / 可点 / 需要哪级确认 / 弹提权框。"""

    allowed: bool
    action: Action
    role: Role  # 实际生效的角色
    danger: DangerLevel
    control: str  # none / toast_undo / confirm_impact / type_name_reason
    reason: str = ''
    elevate_to: Role | None = None  # 无权限时建议提权到的最低角色（None = 提权也无济于事）


class AuthPolicy:
    """纯逻辑授权策略。默认提权 TTL 30 分钟（滑动过期）。"""

    ELEVATE_TTL_S = 1800.0

    def effective_role(self, session: Session, now: float) -> Role:
        """当前生效角色。提权过期自动回落 base_role（JIT 自动降权）。"""
        if session.elevated is not None and now < session.expires_at:
            return session.elevated
        return session.base_role

    def elevate(
        self, session: Session, to: Role, now: float, ttl_s: float = ELEVATE_TTL_S
    ) -> tuple[OpResult, Session]:
        """提权。返回 (结果, 新会话)；失败时新会话为原会话不变。

        目标必须高于 base_role；对已提权会话重复提权 = 刷新过期时间（滑动）。
        """
        if _role_rank(to) <= _role_rank(session.base_role):
            return OpResult.failure('目标角色不高于基础角色，无需提权'), session
        return (
            OpResult.success(detail=f'elevate→{to.value}, expires_at={now + ttl_s:.0f}'),
            Session(base_role=session.base_role, elevated=to, expires_at=now + ttl_s),
        )

    def build_session(self, base_role: Role, to: Role | None, now: float, ttl_s: float = ELEVATE_TTL_S) -> Session:
        """构建会话。to 为 None 表示以 base_role 无提权运行。"""
        if to is not None and _role_rank(to) > _role_rank(base_role):
            return Session(base_role=base_role, elevated=to, expires_at=now + ttl_s)
        return Session(base_role=base_role)

    def touch(self, session: Session, now: float, ttl_s: float = ELEVATE_TTL_S) -> Session:
        """滑动续期：每次成功操作后延长提权过期时间。"""
        if not session.elevated_active:
            return session
        return Session(base_role=session.base_role, elevated=session.elevated, expires_at=now + ttl_s)

    def degrade(self, session: Session) -> Session:
        """立即降权（UI「立即降权」按钮）。"""
        return Session(base_role=session.base_role)

    def ttl_remaining(self, session: Session, now: float) -> float:
        """提权剩余秒数。未提权或已过期返回 0。"""
        if not session.elevated_active:
            return 0.0
        return max(0.0, session.expires_at - now)

    def authorize(self, session: Session, action: Action, now: float) -> Authorization:
        """授权裁决。无权限时给出 elevate_to 建议（禁用而非隐藏的交互依据）。"""
        role = self.effective_role(session, now)
        danger = DANGER[action]
        control = CONTROL_BY_DANGER[danger]
        if action in PERMISSIONS[role]:
            return Authorization(
                allowed=True, action=action, role=role,
                danger=danger, control=control,
            )
        target = _MIN_ROLE_FOR_ACTION.get(action)
        reason = (
            f'需要 {_MIN_ROLE_FOR_ACTION[action].value} 角色' if target
            else f'未知操作 {action.value}'
        )
        return Authorization(
            allowed=False, action=action, role=role,
            danger=danger, control=control,
            reason=reason, elevate_to=target,
        )

    def check_reason(self, danger: DangerLevel, reason: str) -> OpResult:
        """L3 操作的变更原因强校验（Application 层在执行前调用）。"""
        if danger is DangerLevel.L3 and not (reason or '').strip():
            return OpResult.failure('L3 极高危操作必须填写变更原因')
        return OpResult.success()


def _role_rank(role: Role) -> int:
    """角色等级序：viewer=0 < operator=1 < admin=2。"""
    return {Role.VIEWER: 0, Role.OPERATOR: 1, Role.ADMIN: 2}[role]
