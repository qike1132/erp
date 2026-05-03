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
