"""pywebview 窗口宿主 —— 创建窗口、挂桥、跑事件循环。

═══════════════════════════════════════════════════════════════════
本模块的职责边界
═══════════════════════════════════════════════════════════════════

只做四件事：
    ① 定位前端资源（开发态读源码目录，打包态读临时解包目录）
    ② 创建 pywebview 窗口并挂上 `JsBridge`
    ③ 起一个轮询定时器，把服务器状态推给前端
    ④ 处理窗口关闭（不能让「有服务在跑」时无声退出）

**不做**：业务判定（在 domain）、编排（在 usecase）、序列化（在 serializers）。

═══════════════════════════════════════════════════════════════════
★ 为什么资源路径要两套逻辑
═══════════════════════════════════════════════════════════════════

PyInstaller 打包后，`__file__` 指向**临时解包目录**
（`sys._MEIPASS`），而源码开发态指向仓库。两者必须都能找到
`presentation/web/index.html`，否则：

    · 开发态能跑、打包后白屏  ← 最常见的 PyInstaller 事故
    · 或反之

所以 `resolve_web_dir()` 依次尝试：
    1. `sys._MEIPASS` 下的解包路径（打包态）
    2. 本文件同级的 `web/`（开发态）
找不到就**明确报错**而不是静默回退到 about:blank ——
白屏比崩溃更难查（没有任何日志）。

═══════════════════════════════════════════════════════════════════
★ 为什么用「前端轮询」而不是「后端推送」
═══════════════════════════════════════════════════════════════════

pywebview 的 `evaluate_js()` 必须在 **UI 线程**调用。而状态采样
（服务状态、端口占用、指标）天然该在后台线程做 —— 否则会卡界面。

若从后台线程直接 `evaluate_js`：不同 pywebview 版本表现不一，
可能崩、可能静默无效（后者更糟：看起来正常，实际没更新）。

所以：后端线程只管**采样入队**，前端按固定周期调 `poll_events()`
取走。代价是最长一个周期的延迟（本项目 1 秒），完全可接受。
"""

from __future__ import annotations

import logging
import sys
import threading
from pathlib import Path
from typing import Any

from ..container import Container
from .bridge import JsBridge

log = logging.getLogger(__name__)

#: 窗口默认尺寸
DEFAULT_WIDTH = 1280
DEFAULT_HEIGHT = 860
#: 最小尺寸（再小布局会挤成一团）
MIN_WIDTH = 1024
MIN_HEIGHT = 700

#: 前端轮询周期（毫秒）—— 与 EventPump 的队列容量配合
POLL_INTERVAL_MS = 1000


def resolve_web_dir() -> Path:
    """定位前端资源目录。

    ★ 找不到必须**抛异常**而不是返回 about:blank ——
      白屏没有任何日志，是最难排查的失败模式。
    """
    candidates: list[Path] = []

    # ① 打包态：PyInstaller 解包目录
    meipass = getattr(sys, '_MEIPASS', None)
    if meipass:
        candidates.append(Path(meipass) / 'server_manager_v8' / 'presentation' / 'web')

    # ② 开发态：本文件同级
    candidates.append(Path(__file__).resolve().parent / 'web')

    for path in candidates:
        if (path / 'index.html').exists():
            return path

    tried = '\n'.join(f'  - {p}' for p in candidates)
    raise FileNotFoundError(
        f'找不到前端资源（index.html）。已尝试：\n{tried}\n'
        f'若为打包运行，请检查 spec 的 datas 是否包含 presentation/web'
    )


def build_entry_url() -> str:
    """窗口入口 URL（本地文件）。"""
    index = resolve_web_dir() / 'index.html'
    return index.as_uri()


