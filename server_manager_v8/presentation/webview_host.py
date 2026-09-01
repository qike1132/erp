"""pywebview 宿主 — 装壳启动 + 事件实时推送到页面。

职责（P5）：
    1. 创建窗口，把 Bridge 暴露为 JS API（window.pywebview.api.*）
    2. 订阅事件总线，把序列化事件推送进页面（window.__push）
    3. 不包含任何业务逻辑 —— 全部委托 Container/Bridge
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

__all__ = ['default_html_path', 'run_gui']

_DEFAULT_TITLE = 'ERP 服务器管理器 v8'


def default_html_path() -> str:
    """web/index.html 的绝对路径（打包时随资源目录）。"""
    return str(Path(__file__).resolve().parent / 'web' / 'index.html')


def run_gui(
    container,
    *,
    title: str = _DEFAULT_TITLE,
    html_path: str | None = None,
    width: int = 1440,
    height: int = 900,
    debug: bool = False,
) -> int:
    """启动 GUI（阻塞至窗口关闭）。container 为装配好的 Container。"""
    import webview

    from .bridge import Bridge

    bridge = Bridge(container)
    path = html_path or default_html_path()

    def on_event(event) -> None:
        """事件 → JS 推送（订阅者隔离由 EventBus 保证）。"""
        payload = bridge.event_payload(event)
        if payload is None:
            return
        for window in webview.windows:
            if window is None:
                continue
            try:
                window.evaluate_js(
                    f'window.__push({json.dumps(payload, ensure_ascii=False)})',
                )
            except Exception as exc:
                print(f'[v8-gui] 事件推送失败: {exc}', file=sys.stderr)

    webview.create_window(
        title, path, js_api=bridge,
        width=width, height=height, min_size=(1100, 700),
    )
    container.bus.subscribe(on_event)  # 订阅全部事件（类型过滤在 payload 层）
    webview.start(debug=debug)
    return 0
