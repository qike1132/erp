"""超管降级守卫的回归（2026-11-16 上线前审计 A-24）。

拦哪种错：`update_user` 曾经可以把**最后一个超管**（甚至操作者自己）的 `is_super`
写成 False，而后端 `toggle_user_status` / `delete_user` 都禁止动超管——三条路径口径不一致。
一旦触发，系统在 UI 里再无超管，只能改库恢复。

变异检查：删掉 `update_user` 里对 `super_admin_demotion_error` 的调用后，本文件的用例
仍会绿（它们测的是纯函数）；端到端那条守卫由 test_user_super_admin_guard_api.py 覆盖。
"""
from __future__ import annotations

import pytest

from fastapi_app.services.user_service import super_admin_demotion_error


def test_last_super_admin_cannot_be_demoted():
    """系统只剩一个超管时，禁止把它降级（否则无人能再进用户管理）。"""
    err = super_admin_demotion_error(
        target_user_id=7,
        target_is_super=True,
        new_is_super=False,
        acting_user_id=1,
        super_count=1,
    )
    assert err == '系统必须保留至少一个超级管理员；请先把另一位用户设为超管'


def test_super_admin_can_be_demoted_when_another_remains():
    """还有别的超管时可以降级，别把正常管理动作堵死。"""
    assert super_admin_demotion_error(
        target_user_id=7,
        target_is_super=True,
        new_is_super=False,
        acting_user_id=1,
        super_count=2,
    ) is None


def test_cannot_demote_self_even_with_another_super():
    """操作者不能降级自己：先降自己再降别人是绕开「最后一个超管」守卫的常见走法。"""
    err = super_admin_demotion_error(
        target_user_id=1,
        target_is_super=True,
        new_is_super=False,
        acting_user_id=1,
        super_count=5,
    )
    assert err == '不能修改自己的超级管理员标志；请让另一位超管操作'


@pytest.mark.parametrize(
    ('target_is_super', 'new_is_super', 'super_count'),
    [
        (False, True, 1),   # 提升为超管：不拦
        (True, True, 1),    # 保持超管：不拦
        (False, False, 1),  # 普通用户保持普通：不拦
        (True, None, 1),    # is_super 不修改（None）：不拦
    ],
)
def test_non_demotion_paths_are_not_blocked(target_is_super, new_is_super, super_count):
    assert super_admin_demotion_error(
        target_user_id=7,
        target_is_super=target_is_super,
        new_is_super=new_is_super,
        acting_user_id=1,
        super_count=super_count,
    ) is None


def test_acting_user_unknown_still_protected_by_last_super_rule():
    """外部调用（脚本/后台任务）不传 acting_user_id 时，仍靠「最后一个超管」兜底。"""
    err = super_admin_demotion_error(
        target_user_id=7,
        target_is_super=True,
        new_is_super=False,
        acting_user_id=None,
        super_count=1,
    )
    assert err == '系统必须保留至少一个超级管理员；请先把另一位用户设为超管'
