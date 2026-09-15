"""权限矩阵与高危分级 —— 纯逻辑，零 I/O。

═══════════════════════════════════════════════════════════════════
来源：v8 方案 §2.5（堡垒机 4A / RBAC）
═══════════════════════════════════════════════════════════════════

本模块不是「逐行迁移」（旧实现没有权限体系），而是**按方案裁剪落地**：

    单机桌面工具 → 不引入账号体系 → 用「本地角色 + PIN 提权」模型

三级角色：
    只读 Viewer（默认）  —— 可读全部，可导出日志/确认告警
    运维 Operator        —— 可启停服务、清端口、切模式、静默告警、执行备份
    管理员 Admin         —— 全部

四级高危：
    L3 极高危 —— Admin 专属 + 输入操作名确认 + 强制填原因 + 审计
    L2 高危   —— Operator+ + 二次确认弹窗（列出影响面）+ 审计
    L1 中危   —— Operator+ + 轻确认（Toast 内撤销 5s）+ 审计
    L0 低危   —— 全角色 + 审计（仅流水）

═══════════════════════════════════════════════════════════════════
★ 设计核心：默认拒绝（deny by default）
═══════════════════════════════════════════════════════════════════

`is_allowed()` 查的是**显式授权表**。任何没被显式列出的「角色×操作」组合
一律拒绝。

这与「列出禁止项」的写法有本质区别：后者在新增一个操作时会**默认放行**
（因为没人记得去禁止表里加一条）。而本项目的操作集必然会增长
（v8 方案 §4 列了一堆待加功能），默认放行迟早出事。

★ 反向门禁：`scripts/check_domain_purity.py` 会检查 adapters 层
  不出现权限判定 —— 因为权限判定如果被复制到别处，默认拒绝就失效了。
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

# ═══════════════════════════════════════════════════════════════════
# 角色
# ═══════════════════════════════════════════════════════════════════


class Role(Enum):
    """本地角色（权限由低到高）。"""

    VIEWER = 'viewer'
    OPERATOR = 'operator'
    ADMIN = 'admin'

    @property
    def label(self) -> str:
        return {'viewer': '只读', 'operator': '运维', 'admin': '管理员'}[self.value]

    @property
    def level(self) -> int:
        """角色等级（用于比较「是否足够高」）。"""
        return {'viewer': 0, 'operator': 1, 'admin': 2}[self.value]

    def at_least(self, other: Role) -> bool:
        """当前角色是否不低于 `other`。"""
        return self.level >= other.level


# ═══════════════════════════════════════════════════════════════════
# 高危等级
# ═══════════════════════════════════════════════════════════════════


class DangerLevel(Enum):
    """操作高危等级（方案 §2.5 的管控矩阵）。"""

    L0 = 'L0'
    L1 = 'L1'
    L2 = 'L2'
    L3 = 'L3'

    @property
    def label(self) -> str:
        return {'L0': '低危', 'L1': '中危', 'L2': '高危', 'L3': '极高危'}[self.value]

    @property
    def requires_reason(self) -> bool:
        """是否强制填写变更原因（L3 要求，供审计追溯「为什么做这次变更」）。"""
        return self is DangerLevel.L3

    @property
    def requires_typed_confirmation(self) -> bool:
        """是否需要「输入操作名确认」（类 GitHub 删仓库，防误点）。"""
        return self is DangerLevel.L3

    @property
    def requires_modal_confirm(self) -> bool:
        """是否需要二次确认弹窗并列出影响面（L2 及以上）。"""
        return self in (DangerLevel.L2, DangerLevel.L3)

    @property
    def supports_undo(self) -> bool:
        """是否走「轻确认 + Toast 内撤销」（仅 L1）。

        L2/L3 不用撤销机制 —— 因为它们的副作用（停生产、删服务）
        无法通过一个 5 秒撤销完整回滚，给用户「可撤销」的错觉更危险。
        """
        return self is DangerLevel.L1


# ═══════════════════════════════════════════════════════════════════
# 操作
# ═══════════════════════════════════════════════════════════════════


class Action(Enum):
    """可执行的操作。

    ★ 值的命名约定：`<域>.<动作>`，便于按前缀批量分析（如统计所有 `log.*`）。
    """

    # ── 只读（L0）────────────────────────────────────────────────
    VIEW_ALL = 'view.all'
    REFRESH = 'view.refresh'
    EXPORT_LOGS = 'log.export'
    ACK_ALERT = 'alert.ack'

    # ── 中危（L1）────────────────────────────────────────────────
    RESTART_SERVICE = 'service.restart'
    CLEAR_LOGS = 'log.clear'
    SILENCE_ALERT = 'alert.silence'

    # ── 高危（L2）────────────────────────────────────────────────
    STOP_PROD_SERVICE = 'service.stop_prod'
    START_SERVICE = 'service.start'
    KILL_PORT = 'port.kill'
    SWITCH_MODE = 'mode.switch'
    EDIT_PORTS = 'config.edit_ports'
    EDIT_PATHS = 'config.edit_paths'
    RUN_BACKUP = 'backup.run'

    # ── 极高危（L3）──────────────────────────────────────────────
    UNINSTALL_SERVICE = 'service.uninstall'
    RESTORE_BACKUP = 'backup.restore'
    RESET_CONFIG = 'config.reset'
    MANAGE_ROLES = 'auth.manage_roles'

    @property
    def danger(self) -> DangerLevel:
        """该操作的高危等级（由下面的矩阵决定，默认拒绝的体现之一）。"""
        for level, actions in DANGER_MATRIX.items():
            if self in actions:
                return level
        # ★ 未登记的操作 → 按最高危处理（保守方向）
        #   这比「按最低危处理」安全：新增操作忘了登记等级，
        #   至少不会因为「以为是低危」而被随意执行。
        return DangerLevel.L3

    @property
    def label(self) -> str:
        return ACTION_LABELS.get(self, self.value)


#: 高危分级矩阵（方案 §2.5）
DANGER_MATRIX: dict[DangerLevel, frozenset[Action]] = {
    DangerLevel.L0: frozenset({
        Action.VIEW_ALL, Action.REFRESH, Action.EXPORT_LOGS, Action.ACK_ALERT,
    }),
    DangerLevel.L1: frozenset({
        Action.RESTART_SERVICE, Action.CLEAR_LOGS, Action.SILENCE_ALERT,
    }),
    DangerLevel.L2: frozenset({
        Action.STOP_PROD_SERVICE, Action.START_SERVICE, Action.KILL_PORT,
        Action.SWITCH_MODE, Action.EDIT_PORTS, Action.EDIT_PATHS,
        Action.RUN_BACKUP,
    }),
    DangerLevel.L3: frozenset({
        Action.UNINSTALL_SERVICE, Action.RESTORE_BACKUP, Action.RESET_CONFIG,
        Action.MANAGE_ROLES,
    }),
}

#: 操作的中文名（UI 展示与审计留痕共用，避免两处文案漂移）
ACTION_LABELS: dict[Action, str] = {
    Action.VIEW_ALL: '查看',
    Action.REFRESH: '刷新',
    Action.EXPORT_LOGS: '导出日志',
    Action.ACK_ALERT: '确认告警',
    Action.RESTART_SERVICE: '重启服务',
    Action.CLEAR_LOGS: '清空日志',
    Action.SILENCE_ALERT: '静默告警',
    Action.STOP_PROD_SERVICE: '停止生产服务',
    Action.START_SERVICE: '启动服务',
    Action.KILL_PORT: '清理端口占用',
    Action.SWITCH_MODE: '切换运行模式',
    Action.EDIT_PORTS: '修改端口',
    Action.EDIT_PATHS: '修改路径',
    Action.RUN_BACKUP: '执行备份',
    Action.UNINSTALL_SERVICE: '卸载服务',
    Action.RESTORE_BACKUP: '恢复备份',
    Action.RESET_CONFIG: '重置配置',
    Action.MANAGE_ROLES: '管理角色权限',
}


# ═══════════════════════════════════════════════════════════════════
# 授权矩阵（★ 显式授权 —— 默认拒绝）
# ═══════════════════════════════════════════════════════════════════


def _build_grants() -> dict[Role, frozenset[Action]]:
    """构建「角色 → 允许的操作」显式表。

    规则（方案 §2.5 的角色表）：
        Viewer    —— 全部 L0
        Operator  —— 全部 L0 + 全部 L1 + 全部 L2
        Admin     —— 全部（L0~L3）
    """
    l0 = DANGER_MATRIX[DangerLevel.L0]
    l1 = DANGER_MATRIX[DangerLevel.L1]
    l2 = DANGER_MATRIX[DangerLevel.L2]
    l3 = DANGER_MATRIX[DangerLevel.L3]
    return {
        Role.VIEWER: frozenset(l0),
        Role.OPERATOR: frozenset(l0 | l1 | l2),
        Role.ADMIN: frozenset(l0 | l1 | l2 | l3),
    }


GRANTS: dict[Role, frozenset[Action]] = _build_grants()


def is_allowed(role: Role, action: Action) -> bool:
    """角色是否有权执行该操作。

    ★ **默认拒绝**：不在显式授权表中的组合一律 False。
      新增 `Action` 却忘了加进 `DANGER_MATRIX` 时，
      它会被 `Action.danger` 判为 L3，且 `GRANTS` 里所有角色都查不到它
      → 只有 Admin 也不行，必须显式登记才可用。
      这是有意的「fail-closed」：宁可新功能暂时不可用，也不能默认放开。
    """
    return action in GRANTS.get(role, frozenset())


def required_role(action: Action) -> Role:
    """执行该操作所需的**最低**角色。"""
    for role in (Role.VIEWER, Role.OPERATOR, Role.ADMIN):
        if is_allowed(role, action):
            return role
    return Role.ADMIN  # 没有任何角色可用 → 报最高，便于排障时一眼看出异常


@dataclass(frozen=True)
class PermissionCheck:
    """一次权限检查的结果。

    ★ 不返回裸 bool 的理由（同 `OpResult`）：被拒时调用方需要知道
      「需要什么角色」，才能给出有用的提示（「需要管理员权限」而非「操作失败」），
      审计也需要记录这个信息。
    """

    allowed: bool
    role: Role
    action: Action
    reason: str = ''

    def __post_init__(self) -> None:
        if not self.allowed and not self.reason:
            raise ValueError('权限拒绝必须说明 reason')

    @property
    def danger(self) -> DangerLevel:
        return self.action.danger

    @property
    def message(self) -> str:
        """给用户看的一句话。"""
        if self.allowed:
            return f'允许 {self.action.label}'
        need = required_role(self.action)
        return (f'权限不足：{self.action.label} 需要「{need.label}」权限，'
                f'当前「{self.role.label}」')


def check(role: Role, action: Action) -> PermissionCheck:
    """权限检查（应用层 guard 的唯一入口）。"""
    if is_allowed(role, action):
        return PermissionCheck(True, role, action)
    need = required_role(action)
    return PermissionCheck(
        False, role, action,
        f'需要 {need.value} 权限（{need.label}）',
    )


def actions_for(role: Role) -> tuple[Action, ...]:
    """某角色可执行的全部操作（按枚举顺序，便于 UI 渲染权限说明页）。"""
    return tuple(a for a in Action if is_allowed(role, a))


def danger_actions_at(level: DangerLevel) -> tuple[Action, ...]:
    """某高危等级的全部操作。"""
    return tuple(a for a in Action if a.danger is level)


__all__ = [
    'ACTION_LABELS',
    'DANGER_MATRIX',
    'GRANTS',
    'Action',
    'DangerLevel',
    'PermissionCheck',
    'Role',
    'actions_for',
    'check',
    'danger_actions_at',
    'is_allowed',
    'required_role',
]
