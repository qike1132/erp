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
  8. 日志轮转：子进程 .out.log 与 Nginx access/error 日志超过阈值
     （默认 50MB，PROD_LOG_ROTATE_MB 可调）时 copytruncate 轮转，保留一代 .1 副本，
     防止长期运行后磁盘被日志占满

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

# 日志轮转：检查间隔与阈值。NSSM 只轮转监督器自身的 stdout（logs/erp-*.log），
# 子进程 .out.log 与 Nginx access/error 日志由本模块负责轮转。
LOG_ROTATE_CHECK_INTERVAL = 60.0


def _log_rotate_bytes() -> int:
    """轮转阈值（字节），默认 50MB，PROD_LOG_ROTATE_MB 覆盖，下限 5MB。"""
    return max(5, _get_int_env("PROD_LOG_ROTATE_MB", 50)) * 1024 * 1024


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


# 健康探针必须直连本机，绝不走系统代理。
# 根因(2026-09-10 实证): 本机设置了 HTTP_PROXY/HTTPS_PROXY=127.0.0.1:<port>(代理客户端)
# 且无 NO_PROXY，urllib 默认会读取系统代理——包括 Windows 注册表代理设置——导致
# 探测 127.0.0.1:5002 的 /api/health 被路由进代理。代理客户端抖动时健康检查间歇性
# 失败，触发下方「连续失败 20s → 强制重启」逻辑，形成后端重启风暴
# (应用本身完全正常：被杀前最后一条日志距关停 0 秒、均为正常业务请求)。
# ProxyHandler({}) 显式清空代理，保证探针永远直连。
_OPENER_DIRECT = urllib.request.build_opener(urllib.request.ProxyHandler({}))

# 健康检查失败原因留痕的节流间隔。此前 _http_ok 静默吞掉异常，排障时完全看不出
# 失败原因（本次就是靠排除法才定位到代理），必须留痕。
_HEALTH_FAIL_LOG_INTERVAL = 60.0
_last_health_fail_log = 0.0


def _log_health_fail(err: BaseException) -> None:
    """健康检查失败原因留痕（60s 节流，避免刷屏）。"""
    global _last_health_fail_log
    now = time.monotonic()
    if now - _last_health_fail_log < _HEALTH_FAIL_LOG_INTERVAL:
        return
    _last_health_fail_log = now
    print(f"[prod_runner] 健康检查失败(60s 内不重复记录): {type(err).__name__}: {err}")


def _http_ok(url: str, timeout: float = 5.0, expect_substr: str | None = None) -> bool:
    """探测 url 是否可用。

    expect_substr 非空时额外要求响应体包含该子串。用于区分「目标服务就绪」与
    「同端口上的其它服务返回了 200」——典型如 :3000 上 nginx 缺席时由 Vite dev
    server 以 SPA fallback 对任意路径直出 200 + index.html，仅比较状态码会误判。
    既有调用方（后端/ARQ 探针）不传该参数，行为与修复前完全一致。
    """
    try:
        with _OPENER_DIRECT.open(url, timeout=timeout) as resp:  # nosec B310
            if resp.status != 200:
                return False
            if expect_substr is None:
                return True
            # 只读有界前缀（探针目标响应都很小），避免万一命中大体积 body 时的内存放大
            body = resp.read(8192).decode("utf-8", errors="replace")
            return expect_substr in body
    except (urllib.error.URLError, OSError, TimeoutError) as e:
        _log_health_fail(e)
        return False


def _iso_now() -> str:
    return datetime.now().isoformat(timespec="seconds")


# ---------------------------------------------------------------------------
# 健康型进程的强制重启判定（D7）
# ---------------------------------------------------------------------------
# 旧逻辑：健康检查持续失败即无条件 kill_tree()，把「探针偶发超时（进程其实健在）」
# 与「进程真的死了」混为一谈，造成大量误杀。新逻辑要求「连续失败 + 失败窗口 + 进程
# 确已死亡」三者同时成立才重启；进程存活时只告警 + 放宽退避，绝不误杀进程树。
_RESTART_MIN_CONSECUTIVE = 3
_RESTART_MIN_WINDOW_S = 90.0

