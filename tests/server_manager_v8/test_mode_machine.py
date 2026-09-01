"""运行模式状态机测试：互斥不变式、SWITCHING 持锁、commit/rollback。"""
from __future__ import annotations

import pytest

from server_manager_v8.domain import (
    ModeAction,
    ModeMachine,
    ModeTransitionError,
    RunMode,
    Startup,
    Teardown,
)


class TestLegalTransitions:
    def test_idle_start_dev(self) -> None:
        m = ModeMachine()
        plan = m.begin(ModeAction.START_DEV)
        assert m.mode is RunMode.SWITCHING
        assert plan.teardown is Teardown.NONE and plan.startup is Startup.DEV_PROCS
        assert m.commit() is RunMode.DEV

    def test_idle_start_prod(self) -> None:
        m = ModeMachine()
        plan = m.begin(ModeAction.START_PROD)
        assert plan.startup is Startup.PROD_SERVICES
        m.commit()
        assert m.mode is RunMode.PROD

    def test_dev_to_prod_tears_down_dev(self) -> None:
        m = ModeMachine()
        m.begin(ModeAction.START_DEV)
        m.commit()
        plan = m.begin(ModeAction.START_PROD)
        assert plan.teardown is Teardown.DEV_PROCS  # 先停开发侧
        assert plan.from_mode is RunMode.DEV
        assert m.commit() is RunMode.PROD

    def test_prod_to_dev_tears_down_prod(self) -> None:
        m = ModeMachine()
        m.begin(ModeAction.START_PROD)
        m.commit()
        plan = m.begin(ModeAction.START_DEV)
        assert plan.teardown is Teardown.PROD_SERVICES
        m.commit()
        assert m.mode is RunMode.DEV

    @pytest.mark.parametrize('frm,action', [
        (RunMode.DEV, ModeAction.STOP_ALL),
        (RunMode.PROD, ModeAction.STOP_ALL),
    ])
    def test_stop_all_from_running(self, frm: RunMode, action: ModeAction) -> None:
        m = ModeMachine()
        m.begin(ModeAction.START_DEV if frm is RunMode.DEV else ModeAction.START_PROD)
        m.commit()
        assert m.begin(action).target is RunMode.IDLE
        assert m.commit() is RunMode.IDLE


class TestIllegalTransitions:
    def test_mutex_dev_blocks_start_dev(self) -> None:
        m = ModeMachine()
        m.begin(ModeAction.START_DEV)
        m.commit()
        check = m.can(ModeAction.START_DEV)
        assert not check.ok and '已在运行' in check.reason

    def test_mutex_prod_blocks_start_prod(self) -> None:
        m = ModeMachine()
        m.begin(ModeAction.START_PROD)
        m.commit()
        assert not m.can(ModeAction.START_PROD).ok

    def test_stop_all_from_idle_rejected(self) -> None:
        m = ModeMachine()
        assert not m.can(ModeAction.STOP_ALL).ok
        with pytest.raises(ModeTransitionError):
            m.begin(ModeAction.STOP_ALL)

    def test_switching_locks_all_actions(self) -> None:
        """SWITCHING 期间拒绝一切新指令（v6 ActionLock 语义）。"""
        m = ModeMachine()
        m.begin(ModeAction.START_DEV)
        for action in ModeAction:
            assert not m.can(action).ok, f'SWITCHING 期间 {action} 应被拒绝'
            with pytest.raises(ModeTransitionError):
                m.begin(action)

    def test_commit_only_during_switching(self) -> None:
        m = ModeMachine()
        with pytest.raises(ModeTransitionError):
            m.commit()
        with pytest.raises(ModeTransitionError):
            m.rollback()


class TestCommitRollback:
    def test_rollback_restores_previous(self) -> None:
        """启动中途失败回到出发模式（v6 健康检查失败场景）。"""
        m = ModeMachine()
        m.begin(ModeAction.START_DEV)
        m.commit()
        m.begin(ModeAction.START_PROD)
        assert m.rollback() is RunMode.DEV
        assert m.mode is RunMode.DEV

    def test_rollback_from_idle_start(self) -> None:
        m = ModeMachine()
        m.begin(ModeAction.START_PROD)
        assert m.rollback() is RunMode.IDLE

    def test_pending_plan_visible_and_cleared(self) -> None:
        m = ModeMachine()
        m.begin(ModeAction.START_DEV)
        assert m.pending_plan is not None
        m.commit()
        assert m.pending_plan is None
        assert not m.switching


class TestInvariant:
    def test_dev_and_prod_never_both_running(self) -> None:
        """随机转移序列下不变式始终成立：DEV 与 PROD 互斥。"""
        m = ModeMachine()
        actions = [ModeAction.START_DEV, ModeAction.STOP_ALL, ModeAction.START_PROD,
                   ModeAction.STOP_ALL, ModeAction.START_DEV, ModeAction.START_PROD]
        for action in actions:
            if m.switching:
                m.commit()
            if m.can(action).ok:
                m.begin(action)
                m.commit()
            running = [m.mode is RunMode.DEV, m.mode is RunMode.PROD]
            assert sum(running) <= 1
