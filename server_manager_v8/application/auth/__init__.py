"""auth 包 —— 角色会话与权限守卫。"""

from __future__ import annotations

__all__ = [
    'ConfirmKind',
    'ConfirmationToken',
    'DEFAULT_ELEVATE_TTL_S',
    'GuardError',
    'Session',
    'SessionState',
    'check_permission',
    'require',
]


def __getattr__(name: str):
    if name not in __all__:
        raise AttributeError(f'module {__name__!r} has no attribute {name!r}')
    from . import guard, session  # noqa: PLC0415

    for module in (session, guard):
        if hasattr(module, name):
            return getattr(module, name)
    raise AttributeError(f'module {__name__!r} has no attribute {name!r}')
