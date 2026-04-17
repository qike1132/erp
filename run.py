"""
ERP系统启动脚本 (修复版 - 热重载稳定性增强)

架构说明（单一重载器）：
  - Flask (端口5003): 主进程，唯一热重载器（Werkzeug stat reloader）
  - FastAPI/uvicorn (端口5002): 子进程，不启用 uvicorn --reload
  - 所有后端代码改动统一由 Flask reloader 触发重启，避免双重重载冲突

关键设计：
  1. Windows 上使用 CREATE_NO_WINDOW + 输出重定向让 uvicorn 在后台运行
     → 避免 uvicorn 创建额外的控制台窗口，实现单窗口启动
  2. FastAPI 关闭 --reload，避免与 Flask reloader 叠加
  3. Flask 通过 extra_files 显式监控 fastapi_app/*.py
     → FastAPI 代码改动同样触发统一重载
  4. FastAPI 日志通过 --log-config 写入文件，不依赖 stdout/stderr
  4. atexit 和信号处理器确保干净退出
"""
import os
import sys

# Windows UTF-8 输出：防止中文在管道/重定向场景下产生 GBK 乱码
if sys.platform == 'win32':
    import io
    if sys.stdout and hasattr(sys.stdout, 'buffer'):
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    if sys.stderr and hasattr(sys.stderr, 'buffer'):
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

# ============================================================
# 虚拟环境自动检测：若当前 Python 不在 .venv313 内，则用 .venv313 重启
# ============================================================
_VENV_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), '.venv313')
_VENV_PYTHON = os.path.join(_VENV_DIR, 'Scripts', 'python.exe')
if sys.platform != 'win32':
    _VENV_PYTHON = os.path.join(_VENV_DIR, 'bin', 'python')

if os.path.isfile(_VENV_PYTHON) and os.path.normpath(sys.executable) != os.path.normpath(_VENV_PYTHON):
    # 保留原始命令行参数，重新以 .venv313 的 Python 启动本脚本
    os.execv(_VENV_PYTHON, [_VENV_PYTHON] + sys.argv)
import threading
import subprocess
import atexit
import time
import signal
import logging
from importlib.metadata import version as _pkg_version, PackageNotFoundError

# 在启动任何子进程之前加载 .env，确保 FastAPI 子进程继承到 DB_PASSWORD 等变量
from dotenv import load_dotenv
load_dotenv(override=False)

# ============================================================
# 全局状态与日志
# ============================================================
_fastapi_proc = None
_fastapi_monitor_running = False
_logger = logging.getLogger(__name__)
_PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))


def _single_reloader_enabled() -> bool:
    """是否启用单一重载器架构（默认启用）。"""
    return os.getenv("SINGLE_RELOADER_MODE", "1").lower() in ("1", "true", "yes")


def _should_manage_fastapi_in_this_process() -> bool:
    """仅在 Werkzeug worker 进程中管理 FastAPI 子进程。"""
    run_main = os.environ.get("WERKZEUG_RUN_MAIN")
    return run_main == "true"


def _collect_fastapi_reload_files():
    """收集 Flask reloader 需额外监控的 FastAPI 源文件。"""
    fastapi_root = os.path.join(_PROJECT_ROOT, "fastapi_app")
    watched_files = []
    if not os.path.isdir(fastapi_root):
        return watched_files

    for root, dirs, files in os.walk(fastapi_root):
        # 排除缓存目录，减少无意义重载
        dirs[:] = [d for d in dirs if d != "__pycache__"]
        for filename in files:
            if filename.endswith(".py"):
                watched_files.append(os.path.join(root, filename))
    return watched_files


def _check_reload_dependency_versions():
    """启动前检查热重载关键依赖版本，提前暴露不兼容组合。"""
    try:
        uvicorn_ver = _pkg_version("uvicorn")
        watchfiles_ver = _pkg_version("watchfiles")
        print(f"[INFO] 热重载依赖版本: uvicorn={uvicorn_ver}, watchfiles={watchfiles_ver}")
    except PackageNotFoundError as e:
        print(f"[WARN] 热重载依赖缺失: {e}. 建议执行: pip install \"uvicorn[standard]\" watchfiles")


def _kill_port_5002():
    """强制释放端口 5002 上的残留进程，防止 WinError 10013 端口冲突"""
    try:
        result = subprocess.run(
            ['netstat', '-ano'],
            capture_output=True, text=True, timeout=5,
            encoding='gbk', errors='replace'
        )
        for line in result.stdout.splitlines():
            if ':5002' in line and 'LISTEN' in line:
                parts = line.strip().split()
                pid = parts[-1]
                if pid.isdigit() and int(pid) != os.getpid():
                    subprocess.run(['taskkill', '/F', '/T', '/PID', pid],
                                   capture_output=True, timeout=5)
                    print(f"[INFO] 已清理端口 5002 残留进程 (PID: {pid})")
    except Exception:
        pass


