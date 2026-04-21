"""
ERP系统开发调试启动脚本 (FastAPI 单框架版)

开发环境启动：python run.py（支持 auto-reload）
生产环境使用：python start_production_optimized.py
"""
import os
import sys

# Windows UTF-8 输出
if sys.platform == 'win32':
    import io
    if sys.stdout and hasattr(sys.stdout, 'buffer'):
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    if sys.stderr and hasattr(sys.stderr, 'buffer'):
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

# 虚拟环境自动检测
_VENV_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), '.venv313')
_VENV_PYTHON = os.path.join(_VENV_DIR, 'Scripts', 'python.exe')
if sys.platform != 'win32':
    _VENV_PYTHON = os.path.join(_VENV_DIR, 'bin', 'python')

if os.path.isfile(_VENV_PYTHON) and os.path.normpath(sys.executable) != os.path.normpath(_VENV_PYTHON):
    os.execv(_VENV_PYTHON, [_VENV_PYTHON] + sys.argv)

# 加载 .env
from dotenv import load_dotenv
load_dotenv(override=False)

if __name__ == '__main__':
    import uvicorn
    from fastapi_app.core.config import settings

    print("=" * 60)
    print("ERP系统开发调试服务器 (FastAPI)")
    print("=" * 60)
    print(f"FastAPI 访问地址: http://127.0.0.1:5002")
    print(f"API 文档: http://127.0.0.1:5002/api/docs")
    print(f"调试模式: {settings.FASTAPI_DEBUG}")
    print("=" * 60)

    try:
        uvicorn.run(
            "fastapi_app.main:app",
            host="0.0.0.0",
            port=5002,
            reload=settings.FASTAPI_DEBUG,
            reload_dirs=["fastapi_app"] if settings.FASTAPI_DEBUG else None,
        )
    except KeyboardInterrupt:
        print("\n收到停止信号，正在关闭服务器...")
    except Exception as e:
        print(f"服务器错误: {e}")
        raise
