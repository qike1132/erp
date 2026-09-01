"""通知适配器 — 实现 domain.ports.NotifyPort。

按 Severity.notify_channels 决定渠道：modal（系统弹窗）/ tray / sound / badge。
无外部依赖：modal 用 ctypes MessageBoxW；sound 用 ctypes MessageBeep；
tray 由托盘适配器负责（v8 方案中 tray_pystray 独立实现，此处占位降级为 stderr）。
UI 环境不可用时降级到 stderr 日志 —— 通知失败不抛异常（审计/主流程不受影响）。
"""

from __future__ import annotations

import sys

from server_manager_v8.domain import Severity

__all__ = ['WinNotifyAdapter']


class WinNotifyAdapter:
    """Windows 通知适配器。modal / sound 用 ctypes，其余渠道降级 stderr。"""

    def __init__(self, app_title: str = 'ERP 服务器管理器') -> None:
        self.app_title = app_title

    def notify(self, severity: object, title: str, body: str = '') -> None:
        """按告警等级决定渠道（Severity.notify_channels 驱动）。"""
        level = severity if isinstance(severity, Severity) else Severity.P2
        channels = level.notify_channels
        try:
            if 'modal' in channels:
                self._modal(title, body)
            if 'sound' in channels:
                self._beep()
        except Exception:
            self._log(f'通知发送失败（{title}）: ')
        if not channels:
            self._log(f'[{level.value}] {title} {body}')

    # ---- 内部 ----

    def _modal(self, title: str, body: str) -> None:
        import ctypes

        ctypes.windll.user32.MessageBoxW(0, body or title, f'{self.app_title} · {title}', 0x10)

    @staticmethod
    def _beep() -> None:
        import ctypes

        ctypes.windll.user32.MessageBeep(0xFFFFFFFF)  # MB_ICONERROR

    @staticmethod
    def _log(line: str) -> None:
        try:
            sys.stderr.write(line + '\n')
        except OSError:  # pragma: no cover - stderr 关闭等极端情况
            return
