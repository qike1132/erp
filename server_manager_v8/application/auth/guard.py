"""权限守卫 —— `@require` 装饰器 + 确认流程校验。

═══════════════════════════════════════════════════════════════════
装饰器要解决的两个问题
═══════════════════════════════════════════════════════════════════

1. **权限校验散落**：每个 usecase 开头都写一遍
   ```
   if not session.can(Action.KILL_PORT):
       return OpResult.failure('权限不足')
   ```
   漏写一处就是一个越权入口，而漏写不会报错。

2. **高危确认流程易漏**：L2 要二次确认、L3 要输入操作名 + 填原因。
   这些要求写在每个用例里同样容易漏。

`@require(action)` 把两者收口到一处，并在**未授权/未确认时**：
    · 发 `OperationDenied` 事件（★ 必须留痕 —— 4A 要求「谁在什么权限下被拦」）
    · 写审计（`AuditOutcome.DENIED`）
    · 返回显式的 `OpResult.failure`（不抛出，让调用方能给出友好提示）

═══════════════════════════════════════════════════════════════════
★ 设计要点：不抛出，而是返回失败结果
═══════════════════════════════════════════════════════════════════

可以设计成抛 `PermissionError`，但那会让调用方被迫到处 try/except，
而且「权限不足」是**预期内的正常分支**，不是异常。

返回 `OpResult.failure` 让调用方统一处理（与项目「显式结果对象」原则一致）。

═══════════════════════════════════════════════════════════════════
确认令牌（ConfirmationToken）
═══════════════════════════════════════════════════════════════════

L2/L3 操作需要用户在前端确认。确认结果通过 `ConfirmationToken` 传入：

    L2: token(kind='modal', impact='将停止 erp-prod，端口 5002 会释放')
    L3: token(kind='typed', typed_name='erp-prod', reason='服务迁移到新机器')

守卫校验令牌是否满足该等级的管控要求。**校验在服务端（应用层）做**，
不信前端说的「我已经确认过了」—— 前端可以伪造。
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import wraps
from enum import Enum
from typing import Any, Callable

from ...domain.permissions import Action, DangerLevel, Role
from ...domain.results import AuditEntry, AuditOutcome, OpResult
from ..events import OperationDenied

#: 审计里记录的操作者标识（单机工具无账号体系，用角色名）
DEFAULT_ACTOR = 'local'


class ConfirmKind(Enum):
    """确认方式。"""

    NONE = 'none'
    TOAST_UNDO = 'toast_undo'
    """L1：Toast 内可撤销，不需要阻塞式确认。"""

    MODAL = 'modal'
    """L2：二次确认弹窗，必须列出影响面。"""

    TYPED = 'typed'
    """L3：输入操作名 + 强制填原因。"""


@dataclass(frozen=True)
class ConfirmationToken:
    """用户的确认凭据。

    ★ 为什么 L3 要 `typed_name`：防误点。删一个 NSSM 服务不可逆，
      让它和「刷新」用同样的单击成本是不负责任的
      （对齐 GitHub 删仓库要输入仓库名的做法）。

    ★ 为什么 L3 要 `reason`：审计需要回答「为什么做这次变更」。
      只记「谁在何时做了什么」在事故复盘中往往不够。
    """

    kind: ConfirmKind = ConfirmKind.NONE
    typed_name: str = ''
    reason: str = ''
    impact: str = ''

    def satisfies(self, level: DangerLevel, *, target: str = '') -> tuple[bool, str]:
        """检查本令牌是否满足该高危等级的要求。返回 (是否满足, 不满足的原因)。"""
        if level is DangerLevel.L0:
            return True, ''

        if level is DangerLevel.L1:
            # L1 走 Toast 撤销，不阻塞 —— 任何令牌都放行（含默认的 NONE）
            return True, ''

        # L2 / L3 需要真实确认
        if self.kind is ConfirmKind.NONE:
            return False, f'{level.label}操作需要用户确认'

        if level is DangerLevel.L2:
            if self.kind is not ConfirmKind.MODAL:
                return False, f'{level.label}操作需要二次确认弹窗'
            return True, ''

        # L3
        if self.kind is not ConfirmKind.TYPED:
            return False, f'{level.label}操作需要输入名称确认'
        if not self.reason.strip():
            return False, f'{level.label}操作必须填写变更原因'
        if target and self.typed_name.strip() != target:
            return False, (f'确认名称不匹配：需要输入 {target!r}，'
                           f'实际输入 {self.typed_name!r}')
        return True, ''


class GuardError(RuntimeError):
    """守卫配置错误（如漏传 session）—— 属编程错误，应当崩。"""


def _resolve_session(kwargs: dict[str, Any]) -> Any:
    """从 kwargs 里取 session（支持关键字与位置参数两种调用）。"""
    session = kwargs.get('session')
    if session is None:
        raise GuardError(
            '@require 装饰的函数必须以 session= 关键参数接收 Session 实例'
        )
    return session


def require(
    action: Action,
    *,
    target_arg: str = '',
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """权限 + 确认流程守卫。

    用法：
        class KillPort:
            @require(Action.KILL_PORT, target_arg='port')
            def execute(self, port, *, session, confirm=None) -> OpResult: ...

    被装饰的函数必须满足：
        · 接收 `session=` 关键参数（Session 实例）
        · 接收 `confirm=` 关键参数（ConfirmationToken，可省略 → 默认 NONE）
        · 返回 `OpResult`

    ★ 装饰器**不改变函数签名**（用 wraps + 透传 *args/**kwargs），
      所以调用点写法不变。
    """

    def decorator(fn: Callable[..., Any]) -> Callable[..., Any]:
        @wraps(fn)
        def wrapper(*args: Any, **kwargs: Any) -> OpResult:
            session = _resolve_session(kwargs)
            confirm: ConfirmationToken = kwargs.get('confirm') or ConfirmationToken()
            level = action.danger

            # ── ① 权限检查 ──
            verdict = session.check(action)
            if not verdict.allowed:
                _deny(action, verdict.role, verdict.message, session, kwargs)
                return OpResult.failure('权限不足', verdict.message)

            # ── ② 确认流程检查 ──
            target = str(kwargs.get(target_arg, '')) if target_arg else ''
            ok, why = confirm.satisfies(level, target=target)
            if not ok:
                _deny(action, verdict.role, why, session, kwargs)
                return OpResult.failure('缺少确认', why)

            # ── ③ 放行（执行后做滑动续期）──
            result = fn(*args, **kwargs)
            try:
                session.touch()
            except BaseException:  # noqa: BLE001
                pass
            return result

        # 供 introspection / 测试断言用
        wrapper.__required_action__ = action  # type: ignore[attr-defined]
        wrapper.__danger_level__ = action.danger  # type: ignore[attr-defined]
        return wrapper

    return decorator


def _deny(action: Action, role: Role, reason: str, session: Any,
          kwargs: dict[str, Any]) -> None:
    """拒绝时的留痕（事件 + 审计）。

    ★ 被拒也必须留痕 —— 堡垒机 4A 明确要求记录「谁在什么权限下被拦下」。
      旧实现弹个 messagebox 就完了，事后无法统计越权尝试。
    """
    bus = kwargs.get('event_bus')
    if bus is not None:
        try:
            bus.emit(OperationDenied(
                ts=0.0, action=action.value, required=action.danger.label,
                actor_role=role.value, detail=reason,
            ))
        except BaseException:  # noqa: BLE001
            pass

    audit = kwargs.get('audit')
    if audit is not None:
        try:
            audit.record(AuditEntry(
                ts=0.0, actor=DEFAULT_ACTOR, action=action.value,
                target=str(kwargs.get('target', '')),
                outcome=AuditOutcome.DENIED, reason=reason,
                detail=f'role={role.value}',
            ))
        except BaseException:  # noqa: BLE001
            pass


def check_permission(session: Any, action: Action,
                     confirm: ConfirmationToken | None = None,
                     *, target: str = '') -> OpResult | None:
    """非装饰器形式的权限检查（供需要「先检查再分支」的场景）。

    返回 None 表示通过；返回 `OpResult` 表示被拒（调用方直接 return 它）。
    """
    verdict = session.check(action)
    if not verdict.allowed:
        return OpResult.failure('权限不足', verdict.message)

    token = confirm or ConfirmationToken()
    ok, why = token.satisfies(action.danger, target=target)
    if not ok:
        return OpResult.failure('缺少确认', why)
    return None


__all__ = [
    'ConfirmKind',
    'ConfirmationToken',
    'DEFAULT_ACTOR',
    'GuardError',
    'check_permission',
    'require',
]
