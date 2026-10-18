"""ERP 服务器管理器(包)。

实现位于 server_manager.app;根 server_manager.py 为薄壳入口。

2026-10-18 OCR 评审：原实现 `from server_manager.app import main` 会在导入包时
立刻拉起 Tk GUI 栈（tkinter / app / dev_mode / redis_ops / widgets），
`start.py --prod` 只为调用 git_guard 也会被迫导入 GUI 模块。改为惰性转发。
"""
from typing import Any

__all__ = ["main"]


def main(*args: Any, **kwargs: Any) -> Any:
    from server_manager.app import main as _main

    return _main(*args, **kwargs)
