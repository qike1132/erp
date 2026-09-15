"""角色会话 —— JIT 提权 + 30 分钟滑动过期。

═══════════════════════════════════════════════════════════════════
JIT（Just-In-Time）提权的桌面化裁剪（v8 方案 §2.5）
═══════════════════════════════════════════════════════════════════

大厂的 JIT 是「需要时申请临时高权限，用完自动回收」。
本项目的裁剪版：

    默认角色 = Viewer（只读）
    用户输入本地 PIN 提权到 Operator / Admin
    提权有效期 30 分钟，**滑动过期**（每次操作刷新）
    UI 顶栏显示剩余时间 + 「立即降权」按钮

**滑动过期**是关键设计：如果每次操作都刷新有效期，那么
「用户持续在操作」期间权限不会掉 —— 这符合「活跃会话才需要权限」的直觉。
反之固定过期会让长时间值班的运维在操作到一半时突然掉权限。

═══════════════════════════════════════════════════════════════════
★ 安全要点：降权必须是**立即生效**的
═══════════════════════════════════════════════════════════════════

`demote()` 与 `expire()` 的区别：
    · `demote()`  —— 用户主动点「立即降权」，立刻回到 Viewer
    · `expire()`  —— 超时自动回收（由 `current_role()` 惰性检测）

两者都必须**不可逆地清掉提权状态**。若只清 role 而保留 `_expires_at`，
下一次 `touch()` 会把权限又「续上」—— 用户点了降权却还有权限，这是权限漏洞。

所以本类用**单一状态源**：`_role` 与 `_expires_at` 同生共死，
任何降权路径都调同一个 `_clear()`。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from ...domain.permissions import Action, PermissionCheck, Role, check
from ..events import AuthChanged

#: 提权有效期（秒）—— 方案 §2.5 规定 30 分钟
DEFAULT_ELEVATE_TTL_S = 1800.0


@dataclass
class SessionState:
    """会话快照（供 UI 显示）。"""

    role: Role
    expires_at: float | None = None
    remaining_s: float = 0.0
    elevated: bool = False


class Session:
    """角色会话。

    ★ 时间从注入的 clock 取 —— 于是「30 分钟过期」可以在毫秒内测完，
      不必真的等半小时（这与 domain 层「时间必须注入」的原则一致）。
    """

    def __init__(
        self,
        *,
        clock: Any,
        default_role: Role = Role.VIEWER,
        elevate_ttl_s: float = DEFAULT_ELEVATE_TTL_S,
        emit: Callable[[Any], Any] | None = None,
    ) -> None:
        if elevate_ttl_s <= 0:
            raise ValueError(f'提权有效期必须为正数，得到 {elevate_ttl_s!r}')
        self._clock = clock
        self._default_role = default_role
        self._ttl = float(elevate_ttl_s)
        self._role = default_role
        self._expires_at: float | None = None
        self._emit = emit or (lambda event: None)

    # ── 查询 ──────────────────────────────────────────────────────

    @property
    def role(self) -> Role:
        """当前**有效**角色（惰性检测过期）。

        ★ 惰性过期而不是依赖后台定时器：定时器可能因为线程崩溃/事件循环
          阻塞而没跑，那样权限会一直挂着。惰性检测在**每次读取时**判断，
          没有「忘了回收」的窗口。
        """
        self._expire_if_needed()
        return self._role

    @property
    def expires_at(self) -> float | None:
        self._expire_if_needed()
        return self._expires_at

    @property
    def is_elevated(self) -> bool:
        """是否处于提权状态（不是默认角色）。"""
        return self.role is not self._default_role

    @property
    def remaining_s(self) -> float:
        """提权剩余秒数（未提权返回 0）。"""
        self._expire_if_needed()
        if self._expires_at is None:
            return 0.0
        return max(0.0, self._expires_at - self._clock.monotonic())

    def state(self) -> SessionState:
        """取会话快照（UI 轮询用）。"""
        role = self.role
        return SessionState(
            role=role,
            expires_at=self._expires_at,
            remaining_s=self.remaining_s,
            elevated=role is not self._default_role,
        )

    # ── 提权 / 降权 ───────────────────────────────────────────────

    def elevate(self, role: Role) -> SessionState:
        """提权到指定角色（PIN 校验由调用方完成，本类**不做认证**）。"""
        self._role = role
        self._expires_at = self._clock.monotonic() + self._ttl
        self._notify('提权', f'已提权到「{role.label}」，有效期 {int(self._ttl / 60)} 分钟')
        return self.state()

    def demote(self) -> SessionState:
        """立即降权回默认角色（用户主动点「立即降权」）。"""
        was = self._role
        self._clear()
        if was is not self._default_role:
            self._notify('降权', f'已从「{was.label}」降回「{self._default_role.label}」')
        return self.state()

    def touch(self) -> SessionState:
        """滑动续期（每次成功操作后调用）。

        ★ 只有处于提权状态才续期 —— 默认角色没有有效期概念。
          这也防止「降权后一次 touch 又把权限续回来」。
        """
        if self._expires_at is not None:
            self._expires_at = self._clock.monotonic() + self._ttl
        return self.state()

    def _clear(self) -> None:
        """统一的降权路径（★ 单一状态源，杜绝「清了角色没清过期时间」）。"""
        self._role = self._default_role
        self._expires_at = None

    def _expire_if_needed(self) -> None:
        """超时则自动回收。"""
        if self._expires_at is None:
            return
        if self._clock.monotonic() >= self._expires_at:
            was = self._role
            self._clear()
            self._notify('超时', f'「{was.label}」权限已超时自动回收')

    # ── 权限检查 ──────────────────────────────────────────────────

    def check(self, action: Action) -> PermissionCheck:
        """检查当前角色能否执行该操作。"""
        return check(self.role, action)

    def can(self, action: Action) -> bool:
        return self.check(action).allowed

    def _notify(self, kind: str, detail: str) -> None:
        """发权限变化事件（失败不影响权限操作本身）。"""
        try:
            self._emit(AuthChanged(
                ts=self._clock.monotonic(),
                role=self._role.value,
                expires_at=self._expires_at,
                detail=f'{kind}: {detail}',
            ))
        except BaseException:  # noqa: BLE001
            pass


__all__ = [
    'DEFAULT_ELEVATE_TTL_S',
    'Session',
    'SessionState',
]
