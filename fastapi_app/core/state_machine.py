"""审批工作流状态机
集中管理所有审批状态的合法转换，作为系统层审批规则的单一真相源。
"""
import logging

logger = logging.getLogger(__name__)


class ApprovalState:
    PENDING = 'pending'
    APPROVED = 'approved'
    REJECTED = 'rejected'
    CANCELLED = 'cancelled'


class ApprovalAction:
    SUBMIT = 'submit'
    APPROVE = 'approve'
    REJECT = 'reject'
    CANCEL = 'cancel'


class ApprovalOperation:
    """审批**操作**名（与 ApprovalAction 区分）。

    ⚠️ EDIT / DELETE 目前是**死代码**：全仓无引用，且不在下方 TRANSITIONS 的转移表里，
    因此 `can_transition(status, ApprovalOperation.EDIT)` 恒为 False。当前无调用点故无 bug，
    但将来若照这两个常量驱动"可编辑/可删除"校验，会**静默全部失败**。
    要用请先把它们纳入转移表。
    """

    EDIT = 'edit'
    DELETE = 'delete'


# MECE 状态转移表：列出所有合法转换
TRANSITIONS: dict[str, dict[str, str]] = {
    # 新建/重新提交
    'init': {ApprovalAction.SUBMIT: ApprovalState.PENDING},
    'cancelled': {ApprovalAction.SUBMIT: ApprovalState.PENDING},
    'rejected': {ApprovalAction.SUBMIT: ApprovalState.PENDING},
    # 待审批 -> 通过/拒绝/取消
    ApprovalState.PENDING: {
        ApprovalAction.APPROVE: ApprovalState.APPROVED,
        ApprovalAction.REJECT: ApprovalState.REJECTED,
        ApprovalAction.CANCEL: ApprovalState.CANCELLED,
    },
}

# 终态集合（不能再转换）
TERMINAL_STATES = frozenset({ApprovalState.APPROVED})


def get_allowed_actions(current_status: str | None) -> list[str]:
    """获取当前状态允许的操作列表"""
    state = current_status or 'init'
    return list(TRANSITIONS.get(state, {}).keys())


def can_transition(current_status: str | None, action: str) -> bool:
    """检查是否可以执行指定的状态转换"""
    state = current_status or 'init'
    return action in TRANSITIONS.get(state, {})


def transition(current_status: str | None, action: str) -> str:
    """执行状态转换并返回新状态，非法转换抛出 ValueError"""
    state = current_status or 'init'
    allowed = TRANSITIONS.get(state, {})
    if action not in allowed:
        allowed_actions = list(allowed.keys()) if allowed else ['无可用操作']
        raise ValueError(
            f"非法审批状态转换: "
            f"当前状态='{current_status}' -> 操作='{action}'。"
            f"允许的操作: {allowed_actions}"
        )
    new_state = allowed[action]
    logger.info("审批状态转换: '%s' --%s--> '%s'", current_status, action, new_state)
    return new_state


def is_terminal(status: str) -> bool:
    """检查是否为终态"""
    return status in TERMINAL_STATES


# ==================== 通用状态机引擎（批次1，2026-08-22） ====================
# 审批域（上方 TRANSITIONS + 模块级函数）保持原 API 不变；
# 新领域通过 StateMachine 注册使用，避免状态字面量散落各服务。


class StateMachine:
    """通用状态机：转移表 + 终态集合，非法转移抛 ValueError。

    transition 记录 DEBUG 日志（批处理确认场景避免 INFO 刷屏）。
    """

    def __init__(self, name: str, transitions: dict[str, dict[str, str]],
                 terminal_states: frozenset[str] = frozenset()):
        self.name = name
        self.transitions = transitions
        self.terminal_states = frozenset(terminal_states)

    def get_allowed_actions(self, current_status: str | None) -> list[str]:
        state = current_status or 'init'
        return list(self.transitions.get(state, {}).keys())

    def can_transition(self, current_status: str | None, action: str) -> bool:
        state = current_status or 'init'
        return action in self.transitions.get(state, {})

    def transition(self, current_status: str | None, action: str) -> str:
        state = current_status or 'init'
        allowed = self.transitions.get(state, {})
        if action not in allowed:
            allowed_actions = list(allowed.keys()) if allowed else ['无可用操作']
            raise ValueError(
                f"非法[{self.name}]状态转换: "
                f"当前状态='{current_status}' -> 操作='{action}'。"
                f"允许的操作: {allowed_actions}"
            )
        new_state = allowed[action]
        logger.debug("[%s]状态转换: '%s' --%s--> '%s'", self.name, current_status, action, new_state)
        return new_state

    def is_terminal(self, status: str) -> bool:
        return status in self.terminal_states


# ==================== 暂存区（staging）状态机 ====================
# 原订单/备货/出货三份 near-identical 状态赋值（pending/approved/rejected）
# 收敛为单一转移表；查询过滤与删除沿用 StagingStatus 常量。

class StagingStatus:
    """暂存区记录状态（订单/备货/出货三域共用）"""
    PENDING = 'pending'
    APPROVED = 'approved'
    REJECTED = 'rejected'


class StagingAction:
    APPROVE = 'approve'
    REJECT = 'reject'


STAGING_TRANSITIONS: dict[str, dict[str, str]] = {
    StagingStatus.PENDING: {
        StagingAction.APPROVE: StagingStatus.APPROVED,
        StagingAction.REJECT: StagingStatus.REJECTED,
    },
}

staging_machine = StateMachine(
    'staging', STAGING_TRANSITIONS,
    terminal_states=frozenset({StagingStatus.APPROVED, StagingStatus.REJECTED}),
)