def _start_fastapi():
    """在后台启动 FastAPI 服务"""
    global _fastapi_proc
    log_dir = os.path.join(_PROJECT_ROOT, 'logs')
    os.makedirs(log_dir, exist_ok=True)

    try:
        # 先清理端口残留进程
        _kill_port_5002()

        fastapi_debug = (
            os.getenv('FASTAPI_DEBUG', 'true').lower() in ('true', '1', 'yes')
            and not _single_reloader_enabled()
        )
        uvicorn_args = [
            sys.executable, '-m', 'uvicorn',
            'fastapi_app.main:app',
            '--host', '0.0.0.0',
            '--port', '5002',
        ]
        if fastapi_debug:
            reload_dir = os.path.join(_PROJECT_ROOT, 'fastapi_app')
            uvicorn_args.extend([
                '--reload',
                '--reload-dir', reload_dir,
                # 仅监控 Python 源文件，避免日志/缓存等噪音触发重载风暴
                '--reload-include', '*.py',
                # 明确排除非 FastAPI 代码目录（兼容部分版本在 Windows 下 reload-dir 过宽的问题）
                '--reload-exclude', '.git/*',
                '--reload-exclude', '.archive/*',
                '--reload-exclude', '.agents/*',
                '--reload-exclude', '.trae/*',
                '--reload-exclude', 'tests/*',
                '--reload-exclude', 'scripts/*',
                '--reload-exclude', 'logs/*',
                '--reload-exclude', 'app/*',
                '--reload-exclude', 'migrations/*',
            ])

        # uvicorn 日志通过 --log-config 写入文件，不再重定向 stdout/stderr
        # 这样 uvicorn reloader 可以正常 spawn 新 worker 进程
        log_config_path = os.path.join(_PROJECT_ROOT, 'fastapi_app', 'log_config.json')
        if os.path.exists(log_config_path):
            uvicorn_args.extend(['--log-config', log_config_path])

        print(f"[INFO] 正在启动 FastAPI 服务 (端口 5002, 热重载: {fastapi_debug})...")

        # 修复：使用 CREATE_NO_WINDOW + 重定向输出，彻底避免弹出额外的控制台窗口
        # Windows 上 FastAPI 在后台运行，日志通过 --log-config 写入文件
        # 必须重定向 stdout/stderr 到 DEVNULL，避免子进程继承控制台句柄导致窗口弹出
        popen_kwargs = {}
        if sys.platform == 'win32':
            popen_kwargs['creationflags'] = subprocess.CREATE_NO_WINDOW
            popen_kwargs['stdout'] = subprocess.DEVNULL
            popen_kwargs['stderr'] = subprocess.DEVNULL
        else:
            popen_kwargs['stdout'] = subprocess.DEVNULL
            popen_kwargs['stderr'] = subprocess.DEVNULL

        # Windows + watchfiles 在部分环境下需要强制轮询，避免漏检/误检导致的异常退出
        # 仅在启用 uvicorn reload 时需要
        child_env = os.environ.copy()
        if sys.platform == 'win32' and fastapi_debug:
            child_env.setdefault('WATCHFILES_FORCE_POLLING', 'true')

        _fastapi_proc = subprocess.Popen(
            uvicorn_args,
            env=child_env,
            **popen_kwargs,
        )
        print(f"[OK] FastAPI 服务已启动 (PID: {_fastapi_proc.pid})，日志: logs/fastapi.log")
    except Exception as e:
        print(f"[ERROR] FastAPI 服务启动失败: {e}")
        import traceback
        traceback.print_exc()


def _stop_fastapi():
    """停止 FastAPI 子进程（含其整个进程树）

    Windows 上 subprocess.Popen.terminate() 仅终止父进程，
    uvicorn reloader 的 worker 子进程会残留并占用端口 5002。
    使用 taskkill /T /F 可终止整个进程树。
    """
    global _fastapi_proc
    if _fastapi_proc and _fastapi_proc.poll() is None:
        pid = _fastapi_proc.pid
        try:
            # Windows: /T 终止进程树, /F 强制终止
            subprocess.run(['taskkill', '/F', '/T', '/PID', str(pid)],
                           capture_output=True, timeout=5)
            print(f"[INFO] FastAPI 进程 (PID: {pid}) 已停止")
        except Exception:
            try:
                _fastapi_proc.terminate()
                _fastapi_proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                _fastapi_proc.kill()
        _fastapi_proc = None


