"""v8 GUI 启动入口（PyInstaller spec 的程序入口）。

与 v6 (server_manager.py / ERP_System.exe) 不同名并存：
    v6 → ERP_System.exe / server_manager.exe（后端+GUI 一体）
    v8 → server_manager_v8.exe（仅 GUI，业务层通过 ProcessPort 调外部后端）
EXE 体积大幅缩小（排除 fastapi/uvicorn/celery/pandas/numpy 等后端重依赖）。

启动：装配容器 → 调用 webview_host.run_gui → 阻塞至窗口关闭。
"""

from __future__ import annotations

import sys

from server_manager_v8.container import build_container
from server_manager_v8.presentation.webview_host import run_gui


def main() -> int:
    container = build_container()
    return run_gui(container, debug=False)


if __name__ == '__main__':
    sys.exit(main())
