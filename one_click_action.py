# -*- coding: utf-8 -*-
"""
通用『一键重启 / 一键关闭』按钮组件（开发模式 / 生产模式共用）
================================================================
与 ui_prototype_v2.html 中的 JS 组件同构，适配 server_manager.py v6.0.0。

架构（依赖方向：UI → 控制器 → 锁/配置 → 执行体）::

    OneClickButtonGroup        Tkinter UI：确认 → 触发 → loading → 复位
            │ 调用
            ▼
    OneClickActionController   状态校验 / 幂等 / 并发锁 / 结果收口
            │ 调用
            ├──► ActionLock        全局在途锁（开发/生产共享 → 跨模式互斥）
            └──► ModeActionSpec    模式差异配置（running + 执行体 + 确认策略）

幂等与并发
----------
- 防重复触发：ActionLock 原子占用，在途期间一切新请求被拒绝；
- 跨模式互斥：开发与生产共享同一把锁；
- 非运行态调用即拒绝（不产生副作用）；
- 执行体异常 → 失败回调 + 锁必然释放（finally），状态永不卡死。
"""

from __future__ import annotations

import threading
import tkinter as tk
from dataclasses import dataclass, field
from typing import Callable, Optional

# ======================================================================
# 一、ActionLock —— 并发 / 幂等控制（线程安全）
# ======================================================================


class ActionLock:
    """一键操作在途锁：同一时刻仅允许一个『重启/关闭』在途。"""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._owner: Optional[str] = None

    def acquire(self, who: str) -> bool:
        with self._lock:
            if self._owner is not None:
                return False
            self._owner = who
            return True

    def release(self, who: Optional[str] = None) -> None:
        with self._lock:
            if who is None or self._owner == who:
                self._owner = None

    @property
    def owner(self) -> Optional[str]:
        with self._lock:
            return self._owner


# ======================================================================
# 二、ModeActionSpec —— 模式差异的唯一收敛点
# ======================================================================


@dataclass(frozen=True)
class ModeActionSpec:
    """一键操作的模式规格：开发/生产的全部差异都定义在此（新增模式=新增 spec）。

    key:         模式标识（'dev' / 'prod'），用于锁占用方与日志前缀
    display:     面向用户的模式名
    running:     无参可调用，返回该模式当前是否运行态（调用方注入）
    do_restart:  重启执行体（控制器后台线程内同步执行，内部不得再开线程）
    do_stop:     关闭执行体（同上）
    confirm_restart / confirm_stop: 触发前是否弹二次确认
    stop_desc:   关闭确认框补充说明（影响范围）
    """

    key: str
    display: str
    running: Callable[[], bool]
    do_restart: Callable[[], None]
    do_stop: Callable[[], None]
    confirm_restart: bool = False
    confirm_stop: bool = True
    stop_desc: str = ""
    report: bool = True  # 结果反馈是否由组件统一发出；False = 执行体自反馈（如 dev 走消息泵）

    restart_busy_text: str = field(default="", repr=False)
    stop_busy_text: str = field(default="", repr=False)

    def __post_init__(self) -> None:
        if not self.restart_busy_text:
            object.__setattr__(self, "restart_busy_text", f"{self.display}·重启中…")
        if not self.stop_busy_text:
            object.__setattr__(self, "stop_busy_text", f"{self.display}·停止中…")


# ======================================================================
# 三、OneClickActionController —— 统一状态管理与触发链路
# ======================================================================


class OneClickActionController:
    """一键操作控制器（与 UI 解耦）。

    触发链路::

        校验 can_* ──► 原子占用 ActionLock ──► 后台线程执行体
                │            │                      │
                ▼            ▼                      ▼
           拒绝并提示    拒绝并提示        成功/失败回调 + 释放锁 + 刷新 UI

    回调约定（构建者注入）:
    - on_success(kind, msg) / on_failure(kind, reason): 结果反馈（Toast/告警）
    - on_busy_change(): 在途状态变化（按钮 loading / 禁用刷新）
    """

    def __init__(
        self,
        app,
        spec: ModeActionSpec,
        lock: ActionLock,
        *,
        on_success: Optional[Callable[[str, str], None]] = None,
        on_failure: Optional[Callable[[str, str], None]] = None,
        on_busy_change: Optional[Callable[[], None]] = None,
    ) -> None:
        self.app = app
        self.spec = spec
        self.lock = lock
        self._on_success = on_success
        self._on_failure = on_failure
        self._on_busy_change = on_busy_change
        self._busy_kind: Optional[str] = None

    # ---------- 只读状态（UI 按钮可用性） ----------

    def can_restart(self) -> bool:
        return self.spec.running() and not self.inflight()

    def can_stop(self) -> bool:
        return self.spec.running() and not self.inflight()

    def inflight(self) -> bool:
        return self.lock.owner == self.spec.key

    @property
    def busy_kind(self) -> Optional[str]:
        return self._busy_kind

    # ---------- 触发入口 ----------

    def request_restart(self) -> bool:
        return self._dispatch("restart", self.spec.do_restart)

    def request_stop(self) -> bool:
        return self._dispatch("stop", self.spec.do_stop)

    # ---------- 内部实现 ----------

    def _dispatch(self, kind: str, execute: Callable[[], None]) -> bool:
        ok = self.can_restart() if kind == "restart" else self.can_stop()
        if not ok:
            self._reject(f"{self.spec.display}未运行或已有操作在途")
            return False
        if not self.lock.acquire(self.spec.key):
            self._reject("已有操作进行中，请稍候")
            return False
        self._busy_kind = kind
        self._notify_busy()
        threading.Thread(
            target=self._run_task, args=(kind, execute), daemon=True,
            name=f"one-click-{self.spec.key}-{kind}",
        ).start()
        return True

    def _run_task(self, kind: str, execute: Callable[[], None]) -> None:
        try:
            execute()
            self._finish(kind, True, "")
        except Exception as exc:
            self.app.log_message(f"[{self.spec.key}] {kind} 异常: {exc}", "ERROR")
            self._finish(kind, False, str(exc))

    def _finish(self, kind: str, success: bool, msg: str) -> None:
        """收口：释放锁 → 复位在途 → 结果回调 → 刷新 UI（顺序固定保证幂等）。"""
        self.lock.release(self.spec.key)
        self._busy_kind = None
        try:
            if self.spec.report:
                if success and self._on_success:
                    self._on_success(kind, msg)
                elif not success and self._on_failure:
                    self._on_failure(kind, msg or "未知错误")
        finally:
            self._notify_busy()

    def _reject(self, reason: str) -> None:
        self.app.toast.show("warn", "操作被拒绝", reason)
        self.app.log_message(f"[{self.spec.key}] 操作被拒绝: {reason}", "WARNING")

    def _notify_busy(self) -> None:
        if self._on_busy_change:
            try:
                self._on_busy_change()
            except Exception:
                pass


