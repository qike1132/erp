"""权限守卫包 — 会话持有与 @require 装饰器（见 guard.py）。"""
from __future__ import annotations

from .guard import AuthGuard, PermissionDeniedError, danger_of

__all__ = ['AuthGuard', 'PermissionDeniedError', 'danger_of']
