"""状态机引擎与暂存区（staging）转移表

审批工作流状态机已随审批系统下线移除（2026-11-28）；本模块保留通用
StateMachine 引擎（批次1，2026-08-22）与 staging 转移表。
"""
import logging

logger = logging.getLogger(__name__)


# ==================== 通用状态机引擎（批次1，2026-08-22） ====================
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
        """执行状态转换并返回新状态，非法转换抛 ValueError"""
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
        logger.debug("[%s]状态转换: '%s' --%s--> '%s'", current_status, action, new_state)
        return new_state

    def is_terminal(self, status: str) -> bool:
        """检查是否为终态"""
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