# ======================================================================
# 四、OneClickButtonGroup —— 通用『重启/关闭』按钮组（Tkinter UI 层）
# ======================================================================


class OneClickButtonGroup:
    """通用按钮组：开发/生产各实例化一份，仅凭 spec 区分。

    交互闭环::

        点击 ──► (可选)二次确认 ──► controller.request_* ──► 执行中 loading
                                                              │
                     ◄── 成功/失败 Toast + 告警 + 按钮复位 ────┘

    宿主在 `_update_all_ui` 中调用 `sync()` 保持按钮可用性最新。
    """

    def __init__(
        self,
        parent: tk.Widget,
        controller: OneClickActionController,
        *,
        restart_text: str = "重启",
        stop_text: str = "关闭",
        stop_parent: Optional[tk.Widget] = None,
    ) -> None:
        """``stop_parent``：关闭按钮的独立容器（UI 重构 v2 要求重启/关闭分行布局）。
        为 None 时与重启按钮同排（默认）。"""
        self.controller = controller
        self._restart_text = restart_text
        self._stop_text = stop_text
        RoundedButton = _load_rounded_button()
        canvas_bg = _palette_color("bg_panel")
        self.btn_restart = RoundedButton(
            parent, text=restart_text, command=self._on_restart,
            variant="outlined", tone="brand", canvas_bg=canvas_bg)
        self.btn_restart.pack(side=tk.LEFT, padx=(0, 8))
        stop_host = stop_parent if stop_parent is not None else parent
        self.btn_stop = RoundedButton(
            stop_host, text=stop_text, command=self._on_stop,
            variant="outlined", tone="danger", canvas_bg=canvas_bg)
        self.btn_stop.pack(side=tk.LEFT, padx=(0 if stop_parent is not None else 0, 0))
        # 在途状态变化 → 立即刷新按钮
        controller._on_busy_change = self._busy_sync

    # ---------- 交互入口 ----------

    def _on_restart(self) -> None:
        spec = self.controller.spec
        if spec.confirm_restart and not self._ask(
            f"确认重启{spec.display}？",
            f"将优雅停止并重新启动{spec.display}，已提交的任务可能中断。",
        ):
            return
        self.controller.request_restart()

    def _on_stop(self) -> None:
        spec = self.controller.spec
        if spec.confirm_stop and not self._ask(
            f"确认关闭{spec.display}？",
            spec.stop_desc or f"将停止{spec.display}的全部相关进程并释放端口。",
        ):
            return
        self.controller.request_stop()

    @staticmethod
    def _ask(title: str, message: str) -> bool:
        import tkinter.messagebox as mb

        return mb.askyesno(title, message, icon="warning", default="no")

    # ---------- 状态同步 ----------

    def sync(self) -> None:
        """按钮可用性 + 在途 loading（宿主 _update_all_ui 中调用）。"""
        ctrl = self.controller
        kind = ctrl.busy_kind
        if kind == "restart":
            self.btn_restart.set_loading(True, ctrl.spec.restart_busy_text)
            self.btn_restart.config(state="disabled")
            self.btn_stop.set_loading(False, self._stop_text)
            self.btn_stop.config(state="disabled")
        elif kind == "stop":
            self.btn_stop.set_loading(True, ctrl.spec.stop_busy_text)
            self.btn_stop.config(state="disabled")
            self.btn_restart.set_loading(False, self._restart_text)
            self.btn_restart.config(state="disabled")
        else:
            self.btn_restart.set_loading(False, self._restart_text)
            self.btn_restart.config(state="normal" if ctrl.can_restart() else "disabled")
            self.btn_stop.set_loading(False, self._stop_text)
            self.btn_stop.config(state="normal" if ctrl.can_stop() else "disabled")

    def _busy_sync(self) -> None:
        """在途变化即时回调（内部），并联动宿主全局刷新。"""
        self.sync()
        ctrl = self.controller
        on_change = getattr(ctrl, "_host_on_busy_change", None)
        if on_change:
            try:
                on_change()
            except Exception:
                pass


def _load_rounded_button():
    """延迟导入宿主的 RoundedButton（避免模块级循环依赖）。"""
    from server_manager import RoundedButton

    return RoundedButton


def _palette_color(token: str) -> str:
    """延迟获取宿主 TOKENS 颜色。"""
    from server_manager import TOKENS

    return TOKENS.c(token)
