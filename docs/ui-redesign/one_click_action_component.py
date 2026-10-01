"""
通用『一键重启 / 一键关闭』按钮组件（开发模式 / 生产模式共用）
================================================================

设计目标
--------
开发模式与生产模式共用同一套『重启 / 关闭』交互，**零重复代码**：
1. 模式差异全部收敛到 :class:`ModeActionSpec` 配置（运行态判定 + 执行体 + 确认策略）；
2. 统一的状态校验 / 幂等 / 并发控制由 :class:`OneClickActionController` 提供；
3. UI 层 :class:`OneClickButtonGroup` 只负责『点击确认 → loading → 结果反馈』闭环，
   不掺入任何业务逻辑。

架构分层（依赖方向：UI → 控制器 → 锁/配置 → 执行体）
------------------------------------------------------
 OneClickButtonGroup            Tkinter 层（可替换为任意前端）
        │ 调用
        ▼
 OneClickActionController       状态校验 / 幂等 / 并发锁 / 结果回写
        │ 调用
        ├──► ActionLock          线程安全在途锁（防重复触发/跨模式冲突）
        └──► ModeActionSpec      模式差异配置（运行态 + 执行体 + 确认策略）
                    │
                    ▼
         do_restart / do_stop   业务执行体（调用方注入，后台线程内同步执行）

幂等与并发规则
--------------
- **防重复触发**：同一时刻仅允许一个『一键操作』在途，全局 ActionLock 原子占用；
- **跨模式互斥**：开发重启中，生产关闭请求会被拒绝（共享同一把锁）；
- **运行态校验**：非运行态调用重启/关闭直接拒绝（幂等，不产生副作用）；
- **状态闭环**：无论成功/失败/异常，finally 必释放锁并刷新 UI，永不"卡死"。

本模块零依赖（除 threading/dataclasses），逻辑层可脱离 Tkinter 独立单测。
"""

from __future__ import annotations

import threading
import tkinter as tk
from collections.abc import Callable
from dataclasses import dataclass, field

# ======================================================================
# 一、ActionLock —— 并发 / 幂等控制（纯逻辑，可独立单测）
# ======================================================================