# 退避上限阶梯：反复失败/重启时上限依次抬升（30 → 60 → 120 → 300，封顶），
# 替代原先写死的 min(delay*2, 30.0)，避免崩溃风暴期间过于频繁的重启。
_BACKOFF_CAPS = (30.0, 60.0, 120.0, 300.0)


def _next_backoff(current_delay: float, step: int) -> float:
    """下一次退避时长：在当前基础上翻倍，上限随重试阶梯抬升（阶梯封顶）。"""
    cap = _BACKOFF_CAPS[min(max(step, 0), len(_BACKOFF_CAPS) - 1)]
    return min(current_delay * 2.0, cap)


def _should_restart(consecutive_failures: int, fail_window_s: float, proc_alive: bool) -> bool:
    """健康检查持续失败时，是否应强制重启整棵进程树（纯函数，便于断言）。

    仅当「连续失败 ≥ _RESTART_MIN_CONSECUTIVE 次」且「失败窗口 ≥ _RESTART_MIN_WINDOW_S 秒」
    且「进程确已死亡（proc_alive is False）」三者同时成立才返回 True。进程仍存活时一律
    返回 False——这正是消掉「探针超时被误判为崩溃」误杀的关键闸门。
    """
    return (
        consecutive_failures >= _RESTART_MIN_CONSECUTIVE
        and fail_window_s >= _RESTART_MIN_WINDOW_S
        and not proc_alive
    )


def _rotate_file_copytruncate(path: Path, max_bytes: int) -> bool:
    """日志超阈值时 copytruncate 轮转，保留一代 .1 副本，返回是否执行了轮转。

    Windows 下日志文件被子进程（或 nginx）以共享读写 + 追加方式长期占用，
    无法 rename，只能先复制再原地截断；截断瞬间与追加写之间的少量行丢失
    对运维日志可接受。追加语义保证持有方后续写入落在新的文件尾。
    """
    try:
        if not path.is_file() or path.stat().st_size < max_bytes:
            return False
        rotated = path.with_name(path.name + ".1")
        with open(path, "rb") as src, open(rotated, "wb") as dst:
            shutil.copyfileobj(src, dst, length=1024 * 1024)
        with open(path, "r+b") as f:
            f.truncate(0)
        print(f"[prod_runner] 日志 {path.name} 超过 {max_bytes // (1024 * 1024)}MB，已轮转到 {rotated.name}")
        return True
    except OSError as e:
        print(f"[prod_runner] 日志 {path.name} 轮转失败（下一轮重试）: {e}")
        return False


