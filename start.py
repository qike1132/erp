#!/usr/bin/env python3
"""
ERP系统统一启动管理器

同时启动 FastAPI 后端和 Next.js 前端。
支持开发模式和生产模式，提供进程管理、健康检查和优雅关闭。

用法:
    python start.py                # 开发模式
    python start.py --prod         # 生产模式
    python start.py --backend-only # 仅后端
    python start.py --frontend-only # 仅前端
    python start.py --skip-backend # 跳过后端
    python start.py --help         # 帮助
"""

import os
import sys
import time
import signal
import subprocess
import threading
import argparse
from pathlib import Path
from datetime import datetime

if sys.platform == 'win32':
    import io
    if sys.stdout and hasattr(sys.stdout, 'buffer'):
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    if sys.stderr and hasattr(sys.stderr, 'buffer'):
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

from dotenv import load_dotenv
load_dotenv(override=False)

# ==================== 配置 ====================

PROJECT_ROOT = Path(__file__).resolve().parent
FRONTEND_DIR = PROJECT_ROOT / "frontend-nextjs"

# ==================== 颜色 ====================

class Color:
    BLUE = '\033[94m'
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    RED = '\033[91m'
    BOLD = '\033[1m'
    DIM = '\033[2m'
    HEADER = '\033[95m'
    RESET = '\033[0m'

    @classmethod
    def wrap(cls, text, color):
        if sys.platform == 'win32':
            os.system('')
        return f"{color}{text}{cls.RESET}"


def ts():
    return datetime.now().strftime("%H:%M:%S")


def log_info(name, color, msg):
    print(Color.wrap(f"[{ts()}] {name}", color) + f"  {msg}", flush=True)

def log_error(name, msg):
    print(Color.wrap(f"[{ts()}] {name}", Color.RED) + Color.wrap(f"  ERROR: {msg}", Color.RED), flush=True)

def log_success(name, msg):
    print(Color.wrap(f"[{ts()}] {name}", Color.GREEN) + Color.wrap(f"  ✓ {msg}", Color.GREEN), flush=True)

def log_warn(name, msg):
    print(Color.wrap(f"[{ts()}] {name}", Color.YELLOW) + Color.wrap(f"  WARN: {msg}", Color.YELLOW), flush=True)


# ==================== 横幅 ====================

def print_banner(mode, api_port, web_port):
    mode_map = {
        "dev": Color.wrap("开发模式", Color.BLUE),
        "prod": Color.wrap("生产模式", Color.GREEN),
        "backend": Color.wrap("仅后端", Color.BLUE),
        "frontend": Color.wrap("仅前端", Color.GREEN),
        "skip_backend": Color.wrap("开发模式（跳过后端）", Color.BLUE),
    }
    lines = [
        "",
        "=" * 64,
        f"  {Color.BOLD}ERP 系统 — 统一启动管理器{Color.RESET}",
        "=" * 64,
        f"  启动时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"  Python版本: {sys.version.split()[0]}",
        f"  运行模式: {mode_map.get(mode, mode)}",
        "-" * 64,
        f"  FastAPI API:  {Color.wrap(f'http://127.0.0.1:{api_port}', Color.BLUE)}",
        f"  FastAPI 文档: {Color.wrap(f'http://127.0.0.1:{api_port}/api/docs', Color.BLUE)}",
        f"  Next.js Web:  {Color.wrap(f'http://127.0.0.1:{web_port}', Color.GREEN)}",
        f"  Next.js 登录: {Color.wrap(f'http://127.0.0.1:{web_port}/login', Color.GREEN)}",
        "-" * 64,
        f"  {Color.DIM}按 Ctrl+C 停止所有服务{Color.RESET}",
        "=" * 64 + "\n",
    ]
    print("\n".join(lines), flush=True)


# ==================== 健康检查 ====================

def check_health(url, timeout=30.0, interval=1.0):
    import urllib.request
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            urllib.request.urlopen(url, timeout=2)
            return True
        except Exception:
            time.sleep(interval)
    return False


# ==================== 主程序 ====================