class ActionLock:
    """一键操作在途锁（线程安全）。

    同一时刻仅允许一个『一键操作』(重启/关闭，且跨模式) 在途：
    - ``acquire`` 失败即拒绝新请求，杜绝连点/双线程重复触发；
    - 开发与生产共享同一把锁，天然实现"开发操作中禁止生产操作"；
    - ``owner`` 暴露给 UI，用于按钮禁用与『操作进行中』提示。
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._owner: str | None = None

    def acquire(self, who: str) -> bool:
        """尝试占用。成功返回 True；已被他人占用返回 False。"""
        with self._lock:
            if self._owner is not None:
                return False
            self._owner = who
            return True

    def release(self, who: str | None = None) -> None:
        """释放占用。``who`` 匹配才释放，防止误释放他人持有的锁。"""
        with self._lock:
            if who is None or self._owner == who:
                self._owner = None

    @property
    def owner(self) -> str | None:
        with self._lock:
            return self._owner


# ======================================================================
# 二、ModeActionSpec —— 模式差异的唯一收敛点（配置即扩展）
# ======================================================================


@dataclass(frozen=True)
class ModeActionSpec:
    """一键操作的模式规格：开发/生产的全部差异都定义在此。

    新增一种模式（如"测试模式"）只需新增一个 spec 并复用组件，
    符合开闭原则（对扩展开放、对修改关闭）。

    参数
    ----
    key:
        模式标识，用于锁占用方与日志前缀（如 'dev' / 'prod'）。
    display:
        面向用户的模式名（如 '开发模式' / '生产模式'）。
    running:
        无参可调用，返回该模式当前是否处于运行态；由调用方注入
        （依赖倒置：控制器不感知具体模式判定细节）。
    do_restart / do_stop:
        重启 / 关闭执行体，**在控制器开启的后台线程中同步执行**，
        内部不要再创建线程；自带步骤日志与状态回写。
    confirm_restart / confirm_stop:
        触发前是否弹二次确认。生产关闭风险高默认 True，开发重启
        低风险默认 False，可按模式配置。
    stop_desc:
        关闭确认框的补充说明（列出影响范围，帮助用户决策）。
    """

    key: str
    display: str
    running: Callable[[], bool]
    do_restart: Callable[[], None]
    do_stop: Callable[[], None]
    confirm_restart: bool = False
    confirm_stop: bool = True
    stop_desc: str = ""

    # 运行态文案映射（供 loading / 状态栏展示）
    restart_busy_text: str = field(default="", repr=False)
    stop_busy_text: str = field(default="", repr=False)

    def __post_init__(self) -> None:
        if not self.restart_busy_text:
            object.__setattr__(self, "restart_busy_text", f"{self.display}·重启中…")
        if not self.stop_busy_text:
            object.__setattr__(self, "stop_busy_text", f"{self.display}·停止中…")


# ======================================================================
# 三、OneClickActionController —— 统一状态管理与触发链路（纯逻辑）
# ======================================================================


class OneClickActionController:
    """一键操作控制器（与 UI 解耦，可直接单测）。

    触发链路（重启与关闭共用同一骨架）::

        校验 can_* ──► 原子占用 ActionLock ──► 后台线程执行体
                │            │                      │
                ▼            ▼                      ▼
           拒绝并提示      拒绝并提示        成功/失败回调 + 释放锁 + 刷新 UI

    回调约定（由构建者注入，解耦 UI 与业务）:
    - ``on_success(kind, text)`` / ``on_failure(kind, reason)``:
      结果反馈（Toast / 告警中心在此实现）；
    - ``on_busy_change()``: 在途状态变化时回调（按钮 loading / 禁用刷新）。
    """

    def __init__(
        self,
        app,
        spec: ModeActionSpec,
        lock: ActionLock,
        *,
        on_success: Callable[[str, str], None] | None = None,
        on_failure: Callable[[str, str], None] | None = None,
        on_busy_change: Callable[[], None] | None = None,
    ) -> None:
        self.app = app                 # 宿主应用（仅用于访问 toast/alerts/logger）
        self.spec = spec               # 模式差异配置
        self.lock = lock               # 全局共享在途锁（开发/生产同一把）
        self._on_success = on_success
        self._on_failure = on_failure
        self._on_busy_change = on_busy_change
        self._busy_kind: str | None = None   # 当前在途动作: 'restart' | 'stop' | None

    # ---------- 只读状态（供 UI 刷新按钮可用性） ----------

    def can_restart(self) -> bool:
        """重启是否可触发：模式运行中 且 无任何在途操作。"""
        return self.spec.running() and not self.inflight()

    def can_stop(self) -> bool:
        """关闭是否可触发：模式运行中 且 无任何在途操作。"""
        return self.spec.running() and not self.inflight()

    def inflight(self) -> bool:
        """当前是否已有本模式操作在途。"""
        return self.lock.owner == self.spec.key

    @property
    def busy_kind(self) -> str | None:
        return self._busy_kind

    # ---------- 触发入口（UI 调用；含确认则由按钮组负责） ----------

    def request_restart(self) -> bool:
        """请求一键重启。成功受理返回 True，被拒绝返回 False。"""
        return self._dispatch("restart", self.spec.do_restart)

    def request_stop(self) -> bool:
        """请求一键关闭。成功受理返回 True，被拒绝返回 False。"""
        return self._dispatch("stop", self.spec.do_stop)

    # ---------- 内部实现 ----------

    def _dispatch(self, kind: str, execute: Callable[[], None]) -> bool:
        """通用派发骨架：校验 → 占用 → 后台执行 → 反馈闭环。"""
        # 1. 前置校验（幂等：非运行态直接拒绝，不产生副作用）
        ok = self.can_restart() if kind == "restart" else self.can_stop()
        if not ok:
            self._reject(f"{self.spec.display}未运行或已有操作在途")
            return False

        # 2. 原子占用全局在途锁（并发防护，杜绝双触发）
        if not self.lock.acquire(self.spec.key):
            self._reject("已有操作进行中，请稍候")
            return False

        # 3. 标记在途 → 刷新 UI（按钮 loading / 禁用）
        self._busy_kind = kind
        self._notify_busy()

        # 4. 后台线程执行（执行体内部不得再开线程）
        threading.Thread(
            target=self._run_task,
            args=(kind, execute),
            daemon=True,
            name=f"one-click-{self.spec.key}-{kind}",
        ).start()
        return True

    def _run_task(self, kind: str, execute: Callable[[], None]) -> None:
        """后台执行体包装：任何异常都收口为失败反馈，绝不静默。"""
        try:
            execute()
            self._finish(kind, success=True, message=None)
        except Exception as exc:  # noqa: BLE001 —— 兜底：执行体未捕获的异常
            self.app.log_message(f"[{self.spec.key}] {kind} 异常: {exc}", "ERROR")
            self._finish(kind, success=False, message=str(exc))

    def _finish(self, kind: str, success: bool, message: str | None) -> None:
        """收口：释放锁 + 复位在途 + 结果回调 + 刷新 UI。顺序固定保证幂等。"""
        self.lock.release(self.spec.key)
        self._busy_kind = None
        try:
            if success:
                if self._on_success:
                    self._on_success(kind, message or "")
            else:
                if self._on_failure:
                    self._on_failure(kind, message or "未知错误")
        finally:
            self._notify_busy()          # 无论成败，最后必须刷新按钮状态

    def _reject(self, reason: str) -> None:
        """拒绝请求：轻提示（不弹告警，避免噪音）。"""
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
    """通用按钮组：开发/生产各实例化一份，仅凭 spec 区分，代码零重复。

    交互闭环::

        点击 ──► (可选)二次确认 ──► controller.request_* ──► 执行中 loading
                                                              │
                     ◄── 成功/失败 Toast + 告警 + 按钮复位 ────┘

    用法（在宿主 UI 类中）::

        group = OneClickButtonGroup(panel, controller)
        # 宿主 _update_all_ui 中调用 group.sync() 保持可用性最新
    """

    def __init__(
        self,
        parent: tk.Widget,
        controller: OneClickActionController,
        *,
        restart_text: str = "重启",
        stop_text: str = "关闭",
        restart_kw: dict | None = None,
        stop_kw: dict | None = None,
    ) -> None:
        self.controller = controller
        self._restart_text = restart_text
        self._stop_text = stop_text
        self._orig_restart_text = restart_text
        self._orig_stop_text = stop_text

        # 复用宿主的 RoundedButton（v6.0.0 自绘组件，含 loading/disabled）
        RoundedButton = _load_rounded_button()
        canvas_bg = _palette_color('bg_panel')
        self.btn_restart = RoundedButton(
            parent, text=restart_text,
            command=self._on_restart,
            variant=(restart_kw or {}).get("variant", "outlined"),
            tone=(restart_kw or {}).get("tone", "brand"),
            canvas_bg=canvas_bg,
        )
        self.btn_stop = RoundedButton(
            parent, text=stop_text,
            command=self._on_stop,
            variant=(stop_kw or {}).get("variant", "outlined"),
            tone=(stop_kw or {}).get("tone", "danger"),
            canvas_bg=canvas_bg,
        )
        # 注册 busy 回调：在途状态变化时同步 loading 与禁用
        controller._on_busy_change = self.sync

    # ---------- 交互入口 ----------

    def _on_restart(self) -> None:
        spec = self.controller.spec
        # 二次确认（按模式配置；默认重启轻量不确认）
        if spec.confirm_restart and not self._ask(
            f"确认重启{spec.display}？",
            f"将优雅停止并重新启动{spec.display}，已提交的任务可能中断。",
        ):
            return
        self.controller.request_restart()

    def _on_stop(self) -> None:
        spec = self.controller.spec
        # 二次确认（生产默认必确认，开发可配置关闭）
        if spec.confirm_stop and not self._ask(
            f"确认关闭{spec.display}？",
            spec.stop_desc or f"将停止{spec.display}的全部相关进程并释放端口。",
        ):
            return
        self.controller.request_stop()

    @staticmethod
    def _ask(title: str, message: str) -> bool:
        """统一确认弹窗（沿用宿主 messagebox 风格）。"""
        import tkinter.messagebox as mb

        return mb.askyesno(title, message, icon="warning", default="no")

    # ---------- 状态同步（宿主 _update_all_ui 中调用） ----------

    def sync(self) -> None:
        """刷新按钮可用性与在途 loading 文案。"""
        ctrl = self.controller
        kind = ctrl.busy_kind
        if kind == "restart":
            self.btn_restart.set_loading(True, ctrl.spec.restart_busy_text)
            self.btn_restart.config(state="disabled")
            self.btn_stop.set_loading(False, self._orig_stop_text)
            self.btn_stop.config(state="disabled")
        elif kind == "stop":
            self.btn_stop.set_loading(True, ctrl.spec.stop_busy_text)
            self.btn_stop.config(state="disabled")
            self.btn_restart.set_loading(False, self._orig_restart_text)
            self.btn_restart.config(state="disabled")
        else:
            self.btn_restart.set_loading(False, self._orig_restart_text)
            self.btn_restart.config(state="normal" if ctrl.can_restart() else "disabled")
            self.btn_stop.set_loading(False, self._orig_stop_text)
            self.btn_stop.config(state="normal" if ctrl.can_stop() else "disabled")


def _load_rounded_button():
    """延迟导入宿主的 RoundedButton（避免模块级循环依赖）。"""
    from server_manager.widgets import RoundedButton

    return RoundedButton


def _palette_color(token: str) -> str:
    """延迟获取宿主调色板颜色（隔离对宿主模块的模块级依赖）。

    原文引用 ``from server_manager import TOKENS``,但 ``TOKENS`` 从未存在过
    (包化前后全仓皆无此名)。真实调色板是 ``ServerManagerApp._PALETTE``
    (见 server_manager/app.py),按其原意直取该字典。
    """
    from server_manager.app import ServerManagerApp

    return ServerManagerApp._PALETTE[token]


# ======================================================================
# 五、接入示例（与 server_manager.py v6.0.0 对接）
# ======================================================================
"""
在 ServicesPage 中接入（示意，按实际结构微调）:

    # 1) 定义两个模式 spec —— 全部差异在此，组件零改动
    app = self.app

    def _dev_restart_impl():
        # 执行体：controller 已开后台线程，此处同步写停止+启动逻辑
        # （可复用现有 _restart_dual_thread 的主体，去掉自身线程包装）
        app._mode, app._current_mode_key = 'restarting', 'dual_dev'
        _graceful_stop_development(app)      # 停前端/后端/Redis/清端口
        _start_dual_thread(app, '开发模式（前后端）')   # 重新启动 + 健康检查

    def _dev_stop_impl():
        _graceful_stop_development(app)      # 进程树 + Redis + 端口
        app._mode, app._current_mode_key = 'none', ''
        app._update_all_ui()

    dev_spec = ModeActionSpec(
        key='dev', display='开发模式',
        running=lambda: app._mode == 'dual_dev',
        do_restart=_dev_restart_impl,
        do_stop=_dev_stop_impl,
        confirm_restart=False,
        confirm_stop=False,      # 开发关闭低风险，跳过确认
    )

    def _prod_restart_impl():
        # 优雅重启：stop 等 STOPPED → start 等 RUNNING（防 AppExit 自动重启抢端口）
        for name in (_SVC_API, _SVC_ARQ):
            nssm = app._find_nssm()
            if nssm:
                subprocess.run(['nssm', 'stop', name], executable=nssm, **_cap(15))
            else:
                subprocess.run(['sc', 'stop', name], **_cap(15))
            # 实现已迁 ServiceOps（T4 包化）：经 app.svc 访问，方法名去掉前导下划线
            if not app.svc.wait_service_stopped(name, timeout=45):
                raise RuntimeError(f'{name} 停止超时，已中止重启')
        app._release_ports()
        for name in (_SVC_API, _SVC_ARQ):
            nssm = app._find_nssm()
            if nssm:
                subprocess.run(['nssm', 'start', name], executable=nssm, **_cap(30))
            else:
                subprocess.run(['sc', 'start', name], **_cap(30))
        if not app.svc.wait_service_running(_SVC_API):
            raise RuntimeError('重启后未达 RUNNING，健康检查失败')

    prod_spec = ModeActionSpec(
        key='prod', display='生产模式',
        running=lambda: app._prod_running,
        do_restart=_prod_restart_impl,
        do_stop=_prod_stop_impl,
        confirm_stop=True,
        stop_desc='将停止 erp-prod / erp-arq 服务（保留 NSSM 注册，可再次一键启动）',
    )

    # 2) 共享同一把全局锁（开发/生产互斥）
    self._action_lock = ActionLock()

    # 3) 实例化两个通用按钮组（同一组件类，零重复）
    feedback = dict(
        on_success=lambda k, m: (app.toast.show('ok', f'{spec.display}已{k}', m),
                                 app.log_message(f'{spec.display}{k}成功')),
        on_failure=lambda k, r: (app.alerts.raise_alert(f'{spec.key}_{k}_failed', 'error',
                                                        f'{spec.display}{k}失败', r),
                                 app.toast.show('error', f'{spec.display}{k}失败', r)),
    )
    self.dev_actions = OneClickButtonGroup(dev_panel, OneClickActionController(app, dev_spec, self._action_lock, **feedback))
    self.prod_actions = OneClickButtonGroup(prod_panel, OneClickActionController(app, prod_spec, self._action_lock, **feedback))

    # 4) 宿主状态刷新钩子：_update_all_ui() 中追加
    #    self.dev_actions.sync(); self.prod_actions.sync()
