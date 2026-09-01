"""运行模式状态机 — DEV 与 PROD 互斥，切换期持锁。

把 v6 散落在三处的互斥逻辑内聚为一个可单测的纯逻辑模块：
    - ``ServerManagerApp._mode`` 字符串散落赋值（'none'/'dual_dev'/'starting'/'restarting'）
    - ``_ensure_production_stopped`` / ``_ensure_development_stopped`` 的先停对侧
    - ``ActionLock`` 的幂等锁（拒绝并发切换）

状态图（不变式：DEV ⊕ PROD = true，任意时刻至多一个在运行）::

        ┌───────────────── IDLE ─────────────────┐
        │                   ▲                    │
   start_dev              stop_all            start_prod
        ▼                   │                    ▼
   ┌─ DEV ─┐            SWITCHING           ┌─ PROD ─┐
   │       │◄──── switch_to（先停对侧）────►│        │
   └───────┘                                └────────┘

SWITCHING 是受保护过渡态：期间拒绝一切新指令，只能 commit 或 rollback。
teardown / startup 用抽象 token 表达（'dev_procs' / 'prod_services' / 'none'），
由 Application 层展开为具体 Pipeline 步骤 —— Domain 不感知进程与服务细节。
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from .models import OpResult, RunMode

__all__ = [
    'ModeAction',
    'ModeMachine',
    'ModeTransitionError',
    'Startup',
    'SwitchPlan',
    'Teardown',
]


class ModeAction(StrEnum):
    """用户可发起的模式动作。"""

    START_DEV = 'start_dev'
    START_PROD = 'start_prod'
    STOP_ALL = 'stop_all'


class Teardown(StrEnum):
    """切换前需要确保停止的部分。"""

    NONE = 'none'
    DEV_PROCS = 'dev_procs'  # 开发模式前后端子进程（不动 Redis）
    PROD_SERVICES = 'prod_services'  # NSSM 生产服务 + 残留 prod_runner


class Startup(StrEnum):
    """切换后需要启动的部分。"""

    NONE = 'none'
    DEV_PROCS = 'dev_procs'
    PROD_SERVICES = 'prod_services'


@dataclass(frozen=True)
class SwitchPlan:
    """一次合法切换的执行计划。Application 层据此编排 Pipeline。"""

    action: ModeAction
    target: RunMode  # commit 后到达的模式；STOP_ALL 的 target 是 IDLE
    teardown: Teardown
    startup: Startup
    from_mode: RunMode


class ModeTransitionError(Exception):
    """非法转移。msg 面向 UI 直接展示。"""


# 转移表：(当前模式, 动作) -> (teardown, startup)
_TRANSITIONS: dict[tuple[RunMode, ModeAction], tuple[Teardown, Startup]] = {
    (RunMode.IDLE, ModeAction.START_DEV): (Teardown.NONE, Startup.DEV_PROCS),
    (RunMode.IDLE, ModeAction.START_PROD): (Teardown.NONE, Startup.PROD_SERVICES),
    (RunMode.DEV, ModeAction.START_PROD): (Teardown.DEV_PROCS, Startup.PROD_SERVICES),
    (RunMode.PROD, ModeAction.START_DEV): (Teardown.PROD_SERVICES, Startup.DEV_PROCS),
    (RunMode.DEV, ModeAction.STOP_ALL): (Teardown.DEV_PROCS, Startup.NONE),
    (RunMode.PROD, ModeAction.STOP_ALL): (Teardown.PROD_SERVICES, Startup.NONE),
}


def _rejection(mode: RunMode, action: ModeAction) -> str:
    """生成拒绝原因（可直接展示给用户）。"""
    if action is ModeAction.START_DEV and mode is RunMode.DEV:
        return '开发模式已在运行'
    if action is ModeAction.START_PROD and mode is RunMode.PROD:
        return '生产模式已在运行'
    if action is ModeAction.STOP_ALL and mode is RunMode.IDLE:
        return '当前已停止，无需重复操作'
    return f'当前处于 {mode.value} 模式，不能执行 {action.value}'


class ModeMachine:
    """模式状态机。线程约束：所有方法须在单一编排线程调用（Application 层保证）。"""

    def __init__(self) -> None:
        self._mode = RunMode.IDLE
        self._switching_from: RunMode | None = None
        self._switching_target: RunMode | None = None
        self._plan: SwitchPlan | None = None

    # ---- 查询（CQS 读侧） ----

    @property
    def mode(self) -> RunMode:
        return self._mode

    @property
    def switching(self) -> bool:
        """是否处于切换过渡期。"""
        return self._mode is RunMode.SWITCHING

    @property
    def pending_plan(self) -> SwitchPlan | None:
        """SWITCHING 期间挂起的计划，供 UI 展示「正在执行什么」。"""
        return self._plan

    def can(self, action: ModeAction) -> OpResult:
        """只读判定，不改变状态。UI 据此禁用/启用按钮（禁用而非隐藏）。"""
        if self._mode is RunMode.SWITCHING:
            return OpResult.failure('切换进行中，请等待完成或中止')
        if (self._mode, action) not in _TRANSITIONS:
            return OpResult.failure(_rejection(self._mode, action))
        return OpResult.success()

    # ---- 命令（CQS 写侧） ----

    def begin(self, action: ModeAction) -> SwitchPlan:
        """发起切换：进入 SWITCHING 并返回执行计划。

        非法转移抛 ModeTransitionError —— 这是编程错误而非业务失败
        （业务失败走 can() 判定，UI 应先判定再置灰按钮）。
        """
        check = self.can(action)
        if not check.ok:
            raise ModeTransitionError(check.reason)
        teardown, startup = _TRANSITIONS[(self._mode, action)]
        target = RunMode.IDLE if action is ModeAction.STOP_ALL else (
            RunMode.DEV if action is ModeAction.START_DEV else RunMode.PROD
        )
        plan = SwitchPlan(
            action=action,
            target=target,
            teardown=teardown,
            startup=startup,
            from_mode=self._mode,
        )
        self._switching_from = self._mode
        self._switching_target = target
        self._plan = plan
        self._mode = RunMode.SWITCHING
        return plan

    def commit(self) -> RunMode:
        """切换成功：SWITCHING → 目标模式。"""
        self._ensure_switching('commit')
        target = self._switching_target
        if target is None:  # 防御式：_ensure_switching 已保证，此处兜底
            raise ModeTransitionError('切换计划丢失，无法提交')
        self._mode = target
        self._clear_switching()
        return target

    def rollback(self) -> RunMode:
        """切换中止/失败：SWITCHING → 回到出发模式。

        v6 对应场景：启动中途健康检查失败，回到切换前的模式
        （对侧已停止的不会自动恢复 —— 由调用方决定是否重新发起）。
        """
        self._ensure_switching('rollback')
        back = self._switching_from
        if back is None:  # 防御式：_ensure_switching 已保证，此处兜底
            raise ModeTransitionError('切换来源丢失，无法回滚')
        self._mode = back
        self._clear_switching()
        return back

    # ---- 内部 ----

    def _ensure_switching(self, op: str) -> None:
        if self._mode is not RunMode.SWITCHING:
            raise ModeTransitionError(f'{op} 只能在切换过渡期调用，当前为 {self._mode.value}')

    def _clear_switching(self) -> None:
        self._switching_from = None
        self._switching_target = None
        self._plan = None
