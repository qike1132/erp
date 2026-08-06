"""
ERP系统开发环境启动脚本 (FastAPI + Vue/Vite) — 兼容快捷方式

开发模式特点：
  - FastAPI 开启 --reload（代码修改自动重启）
  - Vue/Vite 开启 HMR（热模块替换）

用法:
    python run.py              # 开发模式启动
    python start.py --help     # 查看所有选项

注意：此文件为历史兼容快捷方式，请直接使用 python start.py
"""
import os
import sys
from pathlib import Path

if __name__ == '__main__':
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    os.environ.setdefault('FASTAPI_DEBUG', 'true')

    # 保留用户传入的额外参数，默认追加 --dev
    extra_args = [a for a in sys.argv[1:] if a not in ('--dev', '--prod')]
    if '--prod' not in sys.argv and '--dev' not in sys.argv:
        extra_args.insert(0, '--dev')
    sys.argv = [sys.argv[0]] + extra_args

    from start import main
    main()
