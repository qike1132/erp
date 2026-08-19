"""
ERP 生产模式监督器 (Windows 原生)。

统一生产入口：`start.py --prod` 最终调用本模块。
职责：
  1. 拉起并守护多 worker Uvicorn（默认 UVICORN_WORKERS=4，可 .env / 环境变量覆盖）
  2. 拉起并守护 ARQ worker（fastapi_app.core.arq_app.WorkerSettings，含内建 cron）
  3. 前端托管：优先 Nginx（config/nginx-windows.conf），缺失时回退 vite preview
  4. Redis：仅检查连通（生产建议将 Redis 注册为独立 Windows 服务）
  5. 子进程崩溃自动重启（指数退避 2s→30s，防崩溃风暴）；
     对后端按 /api/health 做健康判定，主进程存活但 worker 崩溃循环时强制重启整棵进程树
  6. 状态落盘 logs/prod_runner.json，供 server_manager GUI 展示
  7. 子进程 stdout/stderr 落盘 logs/<name>.out.log，便于排障

用法:
  python -m fastapi_app.core.prod_runner --check       # 环境自检（不拉起进程）
  python -m fastapi_app.core.prod_runner --no-arq       # 不托管 ARQ（配合独立 erp-arq 服务使用）
  python -m fastapi_app.core.prod_runner               # 前台运行（Ctrl+C 优雅关闭）
"""
from __future__ import annotations

import contextlib
import io
import json
import os
import shutil
import socket
import subprocess  # nosec B404
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
LOGS_DIR = PROJECT_ROOT / "logs"
STATUS_FILE = LOGS_DIR / "prod_runner.json"
FRONTEND_DIR = PROJECT_ROOT / "frontend-vite"
DIST_DIR = FRONTEND_DIR / "dist"
NGINX_CONF = PROJECT_ROOT / "config" / "nginx-windows.conf"

# 常见 nginx for Windows 安装位置（PATH 之外）
_NGINX_CANDIDATES = [
    Path(r"C:\nginx\nginx.exe"),
    Path(r"C:\Program Files\nginx\nginx.exe"),
    Path(r"C:\tools\nginx\nginx.exe"),
]

_PY = sys.executable
_CREATE_NO_WINDOW = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0


def _load_dotenv() -> None:
    try:
        from dotenv import load_dotenv
        load_dotenv(PROJECT_ROOT / ".env", override=False)
    except ImportError:
        pass  # defensive: 可选依赖未安装,优雅降级


