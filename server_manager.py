"""ERP 服务器管理器入口(薄壳)。

实现已迁入 server_manager/ 包;本文件只为保持以下入口不变:
  · 双击桌面快捷方式 / PyInstaller spec 的 Analysis(['server_manager.py'])
  · `python server_manager.py`
包与模块同名时 **包优先**(已实测),故 `from server_manager.app import main` 解析到包。
"""
from server_manager.app import main

if __name__ == '__main__':
    main()
