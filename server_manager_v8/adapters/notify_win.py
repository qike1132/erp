"""Windows 通知适配器 —— 托盘气泡 / 声音 / 弹窗。

═══════════════════════════════════════════════════════════════════
★ 设计基调：通知是「尽力而为」，绝不能影响业务
═══════════════════════════════════════════════════════════════════

通知的失败场景极多且都不可控：
    · 用户关了系统通知（勿扰模式）
    · 气泡被系统静默丢弃（Windows 有「通知节流」，短时间内多条会丢）
    · 声音设备被占用 / 无音频设备
    · 在非 Windows 环境（CI）下根本没有这些东西

如果通知失败抛异常，就会**在业务操作成功之后**抛出 ——
用户看到「操作失败」，实际操作已经完成。这是比「没收到通知」严重得多的问题。

所以 `NotifyPort.notify()` 契约要求**永不抛出**，本实现严格遵守。

═══════════════════════════════════════════════════════════════════
降级链（从好到坏）
═══════════════════════════════════════════════════════════════════

    1. 注入的 notify_fn（生产环境由 pywebview / pystray 提供）
    2. Windows 原生 MessageBoxW（`ctypes`，能弹出来就弹）
    3. stderr 打印（最后兜底，保证「至少不是静默的」）

第 3 级的存在是关键 —— 在多级降级设计里，**最后一级绝不能是「什么都不做」**，
否则降级链的末端就是个静默黑洞。

═══════════════════════════════════════════════════════════════════
为什么 P0 通知要额外弹窗
═══════════════════════════════════════════════════════════════════

对齐 v8 方案 §2.4「Google SRE 告警分级」：P0/P1 是「该叫人起床」的级别。
托盘气泡会被忽略（它自己几秒后消失），所以对 `Severity.is_page` 的通知
强制升级为**模态弹窗**，必须有人点掉。

这个「升级」是有意的打扰 —— 告警工程里，该打扰时不打扰等于没有告警。
"""

from __future__ import annotations

import sys
from typing import Any, Callable

from ..domain.results import Severity

#: Windows MessageBox 图标常量
MB_ICON_ERROR = 0x10
MB_ICON_WARNING = 0x30
MB_ICON_INFORMATION = 0x40

#: MessageBox 按钮：确定
MB_OK = 0x0

#: MessageBox 置顶（保证不被其他窗口盖住 —— 告警被盖住等于没弹）
MB_TOPMOST = 0x40000


def _is_windows() -> bool:
    return sys.platform == 'win32'


def _level_icon(level: Severity) -> int:
    """告警级别 → MessageBox 图标。"""
    if level in (Severity.P0, Severity.P1):
        return MB_ICON_ERROR
    if level is Severity.P2:
        return MB_ICON_WARNING
    return MB_ICON_INFORMATION


class WinNotifier:
    """Windows 通知实现。

    实现 `domain.ports.NotifyPort`。

    `bubble_fn`：注入的托盘气泡函数（签名 `(title, body) -> None`）。
        生产环境由 pystray / pywebview 提供；测试注入 fake。
        未提供时自动降级到 MessageBox。
    `fallback_to_messagebox`：是否允许降级到 MessageBox。
        在自动化/测试环境应传 False，避免弹窗卡住进程。
    `on_error`：失败回调（默认写 stderr）。同样是为了「不静默」。
    """

    def __init__(
        self,
        *,
        bubble_fn: Callable[[str, str], None] | None = None,
        fallback_to_messagebox: bool = True,
        on_error: Callable[[BaseException], None] | None = None,
    ) -> None:
        self._bubble_fn = bubble_fn
        self._fallback = fallback_to_messagebox
        self._on_error = on_error

    # ── Port 实现 ─────────────────────────────────────────────────

    def notify(self, level: Severity, title: str, body: str) -> None:
        """发一条通知。**永不抛出**（契约要求）。"""
        try:
            if self._deliver(level, title, body):
                return
            # 所有投递方式都失败 → 至少写 stderr，不做静默黑洞
            self._log_fallback(level, title, body)
        except BaseException as exc:  # noqa: BLE001 —— 契约要求永不抛出
            self._report(exc)
            self._log_fallback(level, title, body)

    def _deliver(self, level: Severity, title: str, body: str) -> bool:
        """尝试投递，成功返回 True。"""
        # P0/P1 走弹窗（气泡会被忽略，该打扰时必须打扰）
        if level.is_page:
            return self._show_message(title, body, level)

        # 常规：优先托盘气泡
        if self._bubble_fn is not None:
            try:
                self._bubble_fn(title, body)
                return True
            except Exception as exc:  # noqa: BLE001
                self._report(exc)
                # 气泡失败继续走降级链

        if self._fallback:
            return self._show_message(title, body, level)
        return False

    def _show_message(self, title: str, body: str, level: Severity) -> bool:
        """用 MessageBoxW 弹窗。非 Windows 或调用失败返回 False。"""
        if not _is_windows() or not self._fallback:
            return False
        try:
            import ctypes  # noqa: PLC0415 —— 仅 Windows 下需要

            ctypes.windll.user32.MessageBoxW(
                None, body, title,
                MB_OK | _level_icon(level) | MB_TOPMOST,
            )
            return True
        except Exception as exc:  # noqa: BLE001
            self._report(exc)
            return False

    def _log_fallback(self, level: Severity, title: str, body: str) -> None:
        """最后兜底：stderr。绝不静默。"""
        print(f'[{level.value}] {title}: {body}', file=sys.stderr)

    def _report(self, exc: BaseException) -> None:
        if self._on_error is not None:
            try:
                self._on_error(exc)
            except Exception:  # noqa: BLE001 —— 错误回调自己炸了也只能吞
                pass


def notify_via_webview(bridge: Any) -> Callable[[str, str], None]:
    """把 pywebview 桥接对象包装成气泡回调。

    P4 组装时用：`WinNotifier(bubble_fn=notify_via_webview(bridge))`。
    包装时把「bridge 可能没有该方法」处理掉，避免调用点到处 try。
    """

    def _send(title: str, body: str) -> None:
        fn = getattr(bridge, 'show_toast', None)
        if fn is None:
            raise AttributeError('bridge 未提供 show_toast 方法')
        fn(title, body)

    return _send


__all__ = [
    'WinNotifier',
    'notify_via_webview',
]