"""


# ======================================================================
# 六、单元测试骨架（逻辑层可脱离 Tkinter 运行）
# ======================================================================
"""
class _FakeApp:                       # 最小宿主桩
    def __init__(self):
        self.mode = 'none'
        self.toast = _FakeToast()
        self.alerts = _FakeAlerts()
        self.logs = []
    def log_message(self, msg, level='INFO'): self.logs.append((level, msg))

def test_stop_rejected_when_not_running():
    app = _FakeApp()
    spec = ModeActionSpec(key='dev', display='开发', running=lambda: app.mode == 'dual_dev',
                          do_restart=lambda: None, do_stop=lambda: None)
    ctrl = OneClickActionController(app, spec, ActionLock())
    assert ctrl.request_stop() is False            # 幂等：非运行态拒绝
    assert ctrl.lock.owner is None                 # 且未占用锁

def test_concurrent_requests_rejected():
    app = _FakeApp(); app.mode = 'dual_dev'
    spec = ModeActionSpec(key='dev', display='开发', running=lambda: True,
                          do_restart=lambda: None, do_stop=lambda: None)
    ctrl = OneClickActionController(app, spec, ActionLock())
    assert ctrl.request_restart() is True          # 第一次受理
    assert ctrl.request_stop() is False            # 在途期间第二次拒绝
"""
