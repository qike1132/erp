"""
ERP系统生产环境启动脚本 (FastAPI 单框架版)

使用 Uvicorn 多 worker 模式启动 FastAPI 服务。
适用于单机直接部署的生产服务器（Linux 多 worker / Windows 单 worker）。
Docker 部署请使用 docker-compose.yml。
"""
import os
import sys
import gc
import time
import logging
import threading
from datetime import datetime

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


def setup_gc():
    gc.set_threshold(700, 15, 15)
    gc.enable()


def setup_logging():
    log_dir = 'logs'
    if not os.path.exists(log_dir):
        os.makedirs(log_dir)

    logger = logging.getLogger('production')
    if logger.handlers:
        return logger

    logger.setLevel(logging.INFO)
    formatter = logging.Formatter('[%(asctime)s] %(levelname)s: %(message)s')

    file_handler = logging.FileHandler(f'{log_dir}/server.log', encoding='utf-8')
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setFormatter(formatter)
    logger.addHandler(stream_handler)

    return logger


def print_banner(logger, port, workers):
    lines = [
        "\n" + "=" * 60,
        "  ERP 系统 - Uvicorn 生产服务器",
        "=" * 60,
        f"  启动时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"  Python版本: {sys.version.split()[0]}",
        "-" * 60,
        f"  访问地址: http://127.0.0.1:{port}",
        f"  API 文档: http://127.0.0.1:{port}/api/docs",
        f"  Worker 数: {workers}",
        "-" * 60,
        "  按 Ctrl+C 停止服务",
        "=" * 60 + "\n",
    ]
    for line in lines:
        logger.info(line)


def run_periodic_cleanup(logger):
    cleanup_loop_running = True

    def cleanup_loop():
        nonlocal cleanup_loop_running
        while cleanup_loop_running:
            time.sleep(300)
            if cleanup_loop_running:
                collected = gc.collect()
                if collected > 0:
                    logger.info(f"[清理] 回收对象: {collected}")

    thread = threading.Thread(target=cleanup_loop, daemon=True)
    thread.start()
    return thread


def stop_cleanup():
    pass


def main():
    setup_gc()
    logger = setup_logging()

    from fastapi_app.core.config import settings

    port = 5002
    # Windows 不支持 uvicorn 多 worker（无 fork），强制使用单 worker
    # Linux 生产环境建议设置 UVICORN_WORKERS=CPU核数
    if sys.platform == 'win32':
        workers = 1
        logger.info("Windows 平台: 使用单 worker 模式（不支持多 worker）")
    else:
        workers = int(os.getenv("UVICORN_WORKERS", "4"))
        logger.info(f"Linux 平台: 使用 {workers} worker 模式")

    print_banner(logger, port, workers)
    run_periodic_cleanup(logger)

    import uvicorn

    try:
        logger.info("Uvicorn 生产服务器启动中...")
        uvicorn.run(
            "fastapi_app.main:app",
            host="0.0.0.0",
            port=port,
            workers=workers,
            log_level="info",
            access_log=True,
        )
    except KeyboardInterrupt:
        logger.info("收到停止信号，正在关闭服务器...")
    except Exception as e:
        logger.error(f"服务器错误: {e}")
        raise
    finally:
        logger.info("服务器已停止")


if __name__ == '__main__':
    main()