def _cmd_uvicorn(api_port: int, workers: int) -> list[str]:
    return [
        _PY, "-m", "uvicorn", "fastapi_app.main:app",
        # 绑定 IPv4（回环/局域网/nginx 反代可达）。避免使用 "--host ::"：
        # Windows 下会生成 IPv6-only socket，HTTP 探针与 nginx 反代的
        # IPv4 127.0.0.1:5002 无法连接，导致 502 且健康门永不就绪。
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
    健康检查持续失败且**确认进程已死**时才强制重启整棵进程树（应对 master 死亡 /
    进程树异常）；进程仍存活时只告警 + 放宽退避，绝不误杀进程树（D7 关键闸门）。
    否则为“进程型”服务，仅按进程存活判定。
    """

    def __init__(self, name: str, cmd: list[str], cwd: Path,
                 health_url: str | None = None, start_grace: float = 45.0,
                 workers: int | None = None):
        self.name = name
        self.cmd = cmd
        self.cwd = cwd
        self.health_url = health_url
        # start_grace 为历史参数保留：新的 proc-alive 闸门已能保证启动期不被误杀，
        # 故 poll() 不再据此判定（见 poll 内注释）。
        self.start_grace = start_grace
        self.workers = workers
        self.proc: subprocess.Popen | None = None
        self._logf: io.BufferedWriter | None = None
        self.delay = 2.0
        self.next_start = 0.0
        self.status = "stopped"
        self.last_health: str | None = None
        self.started_at = 0.0
        self.health_fail_start: float | None = None
        self.consecutive_health_fail = 0
        self.backoff_step = 0

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
            # 注意：此处不重置 self.delay——退避在「健康检查恢复」时才清零，
            # 保证启动即崩的进程按 2→4→…→30s 指数退避，避免崩溃风暴
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

    def _probe_health(self) -> tuple[bool, float]:
        """探测健康端点：单次超时 5s，同一 tick 内失败则重试 1 次。

        返回 (是否健康, 最近一次探针耗时秒)。重试用于吸收偶发抖动，避免把一次
        慢响应直接当成持续失败；`_log_health_fail` 的 60s 节流仍在 _http_ok 内部保留。
        """
        last_elapsed = 0.0
        for _ in range(2):
            start = time.monotonic()
            ok = _http_ok(self.health_url or "", timeout=5.0)
            last_elapsed = time.monotonic() - start
            if ok:
                return True, last_elapsed
        return False, last_elapsed

    def _mark_crashed(self) -> None:
        """置 crashed 并安排退避重启（仅在「运行→崩溃」跳变时执行一次）。"""
        if self.status == "crashed":
            return
        self.status = "crashed"
        self.next_start = time.monotonic() + self.delay
        self.delay = _next_backoff(self.delay, self.backoff_step)
        self.backoff_step += 1
        code = self.proc.returncode if self.proc else None
        print(f"[prod_runner] {self.name} 已退出 (code={code})，{int(self.delay)}s 后重启")

    def poll(self) -> None:
        """主循环每轮调用：进程退出、或「确已死亡且健康持续失败」才安排退避重启。

        关键（D7）：健康型服务的强制重启前，必须先判定「进程是真的死了」还是
        「只是探针超时」。进程树仍存活 → 只告警 + 放宽退避，绝不 kill_tree()。
        """
        if self.proc is None:
            return
        if self.proc.poll() is not None:
            # 只在「运行→崩溃」跳变时安排重启时刻。若每轮都重置 next_start，
            # 由于主循环间隔(3s)≥首次退避(2s)，next_start 永远落在未来，
            # maybe_restart 将永久饥饿——已退出进程永远不会被重启（2026-09-12 实证：
            # uvicorn master 死后 4 个孤儿 worker 顶在 5002 上服务数小时无人重启）。
            self._mark_crashed()
            return
        if not self.health_url:
            self.status = "running"
            return
        # 健康型服务
        healthy, elapsed = self._probe_health()
        # 复检进程存活：探针最长可耗时 ~10s，期间 master 可能已经死掉
        proc_alive = self.proc.poll() is None
        if healthy:
            self.status = "ready"
            self.last_health = _iso_now()
            self.health_fail_start = None
            self.consecutive_health_fail = 0
            self.delay = 2.0  # 服务健康，退避归零
            self.backoff_step = 0
            return
        self.consecutive_health_fail += 1
        if self.health_fail_start is None:
            self.health_fail_start = time.monotonic()
        window = time.monotonic() - self.health_fail_start
        if _should_restart(self.consecutive_health_fail, window, proc_alive):
            print(f"[prod_runner] {self.name} 进程已死且健康检查持续失败"
                  f"(连续 {self.consecutive_health_fail} 次 / 窗口 {int(window)}s)，强制重启进程树")
            self.kill_tree()
            self.health_fail_start = None
            self.consecutive_health_fail = 0
            self._mark_crashed()
            return
        # 进程仍存活，仅探针失败：只告警 + 放宽退避，绝不误杀进程树（消掉大部分误杀）
        print(f"[prod_runner] {self.name} 健康检查失败但进程存活，暂不重启"
              f"(连续 {self.consecutive_health_fail} 次 / 窗口 {int(window)}s / "
              f"最近探针 {elapsed:.1f}s / proc_alive={proc_alive} / workers={self.workers})")
        self.delay = _next_backoff(self.delay, self.backoff_step)
        self.backoff_step += 1

    def maybe_restart(self) -> None:
        if self.status == "crashed" and self.next_start <= time.monotonic():
            self.start()

    def rotate_log_if_needed(self, max_bytes: int) -> None:
        """子进程 stdout 日志轮转（服务停止期间同样清理历史大文件）。"""
        _rotate_file_copytruncate(LOGS_DIR / f"{self.name}.out.log", max_bytes)


class _FrontendNginx:
    """Nginx 前端托管：nginx 为独立守护进程，按端口存活情况重启。"""

    def __init__(self, nginx: Path, web_port: int):
        self.nginx = nginx
        self.web_port = web_port
        self.delay = 5.0
        self.next_start = 0.0
        self.status = "stopped"
        # Popen 句柄：用于取真实 pid、关闭 spawn 日志句柄。此前 spawn 返回值被丢弃，
        # 早期失败除 nginx-error.log 外完全无痕，也无法观测 pid（D3/D4 根因）。
        self.proc: subprocess.Popen | None = None
        self._spawn_logf: io.BufferedWriter | None = None

    @property
    def pid(self) -> int | None:
        """nginx 进程真实 pid；未派生或已退出时返回 None（不谎报）。"""
        if self.proc is not None and self.proc.poll() is None:
            return self.proc.pid
        return None

    def _close_spawn_log(self) -> None:
        """关闭并释放 spawn 日志句柄，避免重启路径反复 _ensure_started 时句柄泄漏。"""
        if self._spawn_logf:
            with contextlib.suppress(OSError):
                self._spawn_logf.close()
        self._spawn_logf = None

    def _spawn(self) -> None:
        """派生 nginx master 并保存句柄；stdout/stderr 落盘 nginx-spawn.out.log。

        Windows 上 nginx.exe 本身就是 master 进程，启动后不会退出返回，绝不能用
        subprocess.run（会阻塞到 timeout 抛 TimeoutExpired，拖垮 prod_runner 主流程，
        导致 NSSM 反复重启监督器、nginx 被周期性 kill/重建，全站连接每 ~35 秒被切断
        一次，前端所有请求 502 重试）。改用 Popen 派生后立即返回，再由上层探测就绪。
        """
        self._close_spawn_log()  # 关闭上一轮遗留句柄（重启路径中会反复调用）
        try:
            self._spawn_logf = open(  # noqa: SIM115 需保持打开作为子进程 stdout
                LOGS_DIR / "nginx-spawn.out.log", "ab"
            )
            self.proc = subprocess.Popen(  # nosec B603
                [str(self.nginx), "-p", str(PROJECT_ROOT), "-c", str(NGINX_CONF),
                 "-e", str(LOGS_DIR / "nginx-error.log")],
                cwd=str(PROJECT_ROOT), creationflags=_CREATE_NO_WINDOW,
                stdout=self._spawn_logf, stderr=subprocess.STDOUT,
            )
        except (OSError, subprocess.SubprocessError) as e:
            self.proc = None
            self._close_spawn_log()
            print(f"[prod_runner] ERROR: 派生 nginx 进程失败: {e}")

    def _dump_error_log_tail(self, max_lines: int = 20) -> None:
        """打印 nginx-error.log 尾部——nginx 启动失败时唯一能自我说明的通道。

        典型真相：[emerg] bind() to 0.0.0.0:3000 failed (10013: ...)。
        文件可能不存在（nginx 从未真正起过），必须做异常保护。
        """
        err_path = LOGS_DIR / "nginx-error.log"
        try:
            if not err_path.is_file():
                print(f"[prod_runner]   （无 {err_path.name}，nginx 可能未真正启动）")
                return
            lines = err_path.read_text(encoding="utf-8", errors="replace").splitlines()
            tail = lines[-max_lines:]
            if not tail:
                print(f"[prod_runner]   （{err_path.name} 为空）")
                return
            print(f"[prod_runner]   --- {err_path.name} 尾部 {len(tail)} 行 ---")
            for line in tail:
                print(f"[prod_runner]   {line}")
        except OSError as e:
            print(f"[prod_runner]   读取 {err_path.name} 失败: {e}")

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
        # 进程已清理，同步释放句柄与句柄引用，避免重启路径中句柄泄漏 / 取到死进程
        self.proc = None
        self._close_spawn_log()

    def _ensure_started(self) -> None:
        # 启动前先彻底清理历史遗留的 nginx 进程（含孤儿 worker）。
        # 否则端口 3000 被旧 master 占用，新 master 无法绑定。
        self._kill_all()
        LOGS_DIR.mkdir(exist_ok=True)
        self._spawn()
        # 轮询 /nginx-health 确认就绪：该探测校验响应体含 '"service":"nginx"'，
        # 因此 :3000 上是 Vite dev server 的 SPA fallback（200 + index.html）时判否。
        started = False
        for _ in range(10):
            if self.alive():
                started = True
                break
            time.sleep(0.5)
        if started:
            self.status = "running"
            self.delay = 5.0
            print(f"[prod_runner] 前端 Nginx 已启动 (port {self.web_port}, PID {self.pid})")
            return
        # 探测全败：必须如实置 crashed + 退避，绝不能无条件置 running 假成功。
        self.status = "crashed"
        self.next_start = time.monotonic() + self.delay
        self.delay = min(self.delay * 2, 30.0)
        print(f"[prod_runner] ERROR: 前端 Nginx 启动失败（{int(self.delay)}s 后重试），"
              f"port={self.web_port}, pid={self.pid}")
        self._dump_error_log_tail()

    def alive(self) -> bool:
        # expect_substr 确保是 nginx 自身的 /nginx-health 返回，而非同端口其它服务。
        return _http_ok(
            f"http://127.0.0.1:{self.web_port}/nginx-health",
            timeout=1.5,
            expect_substr='"service":"nginx"',
        )

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

    def rotate_logs_if_needed(self, max_bytes: int) -> None:
        """Nginx access/error 日志轮转。

        nginx 以共享读写 + 原子追加方式持有日志句柄，外部截断后其后续
        写入仍落在新的文件尾，无需发送 -s reopen 信号。
        """
        for name in ("nginx-access.log", "nginx-error.log"):
            _rotate_file_copytruncate(LOGS_DIR / name, max_bytes)


class Supervisor:
    def __init__(self, workers: int, api_port: int, web_port: int, with_arq: bool = True):
        self.workers = workers
        self.api_port = api_port
        self.web_port = web_port
        self.with_arq = with_arq
        self.redis_port = _get_int_env("REDIS_PORT", 6379)
        self.ready = False
        self._last_log_check = 0.0

        self.backend = _Managed(
            "后端(uvicorn)", _cmd_uvicorn(api_port, workers), PROJECT_ROOT,
            health_url=f"http://127.0.0.1:{api_port}/api/health",
            workers=workers,
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
    def _frontend_state(self) -> tuple[int | None, str, bool]:
        """现探前端真实存活状态，避免落盘被污染的 self.nginx.status（谎报根因）。

        返回 (pid, status, ok)。nginx 分支以 HTTP 探针现探结果为准；vite 分支以
        Popen 句柄存活为准。任何情况下都不以可能滞后的 self.nginx.status 充当"存活"。
        """
        if self.nginx:
            ok = self.nginx.alive()
            return self.nginx.pid, ("running" if ok else "crashed"), ok
        if self.vite:
            pid = self.vite.proc.pid if self.vite.proc else None
            return pid, self.vite.status, self.vite.alive()
        return None, "stopped", False

    def write_status(self) -> None:
        redis_status = "ok" if _is_redis_up(self.redis_port) else "down"
        self.ready = self.backend.status == "ready"  # 语义保持不变（GUI 可能已依赖）
        frontend_pid, frontend_status, frontend_ok = self._frontend_state()
        data = {
            "pid": os.getpid(),
            "started_at": _iso_now(),
            "mode": "production",
            "ready": self.ready,
            # 新增可观测字段：ready 只看后端，前端缺失此前完全不可见；
            # 新增 frontend_ok 暴露前端真实存活，不改变 ready 现有语义。
            "frontend_ok": frontend_ok,
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
                    "pid": frontend_pid,
                    "status": frontend_status,
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
                self._rotate_logs_if_due()
                self.write_status()
            except Exception as e:  # defensive: supervisor main loop must not exit
                print(f"[prod_runner] 主循环异常（已吞掉，不退出）: {type(e).__name__}: {e}")
            time.sleep(3)

    # -- 日志轮转 -----------------------------------------------------------
    def _rotate_logs_if_due(self) -> None:
        """按 LOG_ROTATE_CHECK_INTERVAL 节流，检查并轮转子进程与 Nginx 日志。"""
        if time.monotonic() - self._last_log_check < LOG_ROTATE_CHECK_INTERVAL:
            return
        self._last_log_check = time.monotonic()
        max_bytes = _log_rotate_bytes()
        for svc in (self.backend, self.arq, self.vite):
            if svc:
                svc.rotate_log_if_needed(max_bytes)
        if self.nginx:
            self.nginx.rotate_logs_if_needed(max_bytes)

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
