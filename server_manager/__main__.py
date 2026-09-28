"""``python -m server_manager`` 入口(spec §2 明列的交付物之一)。

包化后除 GUI 脚本入口(``server_manager/app.py`` 直接运行)外,还须保留一个
**模块入口**,使 ``python -m server_manager`` 亦能启动管理器。此处只做薄壳,
不复制任何启动逻辑 —— 真正的入口仍是 ``server_manager.app.main``。
"""
from __future__ import annotations

from server_manager.app import main

if __name__ == "__main__":
    main()
