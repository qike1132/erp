"""
Waitress 生产环境优化启动脚本
版本: v2.1.0
优化内容: 性能调优、资源管理、安全增强、FastAPI集成
"""
import os
import sys
import gc
import time
import logging
import subprocess
import threading
from datetime import datetime

if sys.platform == 'win32':
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

os.environ['USE_NEW_ARCH'] = 'true'

from waitress import serve
from app import app

# FastAPI 子进程引用
_fastapi_process = None


def start_fastapi_subprocess():
    """在后台启动 FastAPI 服务"""
    global _fastapi_process

    log_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'logs')
    os.makedirs(log_dir, exist_ok=True)
    log_path = os.path.join(log_dir, 'fastapi.log')

    try:
        print("[INFO] 正在启动 FastAPI 服务 (端口 5002)...")
        # 二进制模式写入，避免子进程 GBK 输出与 UTF-8 文本模式冲突导致日志乱码
        log_file = open(log_path, 'ab')
        _fastapi_process = subprocess.Popen(
            [sys.executable, '-m', 'uvicorn',
             'fastapi_app.main:app',
             '--host', '0.0.0.0',
             '--port', '5002'],
            stdout=log_file,
            stderr=log_file,
        )
        print(f"[OK] FastAPI 服务已启动 (PID: {_fastapi_process.pid})，日志: {log_path}")
    except Exception as e:
        print(f"[WARN] FastAPI 服务启动失败: {e}")


def stop_fastapi_subprocess():
    """停止 FastAPI 子进程"""
    global _fastapi_process
    if _fastapi_process and _fastapi_process.poll() is None:
        print("[INFO] 正在停止 FastAPI 服务...")
        _fastapi_process.terminate()
        try:
            _fastapi_process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            _fastapi_process.kill()
        print("[OK] FastAPI 服务已停止")

class ServerConfig:
    """服务器配置类"""
    
    HOST = '0.0.0.0'
    PORT = 5003
    
    THREADS = 8
    CONNECTION_LIMIT = 300
    CHANNEL_TIMEOUT = 60
    SOCKET_TIMEOUT = 30
    
    SEND_BYTES = 18000
    INBUF_OVERFLOW = 524288
    OUTBUF_OVERFLOW = 1048576
    
    MAX_REQUEST_BODY_SIZE = 10485760
    
    EXPOSE_TRACEBACKS = False
    IDENT = None
    
    CLEANUP_INTERVAL = 30
    LINGER_TIMEOUT = 5
    
    ASYNCORE_USE_POLL = True
    
    @classmethod
    def get_serve_params(cls):
        params = {
            'host': cls.HOST,
            'port': cls.PORT,
            'threads': cls.THREADS,
            'connection_limit': cls.CONNECTION_LIMIT,
            'channel_timeout': cls.CHANNEL_TIMEOUT,
            'socket_timeout': cls.SOCKET_TIMEOUT,
            'send_bytes': cls.SEND_BYTES,
            'inbuf_overflow': cls.INBUF_OVERFLOW,
            'outbuf_overflow': cls.OUTBUF_OVERFLOW,
            'max_request_body_size': cls.MAX_REQUEST_BODY_SIZE,
            'expose_tracebacks': cls.EXPOSE_TRACEBACKS,
            'ident': cls.IDENT,
            'cleanup_interval': cls.CLEANUP_INTERVAL,
            'linger_timeout': cls.LINGER_TIMEOUT,
            'asyncore_use_poll': cls.ASYNCORE_USE_POLL,
        }
        # 过滤当前 waitress 版本不支持的参数
        try:
            from waitress.adjustments import Adjustments
            supported = set(p[0] for p in Adjustments._params)
            unsupported = [k for k in params if k not in supported]
            for k in unsupported:
                del params[k]
        except Exception:
            pass
        return params

def setup_gc():
    gc.set_threshold(700, 15, 15)
    gc.enable()
    print(f"[GC] 垃圾回收已配置: {gc.get_threshold()}")

def setup_logging():
    log_dir = 'logs'
    if not os.path.exists(log_dir):
        os.makedirs(log_dir)
    
    logging.basicConfig(
        level=logging.INFO,
        format='[%(asctime)s] %(levelname)s: %(message)s',
        handlers=[
            logging.FileHandler(f'{log_dir}/server.log', encoding='utf-8'),
            logging.StreamHandler(sys.stdout)
        ]
    )
    return logging.getLogger('waitress')

def print_banner():
    config = ServerConfig
    print("\n" + "=" * 70)
    print("  ERP 系统 - Waitress 生产服务器 (优化版)")
    print("=" * 70)
    print(f"  启动时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"  Python版本: {sys.version.split()[0]}")
    print("-" * 70)
    print("  网络配置:")
    print(f"    Flask  (端口 {config.PORT}): http://127.0.0.1:{config.PORT}")
    print(f"    FastAPI (端口 5002): http://127.0.0.1:5002")
    print(f"    局域网访问: http://192.168.0.95:{config.PORT}")
    print("-" * 70)
    print("  性能配置:")
    print(f"    工作线程: {config.THREADS}")
    print(f"    最大连接: {config.CONNECTION_LIMIT}")
    print(f"    通道超时: {config.CHANNEL_TIMEOUT}s")
    print(f"    Socket超时: {config.SOCKET_TIMEOUT}s")
    print(f"    请求体限制: {config.MAX_REQUEST_BODY_SIZE // 1024 // 1024}MB")
    print("-" * 70)
    print("  安全配置:")
    print(f"    错误追踪: {'开启' if config.EXPOSE_TRACEBACKS else '关闭'}")
    print(f"    服务器标识: {'显示' if config.IDENT else '隐藏'}")
    print("-" * 70)
    print("  按 Ctrl+C 停止服务")
    print("=" * 70 + "\n")

def run_periodic_cleanup():
    def cleanup_loop():
        while True:
            time.sleep(300)
            collected = gc.collect()
            if collected > 0:
                print(f"[清理] 回收对象: {collected}")
    
    thread = threading.Thread(target=cleanup_loop, daemon=True)
    thread.start()
    return thread

def main():
    setup_gc()
    logger = setup_logging()
    print_banner()

    # 启动 FastAPI 子进程
    start_fastapi_subprocess()

    # 等待 FastAPI 就绪
    print("[INFO] 等待 FastAPI 服务就绪...")
    time.sleep(3)

    run_periodic_cleanup()

    serve_params = ServerConfig.get_serve_params()

    try:
        logger.info("Waitress 服务器启动中...")
        serve(app, **serve_params)
    except KeyboardInterrupt:
        logger.info("收到停止信号，正在关闭服务器...")
    except Exception as e:
        logger.error(f"服务器错误: {e}")
        raise
    finally:
        stop_fastapi_subprocess()
        logger.info("服务器已停止")

if __name__ == '__main__':
    main()