def _monitor_fastapi():
    """后台监控 FastAPI 进程，如果崩溃则自动重启"""
    global _fastapi_proc, _fastapi_monitor_running
    _fastapi_monitor_running = True
    consecutive_failures = 0
    max_consecutive_failures = 5

    while _fastapi_monitor_running:
        time.sleep(5)  # 每 5 秒检查一次

        if _fastapi_proc is None:
            continue

        poll = _fastapi_proc.poll()
        if poll is not None:
            consecutive_failures += 1
            if consecutive_failures >= max_consecutive_failures:
                print(f"[ERROR] FastAPI 连续崩溃 {consecutive_failures} 次，停止自动重启。请手动检查日志。")
                _fastapi_monitor_running = False
                break
            print(f"[WARN] FastAPI 进程 (PID: {_fastapi_proc.pid}) 已退出 (返回码: {poll})，正在重启 (第 {consecutive_failures} 次)...")
            _fastapi_proc = None
            time.sleep(3)
            try:
                _start_fastapi()
            except Exception as e:
                print(f"[ERROR] FastAPI 重启失败: {e}")
        else:
            consecutive_failures = 0


if _should_manage_fastapi_in_this_process():
    print("=" * 60)
    print("ERP系统启动中...")
    print("=" * 60)

    # 单一重载器模式下由 Flask 统一拉起/重启，不启用 FastAPI 崩溃自动重启线程，避免重启竞态
    if not _single_reloader_enabled():
        _monitor_thread = threading.Thread(target=_monitor_fastapi, daemon=True)
        _monitor_thread.start()

    _check_reload_dependency_versions()

    # 启动 FastAPI 服务
    _start_fastapi()

    # 注册退出钩子
    atexit.register(_stop_fastapi)

    # 注册信号处理器
    def _signal_handler(signum, frame):
        print(f"\n[INFO] 收到信号 {signum}，正在关闭服务...")
        _stop_fastapi()
        global _fastapi_monitor_running
        _fastapi_monitor_running = False
        sys.exit(0)

    try:
        signal.signal(signal.SIGINT, _signal_handler)
        signal.signal(signal.SIGTERM, _signal_handler)
    except (ValueError, OSError):
        pass

    # 等待 FastAPI 启动
    time.sleep(2)
    print("[OK] 系统初始化完成")

# ============================================================
# Flask 应用导入与配置
# ============================================================
from app import app, db

if __name__ == '__main__':
    app.debug = True
    app.config['TEMPLATES_AUTO_RELOAD'] = True
    app.config['SEND_FILE_MAX_AGE_DEFAULT'] = 0

    db_uri = app.config.get('SQLALCHEMY_DATABASE_URI', '')
    # 仅显示主机部分，避免泄露密码
    db_host = db_uri.split('@')[-1] if db_uri and '@' in db_uri else '未配置'
    print(f"数据库: {db_host}")
    print(f"密钥状态: {'已设置' if app.secret_key else '未设置'}")
    print(f"调试模式: {app.debug}")
    print(f"模板自动重载: {app.config['TEMPLATES_AUTO_RELOAD']}")
    print("=" * 60)
    print("Flask 访问地址: http://127.0.0.1:5003")
    print("Flask 访问地址: http://192.168.0.95:5003")
    print("FastAPI 访问地址: http://127.0.0.1:5002")
    print("=" * 60)

    # Flask reloader 配置
    # 使用 stat reloader + exclude_patterns
    # stat reloader 的 exclude_patterns 通过 fnmatch 对完整文件路径过滤
    # 而 watchdog 的 ignore_patterns 只对文件名生效，无法排除目录
    reloader_type = 'stat'
    flask_exclude_patterns = [
        '*\\logs\\*',
        '*/logs/*',
        '*.git*',
        '*\\scripts\\*',
        '*/scripts/*',
    ]
    flask_extra_files = _collect_fastapi_reload_files()

    print(f"[INFO] 热重载监控器类型: {reloader_type}")
    print(f"[INFO] Flask 排除监控路径: {len(flask_exclude_patterns)} 个模式")
    print(f"[INFO] Flask 额外监控 FastAPI 文件: {len(flask_extra_files)} 个")

    try:
        app.run(
            debug=True,
            host='0.0.0.0',
            port=5003,
            use_reloader=True,
            reloader_type=reloader_type,
            exclude_patterns=flask_exclude_patterns,
            extra_files=flask_extra_files,
        )
    except OSError as e:
        if 'Address already in use' in str(e) or '10048' in str(e):
            print(f"\n[ERROR] 端口 5003 已被占用，请关闭其他进程后重试")
            print(f"[INFO] 你可以运行: netstat -ano | findstr :5003")
        else:
            print(f"\n[ERROR] 启动失败: {e}")
            import traceback
            traceback.print_exc()
    except Exception as e:
        print(f"\n[ERROR] 启动失败: {e}")
        import traceback
        traceback.print_exc()
    finally:
        _stop_fastapi()
        _fastapi_monitor_running = False