def main():
    parser = argparse.ArgumentParser(description="ERP系统统一启动管理器")
    parser.add_argument("--prod", action="store_true", help="生产模式")
    parser.add_argument("--api-port", type=int, default=5002)
    parser.add_argument("--web-port", type=int, default=3000)
    parser.add_argument("--backend-only", action="store_true")
    parser.add_argument("--frontend-only", action="store_true")
    parser.add_argument("--skip-backend", action="store_true")
    parser.add_argument("--no-health", action="store_true")
    args = parser.parse_args()

    if args.backend_only:
        mode = "backend"
    elif args.frontend_only:
        mode = "frontend"
    elif args.skip_backend:
        mode = "skip_backend"
    else:
        mode = "prod" if args.prod else "dev"

    if not args.backend_only:
        if not FRONTEND_DIR.exists():
            print(Color.wrap(f"错误: 前端目录不存在: {FRONTEND_DIR}", Color.RED))
            sys.exit(1)

    print_banner(mode, args.api_port, args.web_port)

    api_name = Color.wrap("API", Color.BLUE)
    web_name = Color.wrap("WEB", Color.GREEN)
    shutdown_event = threading.Event()
    procs = []

    # ==================== 启动后端 ====================
    if not args.frontend_only and not args.skip_backend:
        log_info(api_name, Color.BLUE, "正在启动 FastAPI 服务器...")
        cmd = [
            sys.executable, "-u", "-m", "uvicorn",
            "fastapi_app.main:app",
            "--host", "0.0.0.0",
            "--port", str(args.api_port),
            "--log-level", "info",
        ]
        if mode == "dev":
            cmd.extend(["--reload", "--reload-dir", "fastapi_app"])

        proc = subprocess.Popen(
            cmd,
            cwd=str(PROJECT_ROOT),
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if sys.platform == 'win32' else 0,
        )
        procs.append(proc)
        log_info(api_name, Color.BLUE, f"PID: {proc.pid}")

        if not args.no_health:
            health_url = f"http://127.0.0.1:{args.api_port}/api/health"
            log_info(api_name, Color.BLUE, f"等待后端就绪: {health_url}")
            if check_health(health_url, timeout=30):
                log_success(api_name, "后端已就绪")
            else:
                log_error(api_name, "后端启动超时")

    elif args.skip_backend:
        log_warn(api_name, "跳过后端启动（假设已运行）")

    # ==================== 启动前端 ====================
    if not args.backend_only:
        if not FRONTEND_DIR.exists():
            log_warn(web_name, "前端目录不存在，跳过")
        else:
            log_info(web_name, Color.GREEN, f"正在启动 Next.js ({mode})...")
            if sys.platform == 'win32':
                cmd = ["npm.cmd", "run", "dev"] if mode != "prod" else ["npm.cmd", "start"]
            else:
                cmd = ["npm", "run", "dev"] if mode != "prod" else ["npm", "start"]
            cmd.extend(["--", "-p", str(args.web_port)])

            proc = subprocess.Popen(
                cmd,
                cwd=str(FRONTEND_DIR),
                env={**os.environ, "BACKEND_INTERNAL_URL": f"http://127.0.0.1:{args.api_port}"},
                creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if sys.platform == 'win32' else 0,
            )
            procs.append(proc)
            log_info(web_name, Color.GREEN, f"PID: {proc.pid}")

            if not args.no_health:
                log_info(web_name, Color.GREEN, f"等待前端就绪: http://127.0.0.1:{args.web_port}/")
                if check_health(f"http://127.0.0.1:{args.web_port}/", timeout=60):
                    log_success(web_name, "前端已就绪")
                else:
                    log_warn(web_name, "前端启动超时（首次编译可能较慢）")

    # ==================== 关闭函数 ====================
    def shutdown_all():
        if shutdown_event.is_set():
            return
        shutdown_event.set()
        print(Color.wrap("\n" + "=" * 64, Color.DIM), flush=True)
        log_info(Color.wrap("SYS", Color.DIM), Color.DIM, "正在关闭所有服务...")

        # 先停前端（依赖后端），再停后端
        for proc in reversed(procs):
            try:
                if proc.poll() is None:
                    log_info(Color.wrap("SYS", Color.DIM), Color.DIM, f"停止进程 {proc.pid}...")
                    _stop_process(proc)
                    log_success(Color.wrap("SYS", Color.DIM), f"进程 {proc.pid} 已停止")
                else:
                    log_info(Color.wrap("SYS", Color.DIM), Color.DIM, f"进程 {proc.pid} 已退出")
            except Exception as e:
                log_warn(Color.wrap("SYS", Color.DIM), f"停止进程 {proc.pid} 时出错: {e}")

        log_success(Color.wrap("SYS", Color.DIM), "所有服务已停止")
        print(Color.wrap("=" * 64 + "\n", Color.DIM), flush=True)

    def _stop_process(proc):
        """终止单个进程（Windows: 使用 taskkill /T 终止进程树）"""
        if proc.poll() is not None:
            return True
        if sys.platform == 'win32':
            # Windows: 使用 taskkill /T 终止整个进程树
            try:
                result = subprocess.run(
                    ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                    capture_output=True, timeout=10
                )
                if result.returncode == 0:
                    proc.wait(timeout=5)
                    return True
            except Exception:
                pass
            try:
                proc.kill()
                proc.wait(timeout=2)
                return True
            except Exception:
                return False
        else:
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
                proc.wait(timeout=5)
                return True
            except Exception:
                try:
                    proc.kill()
                    proc.wait(timeout=2)
                    return True
                except Exception:
                    return False

    # ==================== 信号处理 ====================
    def signal_handler(signum, frame):
        log_info(Color.wrap("SYS", Color.DIM), Color.DIM, "收到停止信号")
        shutdown_all()

    signal.signal(signal.SIGINT, signal_handler)
    if sys.platform != 'win32':
        signal.signal(signal.SIGTERM, signal_handler)

    # ==================== 监控 ====================
    def monitor():
        while not shutdown_event.is_set():
            alive = any(p.poll() is None for p in procs)
            if not alive and procs:
                log_warn(Color.wrap("SYS", Color.DIM), "所有子进程已退出")
                shutdown_all()
                break
            time.sleep(2)

    threading.Thread(target=monitor, daemon=True).start()

    # ==================== 等待 ====================
    log_info(Color.wrap("SYS", Color.DIM), Color.DIM, "服务运行中，按 Ctrl+C 停止...")
    try:
        while not shutdown_event.is_set():
            shutdown_event.wait(1)
    except KeyboardInterrupt:
        log_info(Color.wrap("SYS", Color.DIM), Color.DIM, "收到 KeyboardInterrupt")
        shutdown_all()

    # 确保所有子进程已终止
    for proc in procs:
        if proc.poll() is None:
            try:
                proc.kill()
                proc.wait(timeout=2)
            except Exception:
                pass

    log_info(Color.wrap("SYS", Color.DIM), Color.DIM, "启动管理器已退出")
    sys.exit(0)


if __name__ == '__main__':
    main()
