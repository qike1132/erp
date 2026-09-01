"""权限守卫 — @require(action) 装饰器 + 会话持有（JIT 提权接线）。

用法：:

    guard = AuthGuard(AuthPolicy(), clock=time.time)
    # 设置当前会话（Application 启动时 / 提权成功后）
    guard.set_session(session)

    class StopServiceUseCase:
        @guard.require(Action.STOP_SERVICE)
        def run(self) -> OpResult:
            ...

交互硬规则（v8 方案 §5.3）：无权限按钮**禁用而非隐藏**，点击禁用按钮唤起提权、
提权成功后自动继续原操作 —— guard.control(action) 供 UI 查询（不执行），
guard.require 在执行入口裁决（含 L3 变更原因校验）。
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from functools import wraps

from server_manager_v8.domain import (
    DANGER,
    Action,
    Authorization,
    AuthPolicy,
    DangerLevel,
    OpResult,
    Role,
    Session,
)

__all__ = ['AuthGuard', 'PermissionDeniedError']


@dataclass(frozen=True)
class PermissionDeniedError(Exception):
    """授权被拒。elevate_to 供 UI 弹提权框（禁用而非隐藏）。"""

    action: Action
    reason: str
    elevate_to: Role | None = None


class AuthGuard:
    """当前会话持有 + 授权裁决入口。单进程内单实例（CLI/GUI 共享）。"""

    def __init__(self, policy: AuthPolicy, clock: Callable[[], float] = time.time) -> None:
        self._policy = policy
        self._clock = clock
        self._session = Session(base_role=Role.VIEWER)  # 安全默认：只读

    # ---- 会话管理 ----

    def set_session(self, session: Session) -> None:
        self._session = session

    def current(self) -> Session:
        return self._session

    @property
    def role(self) -> Role:
        return self._policy.effective_role(self._session, self._clock())

    def elevate(self, to: Role) -> OpResult:
        """提权（PIN 校验由调用方完成，此处仅更新会话）。"""
        result, session = self._policy.elevate(self._session, to, self._clock())
        if result.ok:
            self._session = session
        return result

    def degrade(self) -> None:
        self._session = self._policy.degrade(self._session)

    def touch(self) -> None:
        """每次成功操作后滑动续期。"""
        self._session = self._policy.touch(self._session, self._clock())

    def ttl_remaining(self) -> float:
        return self._policy.ttl_remaining(self._session, self._clock())

    # ---- 裁决 ----

    def control(self, action: Action) -> Authorization:
        """只读裁决（UI 据此置灰/确认交互），不执行。"""
        return self._policy.authorize(self._session, action, self._clock())

    def authorize(self, action: Action, reason: str = '') -> Authorization:
        """执行入口裁决：权限 + L3 变更原因强校验。拒绝抛 PermissionDeniedError。"""
        auth = self._policy.authorize(self._session, action, self._clock())
        if not auth.allowed:
            raise PermissionDeniedError(action=auth.action, reason=auth.reason, elevate_to=auth.elevate_to)
        check = self._policy.check_reason(auth.danger, reason)
        if not check.ok:
            raise PermissionDeniedError(action=auth.action, reason=check.reason, elevate_to=None)
        return auth

    def require(self, action: Action) -> Callable[[Callable[..., OpResult]], Callable[..., OpResult]]:
        """装饰 UseCase 执行方法：入口裁决权限（L3 原因由方法参数传入）。"""

        def decorator(fn: Callable[..., OpResult]) -> Callable[..., OpResult]:
            @wraps(fn)
            def wrapper(*args: object, **kwargs: object) -> OpResult:
                reason = kwargs.pop('reason', '') or ''
                try:
                    self.authorize(action, reason)
                except PermissionDeniedError as exc:
                    return OpResult.failure(f'权限不足: {exc.reason}')
                result = fn(*args, **kwargs)
                if result.ok:
                    self.touch()  # 成功操作滑动续期 JIT
                return result

            return wrapper

        return decorator


def danger_of(action: Action) -> DangerLevel:
    """供 UI 直接读取某操作的危险等级（不经授权）。"""
    return DANGER[action]