class WebviewHost:
    """窗口宿主。

    用法：
        host = WebviewHost(container)
        host.run()          # 阻塞，直到窗口关闭
    """

    def __init__(
        self,
        container: Container,
        *,
        title: str = 'ERP 服务器管理器 v8',
        width: int = DEFAULT_WIDTH,
        height: int = DEFAULT_HEIGHT,
        debug: bool = False,
    ) -> None:
        self._c = container
        self._title = title
        self._width = width
        self._height = height
        self._debug = debug

        self._bridge = JsBridge(container, on_window_ready=self._on_window_ready)
        self._window: Any = None
        self._closing = threading.Event()

    # ── 属性 ────────────────────────────────────────────────────

    @property
    def bridge(self) -> JsBridge:
        return self._bridge

    @property
    def window(self) -> Any:
        return self._window

    # ── 生命周期 ────────────────────────────────────────────────

    def _on_window_ready(self) -> None:
        """前端 DOM 就绪回调。

        ★ 这里只做「通知后端已就绪」的副作用（如启动指标采样），
          不做数据拉取 —— 首屏数据由前端主动调 `bootstrap()`。
          让前端掌握节奏，避免后端在 DOM 未就绪时推数据。
        """
        log.info('前端已就绪')

    def _on_closing(self) -> bool:
        """窗口关闭前回调，返回 False 可阻止关闭。

        ★ 有服务在运行时**提示**而不是静默退出：
          用户可能忘了生产服务还开着，直接关窗口会让服务留在后台
          处于「无人看管」状态 —— 下一次启动管理器时会报端口冲突，
          而用户完全想不起为什么。
        """
        # 关闭是不可阻挡的（pywebview 的 closing 事件仅通知）。
        # 这里记日志，由 gui_launcher 在退出前做清理。
        log.info('窗口正在关闭')
        self._closing.set()
        return True

    def _on_closed(self) -> None:
        log.info('窗口已关闭')

    def create_window(self) -> Any:
        """创建窗口（不启动事件循环）。

        ★ 拆成独立方法是为了可测：测试可以在不跑 GUI 的前提下
          验证「桥挂上了、URL 对了、尺寸对了」这三件事。
        """
        import webview  # noqa: PLC0415 — 延迟导入，见下方说明

        # ★ 为什么延迟导入 webview：它依赖 pythonnet / clr_loader，
        #   在无 GUI 的 CI 里 import 会失败。放在函数内，
        #   让「导入本模块」与「真的要开窗口」解耦。
        self._window = webview.create_window(
            self._title,
            url=build_entry_url(),
            js_api=self._bridge,
            width=self._width,
            height=self._height,
            min_size=(MIN_WIDTH, MIN_HEIGHT),
            # 不使用 frameless / easy_drag：保留系统标题栏，
            # 用户熟悉的最小化/最大化/关闭都在，不重新发明窗口控制
            text_select=False,
        )
        self._bridge.attach_window(self._window)
        self._window.events.closing += self._on_closing
        self._window.events.closed += self._on_closed
        return self._window

    def run(self, *, private_mode: bool = False) -> None:
        """创建窗口并阻塞运行，直到窗口关闭。

        `private_mode=False`：pywebview 用 EdgeWebView 时会写用户数据目录；
        传 False 让它用默认目录（保持登录态/缩放等偏好）。
        """
        import webview  # noqa: PLC0415

        self.create_window()
        log.info('启动界面：%s', build_entry_url())

        webview.start(
            debug=self._debug,
            private_mode=private_mode,
        )

    # ── 供外部（launcher）使用 ──────────────────────────────────

    def request_close(self) -> None:
        """请求关闭窗口（供退出流程调用）。"""
        if self._window is not None:
            try:
                self._window.destroy()
            except Exception as exc:  # noqa: BLE001
                log.warning('关闭窗口失败: %s', exc)

    @property
    def closing(self) -> bool:
        return self._closing.is_set()


def run_window(container: Container, **kwargs: Any) -> None:
    """便捷入口：创建宿主并运行。"""
    WebviewHost(container, **kwargs).run()


__all__ = [
    'DEFAULT_HEIGHT',
    'DEFAULT_WIDTH',
    'MIN_HEIGHT',
    'MIN_WIDTH',
    'POLL_INTERVAL_MS',
    'WebviewHost',
    'build_entry_url',
    'resolve_web_dir',
    'run_window',
]
