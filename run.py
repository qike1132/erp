"""
ERP系统开发环境启动脚本 (FastAPI + Vue/Vite)

开发模式特点：
  - FastAPI 开启 --reload（代码修改自动重启）
  - Vue/Vite 开启 HMR（热模块替换）

用法:
    python run.py

高级选项:
    python start.py --help
"""
import sys
import os
from pathlib import Path

if __name__ == '__main__':
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    os.environ.setdefault('FASTAPI_DEBUG', 'true')
    # 直接导入并执行 start.py 的 main 函数
    from start import main
    main()