def _get_int_env(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


def _default_workers() -> int:
    configured = _get_int_env("UVICORN_WORKERS", 0)
    if configured > 0:
        return configured
    return max(1, min(4, os.cpu_count() or 1))


def _find_nginx() -> Path | None:
    found = shutil.which("nginx")
    if found:
        return Path(found)
    for cand in _NGINX_CANDIDATES:
        if cand.is_file():
            return cand
    return None


def _is_redis_up(port: int) -> bool:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.settimeout(1)
            return sock.connect_ex(("127.0.0.1", port)) == 0
    except OSError:
        return False


def _http_ok(url: str, timeout: float = 2.0) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:  # nosec B310
            return resp.status == 200
    except (urllib.error.URLError, OSError, TimeoutError):
        return False


def _iso_now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _cmd_uvicorn(api_port: int, workers: int) -> list[str]:
    return [
        _PY, "-m", "uvicorn", "fastapi_app.main:app",
        "--host", "0.0.0.0",  # nosec B104
        "--port", str(api_port),
        "--workers", str(workers),
        "--http", "httptools",
        "--proxy-headers",
        "--forwarded-allow-ips=*",
        "--no-access-log",
        "--timeout-keep-alive", "5",
    ]


def _cmd_arq() -> list[str]:
    return [_PY, "-m", "arq", "fastapi_app.core.arq_app.WorkerSettings"]


def _cmd_vite_preview(web_port: int) -> list[str]:
    npx = "npx.cmd" if os.name == "nt" else "npx"
    return [npx, "vite", "preview", "--port", str(web_port), "--host", "0.0.0.0"]  # nosec B104


# ---------------------------------------------------------------------------
# 环境自检（不拉起进程）
# ---------------------------------------------------------------------------
def check(api_port: int, workers: int) -> int:
    """校验监督器运行所需的环境，缺失项仅告警不失败。"""
    print("[prod_runner] 环境自检 (check)...")
    ok = True

    if not PROJECT_ROOT.is_dir() and not (PROJECT_ROOT / "fastapi_app").is_dir():
        print(f"  ERROR: 项目目录无效 {PROJECT_ROOT}")
        return 1

    redis_port = _get_int_env("REDIS_PORT", 6379)
    if _is_redis_up(redis_port):
        print(f"  OK: Redis 连通 (127.0.0.1:{redis_port})")
    else:
        print(f"  WARN: Redis 未运行 (127.0.0.1:{redis_port})，生产建议注册为 Windows 服务")

    if DIST_DIR.is_dir():
        print(f"  OK: 前端构建产物存在 {DIST_DIR}")
    else:
        print(f"  WARN: 前端构建产物缺失 {DIST_DIR}，请先执行 npm run build")
        ok = False

    nginx = _find_nginx()
    if nginx:
        print(f"  OK: 检测到 Nginx {nginx}")
    else:
        print("  INFO: 未检测到 Nginx，前端将回退 vite preview")

    print(f"  INFO: worker 数 = {workers} (UVICORN_WORKERS)")
    print(f"  INFO: API 端口 = {api_port}")
    return 0 if ok else 1


# ---------------------------------------------------------------------------
# 受监督子进程
# ---------------------------------------------------------------------------
class _Managed:
    """受监督的子进程。

    health_url 非空时为“健康型”服务（如后端按 /api/health 判定）：
    进程存活但健康检查持续失败 → 强制重启整棵进程树（应对 worker 崩溃循环）。
    否则为“进程型”服务，仅按进程存活判定。
    """

    def __init__(self, name: str, cmd: list[str], cwd: Path,
                 health_url: str | None = None, start_grace: float = 45.0):
        self.name = name
        self.cmd = cmd
        self.cwd = cwd
        self.health_url = health_url
        self.start_grace = start_grace
        self.proc: subprocess.Popen | None = None
        self._logf: io.BufferedWriter | None = None
        self.delay = 2.0
        self.next_start = 0.0
        self.status = "stopped"
        self.last_health: str | None = None
        self.started_at = 0.0
        self.health_fail_start: float | None = None

    def start(self) -> None:
        if self.proc and self.proc.poll() is None:
            return
        env = dict(os.environ)
        env.update({"PYTHONUNBUFFERED": "1", "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"})
        LOGS_DIR.mkdir(exist_ok=True)
        log_path = LOGS_DIR / f"{self.name}.out.log"
        try:
            self._logf = open(log_path, "ab")  # noqa: SIM115 需保持打开作为子进程 stdout
            self.proc = subprocess.Popen(  # nosec B603
                self.cmd, cwd=str(self.cwd), env=env,
                stdout=self._logf, stderr=subprocess.STDOUT,
                creationflags=_CREATE_NO_WINDOW,
            )
            self.started_at = time.monotonic()
            self.health_fail_start = None
            self.status = "running"
            self.delay = 2.0
            print(f"[prod_runner] {self.name} 已启动 (PID {self.proc.pid}, 日志 {log_path.name})")
        except (OSError, subprocess.SubprocessError) as e:
            self.status = "failed"
            print(f"[prod_runner] {self.name} 启动失败: {e}")

    def alive(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    def kill_tree(self) -> None:
        """终止整棵进程树（Windows taskkill /T；非 Windows 用进程组）。"""
        if not self.proc:
            return
        pid = self.proc.pid
        if os.name == "nt":
            subprocess.run(  # nosec B603 B607
                ["taskkill", "/F", "/T", "/PID", str(pid)],
                creationflags=_CREATE_NO_WINDOW,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=15,
            )
        else:
            import signal
            try:
                os.killpg(os.getpgid(pid), signal.SIGTERM)  # type: ignore[attr-defined]
            except (ProcessLookupError, OSError):
                self.proc.terminate()
        with contextlib.suppress(subprocess.TimeoutExpired):
            self.proc.wait(timeout=5)
        if self._logf:
            with contextlib.suppress(OSError):
                self._logf.close()
        self._logf = None
        self.proc = None

    def poll(self) -> None:
        """主循环每轮调用：进程退出或健康持续失败则安排退避重启。"""
        if self.proc is None:
            return
        if self.proc.poll() is not None:
            # 进程已退出
            self.status = "crashed"
            self.next_start = time.monotonic() + self.delay
            self.delay = min(self.delay * 2, 30.0)
            print(f"[prod_runner] {self.name} 已退出 (code={self.proc.returncode})，"
                  f"{int(self.delay)}s 后重启")
            return
        if not self.health_url:
            self.status = "running"
            return
        # 健康型服务
        if _http_ok(self.health_url):
            self.status = "ready"
            self.last_health = _iso_now()
            self.health_fail_start = None
            return
        if self.health_fail_start is None:
            self.health_fail_start = time.monotonic()
        # 启动期给足 start_grace 秒；启动超过后连续失败 20s 触发重启
        threshold = self.start_grace if time.monotonic() - self.started_at < self.start_grace else 20.0
        if time.monotonic() - self.health_fail_start > threshold:
            print(f"[prod_runner] {self.name} 健康检查持续失败，强制重启进程树")
            self.kill_tree()
            self.status = "crashed"
            self.next_start = time.monotonic() + self.delay
            self.delay = min(self.delay * 2, 30.0)
            self.health_fail_start = None

    def maybe_restart(self) -> None:
        if self.status == "crashed" and self.next_start <= time.monotonic():
            self.start()


class _FrontendNginx:
    """Nginx 前端托管：nginx 为独立守护进程，按端口存活情况重启。"""

    def __init__(self, nginx: Path, web_port: int):
        self.nginx = nginx
        self.web_port = web_port
        self.delay = 5.0
        self.next_start = 0.0
        self.status = "stopped"

    def _kill_all(self) -> None:
        """彻底停止本项目所有 nginx 进程（仅 Windows 逻辑）。

        Windows 下 `nginx -s stop` 只停最新 master，且杀 master 不会连带结束
        worker，会在重启循环中泄漏孤儿进程（worker 的父进程已消失仍存活），
        导致端口与连接混乱、进程数爆炸。因此先优雅停 master，再按镜像名
        强制结束所有 nginx.exe（含孤儿 worker），确保干净重启。
        """
        subprocess.run(  # nosec B603
            [str(self.nginx), "-s", "stop"],
            creationflags=_CREATE_NO_WINDOW,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=15,
        )
        if os.name == "nt":
            subprocess.run(  # nosec B603 B607
                ["taskkill", "/F", "/T", "/IM", "nginx.exe"],
                creationflags=_CREATE_NO_WINDOW,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=15,
            )

    def _ensure_started(self) -> None:
        # 启动前先彻底清理历史遗留的 nginx 进程（含孤儿 worker）。
        # 否则端口 3000 被旧 master 占用，新 master 无法绑定。
        self._kill_all()
        LOGS_DIR.mkdir(exist_ok=True)
        # Windows 上 nginx.exe 本身就是 master 进程，启动后不会退出返回，
        # 绝不能用 subprocess.run（会阻塞到 timeout 抛 TimeoutExpired，拖垮
        # prod_runner 主流程，导致 NSSM 反复重启监督器、nginx 被周期性
        # kill/重建，全站连接每 ~35 秒被切断一次，前端所有请求 502 重试）。
        # 改用 Popen 派生后立即返回，再通过 /nginx-health 探测确认就绪。
        subprocess.Popen(  # nosec B603
            [str(self.nginx), "-p", str(PROJECT_ROOT), "-c", str(NGINX_CONF),
             "-e", str(LOGS_DIR / "nginx-error.log")],
            cwd=str(PROJECT_ROOT), creationflags=_CREATE_NO_WINDOW,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        for _ in range(10):
            if self.alive():
                break
            time.sleep(0.5)
        self.status = "running"
        self.delay = 5.0
        print(f"[prod_runner] 前端 Nginx 已启动 (port {self.web_port})")

    def alive(self) -> bool:
        return _http_ok(f"http://127.0.0.1:{self.web_port}/nginx-health", timeout=1.5)

    def poll(self) -> None:
        if self.alive():
            self.status = "running"
            return
        if self.status != "crashed":
            self.status = "crashed"
            self.next_start = time.monotonic() + self.delay
            self.delay = min(self.delay * 2, 30.0)
            print(f"[prod_runner] 前端 Nginx 不可达，{int(self.delay)}s 后重启")

    def maybe_restart(self) -> None:
        if self.status == "crashed" and self.next_start <= time.monotonic():
            self._ensure_started()  # _ensure_started 内部已先 _kill_all()

    def stop(self) -> None:
        self._kill_all()


class Supervisor:
    def __init__(self, workers: int, api_port: int, web_port: int, with_arq: bool = True):
        self.workers = workers
        self.api_port = api_port
        self.web_port = web_port
        self.with_arq = with_arq
        self.redis_port = _get_int_env("REDIS_PORT", 6379)
        self.ready = False

        self.backend = _Managed(
            "后端(uvicorn)", _cmd_uvicorn(api_port, workers), PROJECT_ROOT,
            health_url=f"http://127.0.0.1:{api_port}/api/health",
        )
        self.arq = _Managed("ARQ worker", _cmd_arq(), PROJECT_ROOT) if with_arq else None

        nginx = _find_nginx()
        self.nginx = _FrontendNginx(nginx, web_port) if nginx else None
        self.vite: _Managed | None = None
        if nginx:
            self.frontend_type = "nginx"
        else:
            self.frontend_type = "vite"
            self.vite = _Managed(
                "前端(vite preview)", _cmd_vite_preview(web_port), FRONTEND_DIR,
                health_url=f"http://127.0.0.1:{web_port}/",
            )

    # -- 启动序列 -----------------------------------------------------------
    def start_all(self) -> None:
        LOGS_DIR.mkdir(exist_ok=True)
        print(f"[prod_runner] 启动生产模式 (workers={self.workers}, "
              f"api={self.api_port}, web={self.web_port}, frontend={self.frontend_type}"
              f"{', arq=独立服务' if not self.with_arq else ''})")
        self.backend.start()
        if self.arq:
            self.arq.start()
        if self.nginx:
            self.nginx._ensure_started()
        elif self.vite:
            self.vite.start()

    # -- 状态落盘 -----------------------------------------------------------
    def write_status(self) -> None:
        redis_status = "ok" if _is_redis_up(self.redis_port) else "down"
        self.ready = self.backend.status == "ready"
        data = {
            "pid": os.getpid(),
            "started_at": _iso_now(),
            "mode": "production",
            "ready": self.ready,
            "workers": self.workers,
            "api_port": self.api_port,
            "web_port": self.web_port,
            "frontend_type": self.frontend_type,
            "services": {
                "backend": {
                    "pid": self.backend.proc.pid if self.backend.proc else None,
                    "status": self.backend.status,
                    "last_health": self.backend.last_health,
                },
                "arq": {
                    "pid": self.arq.proc.pid if self.arq and self.arq.proc else None,
                    "status": self.arq.status if self.arq else "external",
                },
                "frontend": {
                    "type": self.frontend_type,
                    "pid": (self.vite.proc.pid if self.vite and self.vite.proc else None),
                    "status": (self.nginx.status if self.nginx else
                               self.vite.status if self.vite else "stopped"),
                },
                "redis": {"status": redis_status},
            },
        }
        try:
            tmp = STATUS_FILE.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2),
                           encoding="utf-8")
            os.replace(tmp, STATUS_FILE)  # 原子替换，GUI 永远不会读到半写文件
        except OSError as e:
            print(f"[prod_runner] 状态写入失败: {e}")

    # -- 主循环 -------------------------------------------------------------
    def run(self) -> None:
        self.start_all()
        print("[prod_runner] 进入守护循环（健康门：后端 /api/health 就绪后标记 ready）")
        while True:
            try:
                self.backend.poll()
                if self.arq:
                    self.arq.poll()
                if self.vite:
                    self.vite.poll()
                if self.nginx:
                    self.nginx.poll()
                self.backend.maybe_restart()
                if self.arq:
                    self.arq.maybe_restart()
                if self.vite:
                    self.vite.maybe_restart()
                if self.nginx:
                    self.nginx.maybe_restart()
                if not self.ready and self.backend.status == "ready":
                    print("[prod_runner] 后端就绪 (/api/health 200)")
                self.write_status()
            except Exception as e:  # defensive: supervisor main loop must not exit
                print(f"[prod_runner] 主循环异常（已吞掉，不退出）: {type(e).__name__}: {e}")
            time.sleep(3)

    # -- 优雅关闭 -----------------------------------------------------------
    def shutdown(self) -> None:
        print("[prod_runner] 正在关闭...")
        if self.nginx:
            self.nginx.stop()
        for svc in (self.arq, self.vite, self.backend):
            if svc:
                svc.kill_tree()
        print("[prod_runner] 已停止")


def _install_signal_handlers(sup: Supervisor) -> None:
    if os.name == "nt":
        try:
            import ctypes

            def _win_handler(ctrl_type):
                # CTRL_C_EVENT=0, CTRL_BREAK_EVENT=1, CTRL_CLOSE_EVENT=2,
                # CTRL_LOGOFF_EVENT=5, CTRL_SHUTDOWN_EVENT=6
                sup.shutdown()
                return True  # 阻止默认终止，让 shutdown 完成

            HANDLER_ROUTINE = ctypes.WINFUNCTYPE(ctypes.c_int, ctypes.c_uint)
            _handler_ref = HANDLER_ROUTINE(_win_handler)  # 防止 GC 回收
            ctypes.windll.kernel32.SetConsoleCtrlHandler(_handler_ref, True)
        except (OSError, AttributeError):
            pass  # defensive: 异常静默处理,不影响主流程
    else:
        import signal

        def _posix_handler(*_a):
            sup.shutdown()
            sys.exit(0)

        signal.signal(signal.SIGTERM, _posix_handler)
        signal.signal(signal.SIGINT, _posix_handler)


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    _load_dotenv()

    api_port = _get_int_env("API_PORT", 5002)
    web_port = _get_int_env("WEB_PORT", 3000)
    workers = _default_workers()

    if "--check" in argv:
        return check(api_port, workers)

    with_arq = "--no-arq" not in argv
    sup = Supervisor(workers, api_port, web_port, with_arq=with_arq)
    _install_signal_handlers(sup)
    try:
        sup.run()
    except KeyboardInterrupt:
        sup.shutdown()
    return 0


if __name__ == "__main__":
    sys.exit(main())
