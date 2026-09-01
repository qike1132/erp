"""L4 表现层 — HTML/CSS/JS 页面 + pywebview bridge。

零业务逻辑：只调用 Application 的 UseCase，只消费事件总线事件。
"""
from __future__ import annotations

from . import serializers, webview_host
from .bridge import Bridge

__all__ = ['Bridge', 'serializers', 'webview_host']
