"""
ERP 生产模式监督器 (Windows 原生)。

统一生产入口：`start.py --prod` 最终调用本模块。
职责：
  1. 拉起并守护多 worker Uvicorn（默认 UVICORN_WORKERS=4，可 .env / 环境变量覆盖）
  2. 前端由独立 NSSM 服务 erp-web 托管 nginx——本模块只做只读探针（/nginx-health），
     结果写入状态文件 frontend_ok 字段，探测失败只报告、绝不重启
  3. Redis：仅检查连通（生产建议将 Redis 注册为独立 Windows 服务）
  4. 子进程崩溃自动重启（指数退避 2s→30s，防崩溃风暴）；
     对后端按 /api/health 做健康判定，主进程存活但 worker 崩溃循环时强制重启整棵进程树
  5. 状态落盘 logs/prod_runner.json，供 server_manager GUI 展示
  6. 子进程 stdout/stderr 落盘 logs/<name>.out.log，便于排障
  7. 日志维护：按共享策略（config/log_policy.json，默认轮转 50MB / 保留 14 天 /
     目录上限 512MB）copytruncate 轮转超限日志并清理过期日志，防止长期运行后磁盘被
     日志占满。策略与实现统一在 utils/log_rotation.py，与桌面壳、ARQ 定时任务**同一份**
     （历史上本模块用 PROD_LOG_ROTATE_MB、ARQ 用 100MB、桌面壳用 50MB，各有一套）

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
import socket
import ssl
import subprocess  # nosec B404
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path

from utils.log_rotation import load_log_policy, prune_log_files, rotate_oversized_logs

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
LOGS_DIR = PROJECT_ROOT / "logs"
STATUS_FILE = LOGS_DIR / "prod_runner.json"
# 轮转/保留策略的**唯一**来源，与桌面壳、ARQ 定时任务共用同一份文件。
LOG_POLICY_PATH = PROJECT_ROOT / "config" / "log_policy.json"

_PY = sys.executable
_CREATE_NO_WINDOW = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0

# 日志维护：检查间隔。阈值/保留期不在这里常量化 —— 统一由 LOG_POLICY_PATH 决定，
# 避免又出现「同一个机器上多大该轮转有三个答案」（历史上 prod_runner 50MB、
# ARQ 100MB、桌面壳 50MB）。
LOG_ROTATE_CHECK_INTERVAL = 60.0

# kill_tree 软杀等待窗口 —— **只在软杀自己报告成功（rc=0）时才会进入**。
# 实测（2026-10-13）：对 CREATE_NO_WINDOW 子进程 `taskkill /T`（不带 /F）0.06s 就返回
# rc=128「只能强制终止此进程(带 /F 选项)」，一个进程都没杀掉；此时等待纯属白等，
# 直接升级硬杀（/F 实测 0.05s 即完成）。
# ★ 窗口上限受 NSSM 停机预算硬约束：AppStopMethodConsole=1500ms +
#   AppStopMethodThreads=1500ms（NSSM 默认值，本仓 nssm_install 未覆盖）—— 监督器
#   若没在这 ~3s 内退干净，NSSM 会 TerminateProcess 掉它，**uvicorn 子进程树就没人
#   回收，变成继续占着 :5002 的孤儿**（2026-10-13 08:12 现场：erp-prod 服务 STOPPED，
#   而 5002 上仍有一整棵后端树在服务）。窗口必须远小于 1500ms。
#   旧值 4.0 的注释写「4s 远小于 nssm restart 的停机容忍」——**该判断是错的**，
#   正是 2026-10-11 P1-9 引入孤儿的原因。现取 1.0s：软杀(0.06s)+窗口+硬杀(0.05s)
#   ≈1.1s，仍在 NSSM 的 1500ms console 预算内，同时给「软杀真能生效」的那天留下
#   足够走完 lifespan 关停段的余地（0.5s 几乎必然不够，等于静默退回硬杀）。
_SOFT_KILL_WAIT_SECONDS = 1.0
_SOFT_KILL_POLL_INTERVAL = 0.2


def _source_fingerprint() -> str:
    """本模块源码的 sha256（前 12 位）+ mtime —— 版本指纹。

    ★ 为什么必须有：2026-09-16 那次「崩溃重启饥饿」事故里，源码早已修好，但线上
    NSSM 服务跑的是**旧版** prod_runner，无人察觉地漂移了约 10 小时。原因就是日志里
    没有任何「我是哪一版」的标记，运维无法用日志判断「跑的是不是刚提交的代码」。
    加上指纹后，只需比对日志首行与 git 中的文件即可判定部署漂移。
    """
    try:
        import hashlib
        p = Path(__file__).resolve()
        digest = hashlib.sha256(p.read_bytes()).hexdigest()[:12]
        mtime = datetime.fromtimestamp(p.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S")
        return f"{digest} mtime={mtime}"
    except OSError:
        return "unavailable"


def _init_log_streams() -> None:
    """统一 stdout/stderr 编码为 UTF-8 并置行缓冲，随后打印版本指纹横幅。

    ★ 编码：NSSM 用 `PYTHONUTF8=1` 拉起时 stdout 是 UTF-8，但早期版本的服务 env
    没有这项，于是同一份 `erp-prod.log` 里混着 GBK 与 UTF-8 两种字节（实测 85% / 15%）。
    显式 reconfigure 让**当前**进程的输出编码确定化，新写入的段不再产生新的混编。
    `reconfigure` 缺失（如 stdout 被替换成非 TextIOWrapper）时静默降级，不影响启动。
    """
    for stream in (sys.stdout, sys.stderr):
        if not isinstance(stream, io.TextIOWrapper):
            continue
        with contextlib.suppress(Exception):
            stream.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
    started = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[prod_runner] ==== 启动 ==== fingerprint={_source_fingerprint()} "
          f"pid={os.getpid()} python={sys.version.split()[0]} started={started}")
    print(f"[prod_runner] cwd={PROJECT_ROOT} UVICORN_WORKERS={os.getenv('UVICORN_WORKERS', '(unset)')}")
    with contextlib.suppress(Exception):
        sys.stdout.flush()


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


def _get_int_env_from_env_file(name: str, default: int) -> int:
    """从 .env 文件读取整型配置（不污染 os.environ，仅用于自检/落盘展示）。"""
    try:
        for line in (PROJECT_ROOT / ".env").read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            if key.strip() == name:
                return int(val.strip().strip('"').strip("'"))
    except (OSError, ValueError):
        pass
    return default


def _default_workers() -> int:
    """worker 数（单一可信来源：环境变量 UVICORN_WORKERS）。

    优先级：进程环境变量 > .env 的 UVICORN_WORKERS > min(4, cpu_count)。

    为什么必须先显式读 .env：NSSM 服务的 `AppEnvironmentExtra` 与 .env 能给出
    两个互相矛盾的值（2026-09-16 实测：服务参数写 8、.env 里没有该项），
    而 uvicorn 子进程与 database.py 的连接池都按自己的读法取值 → 同一次启动
    里「监督器以为 4、实际跑 8、连接池按 4 分摊」，三方对不上。
    `_load_dotenv(override=False)` 让已存在的进程变量优先，这里再补一次显式读取，
    保证「日志里打印的数」与「真正传给 --workers 的数」永远是同一个。
    """
    configured = _get_int_env("UVICORN_WORKERS", 0)
    if configured <= 0:
        configured = _get_int_env_from_env_file("UVICORN_WORKERS", 0)
    if configured > 0:
        return configured
    return max(1, min(4, os.cpu_count() or 1))


def _is_redis_up(port: int) -> bool:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.settimeout(1)
            return sock.connect_ex(("127.0.0.1", port)) == 0
    except OSError:
        return False


def _broker_port() -> int:
    """ARQ broker 端口。

    取自 REDIS_BROKER_URL（.env 里独立实例，默认 6380）；未配置该 URL 时
    ARQ 会回退到通用 REDIS_HOST/REDIS_PORT（见 arq_app._build_redis_settings），
    此处同步回退，避免健康检查查错端口。
    """
    broker_url = os.getenv("REDIS_BROKER_URL", "") or ""
    if not broker_url:
        return _get_int_env("REDIS_PORT", 6379)
    try:
        # redis://[:password@]host:port/db —— 不引入 urllib 解析差异，直接切
        tail = broker_url.split("://", 1)[-1]
        host_port = tail.rsplit("@", 1)[-1].split("/", 1)[0]
        if ":" in host_port:
            return int(host_port.rsplit(":", 1)[-1])
    except (ValueError, IndexError):
        pass
    return _get_int_env("REDIS_PORT", 6379)


# 健康探针必须直连本机，绝不走系统代理。
# 根因(2026-09-10 实证): 本机设置了 HTTP_PROXY/HTTPS_PROXY=127.0.0.1:<port>(代理客户端)
# 且无 NO_PROXY，urllib 默认会读取系统代理——包括 Windows 注册表代理设置——导致
# 探测 127.0.0.1:5002 的 /api/health 被路由进代理。代理客户端抖动时健康检查间歇性
# 失败，触发下方「连续失败 20s → 强制重启」逻辑，形成后端重启风暴
# (应用本身完全正常：被杀前最后一条日志距关停 0 秒、均为正常业务请求)。
# ProxyHandler({}) 显式清空代理，保证探针永远直连。
_OPENER_DIRECT = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def _web_health_scheme() -> str:
    """前端健康探针（:3000 /nginx-health）使用的 scheme，取 WEB_HEALTH_SCHEME，默认 http。

    背景（2026-10-09 新机事故）：探针原先硬编码 `http://127.0.0.1:{web_port}`，
    erp-web/nginx 一旦给 :3000 上 TLS，明文请求会得到 400 → frontend_ok 恒 false、
    watchdog 恒报 web_entry=fail（服务其实完全正常）。上 TLS 的机器置
    WEB_HEALTH_SCHEME=https 即可；默认 http，未上 TLS 的机器行为不变。
    """
    return os.getenv("WEB_HEALTH_SCHEME", "http").strip().lower() or "http"


def _probe_opener(scheme: str) -> urllib.request.OpenerDirector:
    """按 scheme 返回探针 opener。

    https 时容忍自签/过期证书（回环探针只判「端口有人在服务」，不做证书链校验；
    否则自签证书会让探针一律失败，退回本函数要修的那个假故障）。同样清空代理。
    """
    if scheme != "https":
        return _OPENER_DIRECT
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return urllib.request.build_opener(
        urllib.request.ProxyHandler({}), urllib.request.HTTPSHandler(context=ctx),
    )

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


def _http_ok(
    url: str, timeout: float = 5.0, expect_substr: str | None = None,
    opener: urllib.request.OpenerDirector | None = None,
    body_out: list[str] | None = None,
) -> bool:
    """探测 url 是否可用。

    expect_substr 非空时额外要求响应体包含该子串。用于区分「目标服务就绪」与
    「同端口上的其它服务返回了 200」——典型如 :3000 上 nginx 缺席时由 Vite dev
    server 以 SPA fallback 对任意路径直出 200 + index.html，仅比较状态码会误判。
    既有调用方（后端/ARQ 探针）不传该参数，行为与修复前完全一致。

    opener 非空时改用它发起请求（前端探针在 https 端口上需要容忍自签证书的 opener）。

    body_out 非空时把响应体有界前缀塞进该列表（身份校验要读 ``runtime.pid``）。
    复用本函数的 opener / 异常口径，避免为读一次 body 再开一个 urllib 调用点
    （每多一处 ``urlopen`` 就多一条安全扫描豁免，nosec 预算是硬约束）。
    """
    try:
        with (opener or _OPENER_DIRECT).open(url, timeout=timeout) as resp:  # nosec B310
            if resp.status != 200:
                return False
            if expect_substr is None and body_out is None:
                return True
            # 只读有界前缀（探针目标响应都很小），避免万一命中大体积 body 时的内存放大
            body = resp.read(8192).decode("utf-8", errors="replace")
            if body_out is not None:
                body_out.append(body)
            return True if expect_substr is None else expect_substr in body
    except (urllib.error.URLError, OSError, TimeoutError) as e:
        _log_health_fail(e)
        return False


def _http_json(url: str, timeout: float = 3.0) -> dict | None:
    """取健康端点的 JSON 体（用于身份校验）；拿不到/不是 JSON 返回 None。"""
    if not url:
        return None
    chunks: list[str] = []
    if not _http_ok(url, timeout=timeout, body_out=chunks):
        return None
    try:
        data = json.loads(chunks[0] if chunks else "")
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


def _port_of(url: str) -> int | None:
    """从 health_url 取端口（用于端口归属校验）。"""
    try:
        parsed = urllib.parse.urlsplit(url)
    except ValueError:
        return None
    return parsed.port


def _pid_in_tree(pid: int, root_pid: int) -> bool:
    """pid 是否属于 root_pid 的进程树（含 root 自身）；psutil 不可用时返回 True。"""
    if pid == root_pid:
        return True
    try:
        import psutil
    except ImportError:  # pragma: no cover - base 依赖
        return True
    try:
        return any(child.pid == pid for child in psutil.Process(root_pid).children(recursive=True))
    except (psutil.Error, OSError):
        return True


def _foreign_listeners(port: int, root_pid: int) -> set[int]:
    """端口上**不属于** root_pid 进程树的 LISTEN 进程集合；取证失败返回空集。

    Windows 的 SO_REUSEADDR 允许同一端口出现多个 LISTEN（不报 10048）。实测事故：
    08:11 的孤儿实例与 15:11 的新实例同时 LISTEN，孤儿继续 accept，新实例日志
    照打「Uvicorn running」却收不到请求 —— 只看健康码永远发现不了。
    """
    try:
        import psutil
    except ImportError:  # pragma: no cover
        return set()
    try:
        conns = psutil.net_connections(kind="tcp")
        own = {root_pid, *[c.pid for c in psutil.Process(root_pid).children(recursive=True)]}
    except (psutil.Error, OSError):
        return set()
    foreign: set[int] = set()
    for conn in conns:
        try:
            if conn.status != psutil.CONN_LISTEN or not conn.laddr or conn.laddr.port != port:
                continue
        except (AttributeError, IndexError):
            continue
        pid = conn.pid
        if pid and pid not in own:
            foreign.add(pid)
    return foreign


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

# AUD-08（2026-10-24 审计）：D7 的三条件闸门挡住了误杀，也挡住了真故障——
# uvicorn --workers>1 时 master 会无限 respawn 崩溃 worker 而自身长存
# （supervisors/multiprocess.py），proc_alive 恒 True、三条件永差一个：
# worker 启动即崩（如 2026-10-22 site-packages 批量损坏）时 5002 永不监听，
# 而 status 停在 ready → prod_runner.json 持续 ready:true，「总宕机显示绿」。
# 补一条**远高于探针抖动**的降级阈值：进程存活且不健康窗口超过 10 分钟也强制
# 重启（探针偶发超时是秒级，10 分钟窗口不会误杀）；同时不健康期间 status
# 降级为 "degraded"（ready:false），状态文件如实反映。
_DEGRADED_RESTART_MIN_WINDOW_S = 600.0

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


def _should_force_restart_degraded(consecutive_failures: int, fail_window_s: float) -> bool:
    """进程存活但健康持续失败的兜底重启判据（AUD-08，纯函数）。

    与 _should_restart 的关系：那条要求 proc_alive is False（防误杀）；本条处理
    「master 长存 + worker 崩溃循环」——proc 恒活、探针恒败。窗口阈值放大到
    _DEGRADED_RESTART_MIN_WINDOW_S（10 分钟），探针抖动（秒级）达不到；
    连续失败次数门槛与 _should_restart 相同。
    """
    return (
        consecutive_failures >= _RESTART_MIN_CONSECUTIVE
        and fail_window_s >= _DEGRADED_RESTART_MIN_WINDOW_S
    )


def _cmd_uvicorn(api_port: int, workers: int) -> list[str]:
    return [
        _PY, "-m", "uvicorn", "fastapi_app.main:app",
        # 仅绑回环：生产拓扑为同机 nginx(3000) 反代 127.0.0.1:5002，
        # 绑 0.0.0.0 会让局域网绕过 nginx/安全头直连后端（/metrics 等随之暴露）。
        "--host", "127.0.0.1",
        "--port", str(api_port),
        "--workers", str(workers),
        "--http", "httptools",
        "--proxy-headers",
        # P0-6(b)：只信任回环代理（本机 nginx）。取 "*" 等于无条件信任任何来源的
        # X-Forwarded-For/Proto —— 攻击者可伪造 XFF 绕过基于 IP 的限流与审计。
        "--forwarded-allow-ips=127.0.0.1",
        "--no-access-log",
        "--timeout-keep-alive", "5",
    ]


def _cmd_arq() -> list[str]:
    return [_PY, "-m", "arq", "fastapi_app.core.arq_app.WorkerSettings"]


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
        print(f"  OK: Redis 缓存连通 (127.0.0.1:{redis_port})")
    else:
        print(f"  WARN: Redis 缓存未运行 (127.0.0.1:{redis_port})，生产建议注册为 Windows 服务")

    broker_port = _broker_port()
    if broker_port == redis_port:
        # broker 与缓存共用实例：上面那条已覆盖，避免同一条信息报两次
        pass
    elif _is_redis_up(broker_port):
        print(f"  OK: Redis broker 连通 (127.0.0.1:{broker_port}，erp-arq 依赖)")
    else:
        print(f"  ERROR: Redis broker 未运行 (127.0.0.1:{broker_port})，"
              f"erp-arq 将无法启动（cron/备份/报表全部不执行）；"
              f"请先启动 erp-redis-broker 服务")
        ok = False

    dist_dir = PROJECT_ROOT / "frontend-vite" / "dist"
    if dist_dir.is_dir():
        print(f"  OK: 前端构建产物存在 {dist_dir}")
    else:
        print(f"  WARN: 前端构建产物缺失 {dist_dir}，请先执行 npm run build")
        ok = False

    print("  INFO: 前端由独立 NSSM 服务 erp-web 托管(本模块只做只读探针)")
    print(f"  INFO: worker 数 = {workers}（来源: UVICORN_WORKERS 环境变量/.env，"
          f"cpu_count={os.cpu_count()}）")
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
                 workers: int | None = None, verify_identity: bool = False):
        self.name = name
        self.cmd = cmd
        self.cwd = cwd
        self.health_url = health_url
        # start_grace 为历史参数保留：新的 proc-alive 闸门已能保证启动期不被误杀，
        # 故 poll() 不再据此判定（见 poll 内注释）。
        self.start_grace = start_grace
        self.workers = workers
        # 2026-10-26（重启实测事故）：健康 200 只说明**有人**在应答，不说明是**我**的
        # 进程在应答。Windows 的 SO_REUSEADDR 允许第二个 socket 绑同一端口而不报
        # 10048：孤儿实例继续 accept，新实例日志照样打「Uvicorn running」却收不到
        # 一个请求，而本监督器看到 200 就判 ready —— 上线等于没上。
        # 置 True 的服务在首次健康通过时校验「应答体的 runtime.pid 属于本进程树」
        # 与「端口没有非本树的 LISTEN」，不成立即降级（ready:false）而不是假装成功。
        self.verify_identity = verify_identity
        self._identity_checked = False
        self.identity_problem: str | None = None
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
        # H2：杀树未确认成功后的重试时刻。窗口内不得再发杀树、更不得起新进程。
        self._kill_retry_at = 0.0

    def start(self) -> None:
        if self.proc and self.proc.poll() is None:
            return
        # B4-F4（2026-10-24 审计）：崩溃重启循环每次 start() 覆写 _logf/proc——
        # 旧日志句柄不 close、死 Popen 不 wait，一天最多泄漏 ~288 组句柄。
        old_logf = getattr(self, '_logf', None)
        if old_logf is not None:
            with contextlib.suppress(OSError):
                old_logf.close()
            self._logf = None
        old_proc = getattr(self, 'proc', None)
        if old_proc is not None and old_proc.poll() is not None:
            old_proc.wait()
        # 每次拉起都要重新证实身份（上一轮可能是别人在应答）；放在 Popen 之前，
        # 保证「本次启动尝试」一开始就不带着上一轮的结论。
        self._identity_checked = False
        self.identity_problem = None
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

    def kill_tree(self) -> bool:
        """终止整棵进程树：Windows 先软杀、超时才升级硬杀；非 Windows 用进程组 SIGTERM。

        返回「是否已确认终止」：True = 进程树确认不在（含本来就没进程）；
        False = 终止动作做完但 PID 仍存活。**H2（2026-10-26 上线前检查）**：
        旧实现无论成没成都会 ``self.proc = None``，调用方随后 ``_mark_crashed()``
        并安排重启——旧进程仍占着 :5002 时再拉一个新实例，同端口双进程、
        而监督器已彻底失去旧进程句柄（再也杀不掉）。

        2026-10-11（复核 P1-9）：原先对 uvicorn 子进程一律 `taskkill /F /T`，
        TerminateProcess 使 lifespan 关停段从不执行（实测 84/160 次进入关停段
        未走完、收尾哨兵「数据库连接池已关闭」自 2026-10-02 起再未亮）。
        现先发不带 /F 的软杀；**软杀报告成功才轮询等待**，否则直接升级 /F。

        2026-10-13（修正 P1-9 的回归）：P1-9 无条件等 4s，而软杀对
        CREATE_NO_WINDOW 子进程实测 0.06s 就回 rc=128、什么都没杀 —— 于是每次停机
        都白等 4s，超过 NSSM 的 3s 停机预算，监督器被 TerminateProcess 掉，
        uvicorn 进程树成为占着 :5002 的孤儿。现在软杀失败即硬杀（合计 ~0.1s），
        监督器能在 NSSM 的 console 窗口内自行退干净。
        """
        if not self.proc:
            return True
        pid = self.proc.pid
        if os.name == "nt":
            soft = subprocess.run(  # nosec B603 B607
                ["taskkill", "/T", "/PID", str(pid)],
                creationflags=_CREATE_NO_WINDOW,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=15,
            )
            # 软杀返回非 0 = 它一个进程都没终止（CREATE_NO_WINDOW 子进程必得 128），
            # 等待窗口只在它报告成功时才有意义 —— 否则纯属把监督器拖出 NSSM 的停机预算。
            soft_ok = soft.returncode == 0
            if soft_ok:
                deadline = time.monotonic() + _SOFT_KILL_WAIT_SECONDS
                while time.monotonic() < deadline and self.proc.poll() is None:
                    time.sleep(_SOFT_KILL_POLL_INTERVAL)
            if self.proc.poll() is None:
                if soft_ok:
                    # 软杀报告成功却没在窗口内退出 = 优雅关停没走完，正被硬杀接管
                    # （P1-9 要避免的那条路）。必须留痕，否则将来只能从「哨兵又不亮」
                    # 反推是哪一步退化的。
                    print(f"[prod_runner] 警告: 软杀成功但 PID {pid} 在 "
                          f"{_SOFT_KILL_WAIT_SECONDS}s 内未退出，升级硬杀（优雅关停未走完）")
                result = subprocess.run(  # nosec B603 B607
                    ["taskkill", "/F", "/T", "/PID", str(pid)],
                    creationflags=_CREATE_NO_WINDOW,
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=15,
                )
                if result.returncode != 0:
                    print(f"[prod_runner] 警告: taskkill 返回 {result.returncode}，"
                          f"PID {pid} 的进程树可能未终止（旧进程会继续占用端口）")
        else:
            import signal
            try:
                os.killpg(os.getpgid(pid), signal.SIGTERM)  # type: ignore[attr-defined]
            except (ProcessLookupError, OSError):
                self.proc.terminate()
        with contextlib.suppress(subprocess.TimeoutExpired):
            self.proc.wait(timeout=5)
        if self.proc.poll() is None:
            # H2：未确认死亡 → 保留 proc/_logf 身份，让调用方能够重试杀树，
            # 也避免「以为杀掉了」而再起一个同端口实例。
            print(f"[prod_runner] 错误: PID {pid} 在终止后仍存活，"
                  f"保留其身份以便重试（不安排新进程）——请手工确认孤儿进程")
            return False
        if self._logf:
            with contextlib.suppress(OSError):
                self._logf.close()
        self._logf = None
        self.proc = None
        return True

    def _defer_after_failed_kill(self, seconds: float = 30.0) -> None:
        """杀树未确认成功：保留进程身份与状态，退避后重试（H2）。

        不调用 ``_mark_crashed()``——那会把 ``next_start`` 提前并让 ``maybe_restart``
        在同一端口再起一个实例，而旧进程仍在服务、监督器已丢失其句柄。
        """
        self._kill_retry_at = time.monotonic() + seconds
        if self.status in ("ready", "running"):
            self.status = "degraded"
        print(f"[prod_runner] {self.name} 进程树未确认终止，{int(seconds)}s 后重试；"
              f"期间不启动新进程（避免同端口双实例），状态={self.status}")

    def _verify_identity(self) -> str | None:
        """证实「应答健康检查的就是我自己拉起的进程」。返回问题描述，None 表示通过。

        两道判据（任一不成立即降级，见 ``verify_identity`` 的注释）：

        1. 应答体带 ``runtime`` 时，``runtime.pid`` 必须落在本进程树内。缺 ``runtime``
           说明对方不提供身份指纹（旧代码，或同端口的别的程序）——**也算不通过**，
           这正是 2026-10-26 那次「重启了但跑的是旧代码」的指纹。
        2. 端口上不允许存在**非本进程树**的 LISTEN。Windows 的 SO_REUSEADDR 允许两个
           socket 绑同一端口，谁先绑谁收流量；多出来的那个监听者迟早把请求抢走。

        取证失败（无 psutil / 拿不到 JSON）时返回 None —— 宁可放过，不能因为探针
        能力缺失把正常服务判成故障。
        """
        root_pid = self.proc.pid if self.proc else None
        if root_pid is None:
            return None
        payload = _http_json(self.health_url or "", timeout=3.0)
        if payload is None:
            return None
        runtime = payload.get("runtime") if isinstance(payload, dict) else None
        if not isinstance(runtime, dict):
            return ("健康响应缺少 runtime 身份指纹（应答的是不提供指纹的旧代码，"
                    "或同端口上的其它程序）")
        pid = runtime.get("pid")
        if not isinstance(pid, int) or isinstance(pid, bool) or not _pid_in_tree(pid, root_pid):
            return f"应答进程 pid={pid} 不属于本进程树（本树根 PID {root_pid}）"
        port = _port_of(self.health_url or "")
        if port is None:
            return None
        foreign = _foreign_listeners(port, root_pid)
        if foreign:
            return (f"端口 {port} 上还有非本进程树的监听者 {sorted(foreign)}"
                    f"（本树根 PID {root_pid}）——新实例可能收不到流量")
        return None

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
            # 2026-10-26：健康 200 只证明「有人应答」。首次健康通过时证实应答者身份，
            # 不成立则降级（ready:false）并保持进程存活——问题不在我的子进程，
            # 重启它也没用，得先清掉抢占端口的那个监听者。
            if self.verify_identity and not self._identity_checked:
                self._identity_checked = True
                self.identity_problem = self._verify_identity()
                if self.identity_problem:
                    self.status = "degraded"
                    self.last_health = _iso_now()
                    print(f"[prod_runner] 错误: {self.name} 身份未证实 —— "
                          f"{self.identity_problem}；本实例可能收不到流量")
                    return
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
        if time.monotonic() < self._kill_retry_at:
            # H2：上一次杀树未确认成功。退避窗口内既不重试杀树（避免 taskkill 风暴），
            # 更不得起新进程（旧进程可能仍占着 :5002）。
            return
        if _should_restart(self.consecutive_health_fail, window, proc_alive):
            print(f"[prod_runner] {self.name} 进程已死且健康检查持续失败"
                  f"(连续 {self.consecutive_health_fail} 次 / 窗口 {int(window)}s)，强制重启进程树")
            if not self.kill_tree():
                self._defer_after_failed_kill()
                return
            self.health_fail_start = None
            self.consecutive_health_fail = 0
            self._mark_crashed()
            return
        # AUD-08：master 长存 + worker 崩溃循环（proc 恒活、探针恒败）——uvicorn
        # 多 worker 下 master 无限 respawn 崩溃 worker 而自身不退，上面的三条件
        # 闸门永差一个 proc_alive。窗口超 10 分钟时强制重启整棵树（探针抖动是
        # 秒级，不会误杀）。
        if _should_force_restart_degraded(self.consecutive_health_fail, window):
            print(f"[prod_runner] {self.name} 进程存活但健康检查持续失败超过 "
                  f"{int(_DEGRADED_RESTART_MIN_WINDOW_S)}s"
                  f"(连续 {self.consecutive_health_fail} 次 / 窗口 {int(window)}s)，"
                  f"判定 worker 崩溃循环，强制重启进程树")
            if not self.kill_tree():
                self._defer_after_failed_kill()
                return
            self.health_fail_start = None
            self.consecutive_health_fail = 0
            self._mark_crashed()
            return
        # 进程仍存活，仅探针失败：状态降级（ready:false 如实反映），只告警 +
        # 放宽退避，绝不误杀进程树（消掉大部分误杀）。crashed/failed/starting
        # 语义不动（maybe_restart 依赖），只把「曾经 ready/running」改为 degraded。
        if self.status in ("ready", "running"):
            self.status = "degraded"
        print(f"[prod_runner] {self.name} 健康检查失败但进程存活，暂不重启"
              f"(连续 {self.consecutive_health_fail} 次 / 窗口 {int(window)}s / "
              f"最近探针 {elapsed:.1f}s / proc_alive={proc_alive} / workers={self.workers})")
        self.delay = _next_backoff(self.delay, self.backoff_step)
        self.backoff_step += 1

    def maybe_restart(self) -> None:
        # 2026-10-17 审计 F-BE-CORE-06：启动失败（failed，一次都没起来）原先
        # 永不重试——start() 抛 OSError 后状态停在 failed，监督器成一次性进程
        # （端口被孤儿占用 / _PY 失效 / 杀软拦截都会走到这）。与 crashed 同样
        # 走退避阶梯，失败后再排下一次。
        if self.status in ("crashed", "failed") and self.next_start <= time.monotonic():
            self.start()
            if self.status == "failed":
                self.next_start = time.monotonic() + self.delay
                self.delay = _next_backoff(self.delay, self.backoff_step)
                self.backoff_step += 1

class Supervisor:
    def __init__(self, workers: int, api_port: int, web_port: int, with_arq: bool = True):
        self.workers = workers
        self.api_port = api_port
        self.web_port = web_port
        self.with_arq = with_arq
        self.redis_port = _get_int_env("REDIS_PORT", 6379)
        self.broker_port = _broker_port()
        self.ready = False
        self._last_log_check = 0.0
        # F4-7：Windows 控制台处理器在独立线程执行，shutdown 后主循环必须收到停止信号；
        # 否则 SetConsoleCtrlHandler 返回 True 阻止默认终止后，监督器进程永久存活。
        self._stop = threading.Event()
        # shutdown 幂等：控制台处理器与 main() 的 finally 都会调用它，
        # 重复杀进程树没有意义，还会让「正在关闭/已停止」日志计数翻倍。
        self._shutdown_done = False
        # F-BE-CORE-04 / F-OPS-DEPLOY-11：started_at 必须是监督器启动时刻，
        # 不是每次 write_status 的落盘时刻（后者见 last_write_at）。
        self._supervisor_started_at = _iso_now()
        self._write_seq = 0

        self.backend = _Managed(
            "后端(uvicorn)", _cmd_uvicorn(api_port, workers), PROJECT_ROOT,
            health_url=f"http://127.0.0.1:{api_port}/api/health",
            workers=workers,
            # 2026-10-26：后端必须证实「应答者是我拉起的进程」，见 _verify_identity
            verify_identity=True,
        )
        self.arq = _Managed("ARQ worker", _cmd_arq(), PROJECT_ROOT) if with_arq else None
        # 前端由独立 NSSM 服务 erp-web 托管,本监督器只观察不管理
        self.frontend_type = "erp-web"

    # -- 启动序列 -----------------------------------------------------------
    def start_all(self) -> None:
        LOGS_DIR.mkdir(exist_ok=True)
        print(f"[prod_runner] 启动生产模式 (workers={self.workers}, "
              f"api={self.api_port}, web={self.web_port}, frontend={self.frontend_type}"
              f"{', arq=独立服务' if not self.with_arq else ''})")
        if self.broker_port != self.redis_port and not _is_redis_up(self.broker_port):
            # 独立 broker 未就绪时早告警：prod_runner 自身不依赖它（ARQ 是独立服务），
            # 但 GUI 的「就绪」徽章不能因此变绿——否则 2026-09-16 那类
            # 「界面显示一切正常、cron 其实全没跑」的静默失效会重演。
            print(f"[prod_runner] 警告: ARQ broker 不可达 (127.0.0.1:{self.broker_port})，"
                  f"erp-arq 服务将无法运行（cron/备份/报表不执行）")
        self.backend.start()
        if self.arq:
            self.arq.start()

    # -- 前端只读探针 -------------------------------------------------------
    def _frontend_probe_ok(self) -> bool:
        """只读探测 erp-web(nginx)是否在服务 :3000。失败仅报告,绝不重启。

        expect_substr 区分「nginx 真在服务」与「同端口其它服务(如 vite dev
        server 的 SPA fallback)返回 200」。
        """
        scheme = _web_health_scheme()
        return _http_ok(
            f"{scheme}://127.0.0.1:{self.web_port}/nginx-health",
            timeout=1.5,
            expect_substr='"service":"nginx"',
            opener=_probe_opener(scheme),
        )

    # -- 状态落盘 -----------------------------------------------------------
    def _frontend_state(self) -> tuple[int | None, str, bool]:
        """erp-web 由独立 NSSM 服务托管,此处只观察不管理。

        pid 恒为 None(进程不在本监督器树内);status 恒为 "external"
        (GUI 据此改读 erp-web 服务状态);ok 由只读探针现探。
        """
        return None, "external", self._frontend_probe_ok()

    def write_status(self) -> None:
        redis_status = "ok" if _is_redis_up(self.redis_port) else "down"
        # broker 与缓存同实例时不重复探测（回退配置下两者是同一个端口）
        if self.broker_port == self.redis_port:
            broker_status = redis_status
        else:
            broker_status = "ok" if _is_redis_up(self.broker_port) else "down"
        # 2026-10-17 审计 F-BE-CORE-04：监督器死亡后状态文件永久冻结为绿
        # （GUI 无新鲜度判据）。加 last_write_at（每次落盘的真实时刻）与
        # write_seq（单调递增序号），消费方按「超过 3×循环周期(3s) 未更新即 stale」判定。
        self._write_seq = getattr(self, '_write_seq', 0) + 1
        self.ready = self.backend.status == "ready"  # 语义保持不变（GUI 可能已依赖）
        frontend_pid, frontend_status, frontend_ok = self._frontend_state()
        data = {
            "pid": os.getpid(),
            "started_at": self._supervisor_started_at,  # 语义修正：监督器启动时刻（原先每次写入刷新，见 F-OPS-DEPLOY-11）
            "last_write_at": _iso_now(),  # 本次落盘时刻（新鲜度判据）
            "write_seq": self._write_seq,
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
                "redis": {"status": redis_status, "port": self.redis_port},
                "broker": {"status": broker_status, "port": self.broker_port},
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
        while not self._stop.is_set():
            try:
                self.backend.poll()
                if self.arq:
                    self.arq.poll()
                self.backend.maybe_restart()
                if self.arq:
                    self.arq.maybe_restart()
                if not self.ready and self.backend.status == "ready":
                    print("[prod_runner] 后端就绪 (/api/health 200)")
                self._rotate_logs_if_due()
                self.write_status()
            except Exception as e:  # defensive: supervisor main loop must not exit
                print(f"[prod_runner] 主循环异常（已吞掉，不退出）: {type(e).__name__}: {e}")
            self._stop.wait(3)

    def request_stop(self) -> None:
        """请求主循环退出（控制台处理器调用；shutdown 负责回收子进程）。"""
        self._stop.set()

    # -- 日志轮转 -----------------------------------------------------------
    def _rotate_logs_if_due(self) -> None:
        """按 LOG_ROTATE_CHECK_INTERVAL 节流，做一轮日志维护（轮转 + 保留清理）。

        规格统一读 ``config/log_policy.json``（``utils.log_rotation`` 的同一份策略），
        与桌面壳、ARQ 定时任务完全一致 —— 不再各带一套阈值，也不再只轮转自己的
        ``.out.log``（nginx 日志的轮转不过是「谁碰巧管到」的历史遗留）。
        """
        if time.monotonic() - self._last_log_check < LOG_ROTATE_CHECK_INTERVAL:
            return
        self._last_log_check = time.monotonic()
        policy = load_log_policy(LOG_POLICY_PATH)
        rotate_oversized_logs(LOGS_DIR, max_bytes=policy.rotate_bytes)
        prune_log_files(LOGS_DIR, keep_days=policy.keep_days,
                        max_total_bytes=policy.max_total_bytes)

    # -- 优雅关闭 -----------------------------------------------------------
    def shutdown(self) -> None:
        if self._shutdown_done:
            return
        self._shutdown_done = True
        print("[prod_runner] 正在关闭...")
        failed: list[str] = []
        for svc in (self.arq, self.backend):
            if svc and not svc.kill_tree():
                failed.append(svc.name)
        if failed:
            # H2：不得无条件打印「已停止」——未确认终止的子进程会继续占用端口，
            # 运维依据「已停止」重启会撞上双实例。
            print(f"[prod_runner] 关闭未完成：{', '.join(failed)} 仍在运行，"
                  f"请手工 taskkill /F /T /PID 对应进程（端口可能仍被占用）")
            return
        print("[prod_runner] 已停止(前端 erp-web 为独立服务,不在此处理)")


# 控制台控制处理器回调**必须挂在模块级**。ctypes 回调对象一旦失去引用就被回收，而
# SetConsoleCtrlHandler 只存函数指针 —— 回调被回收后处理器即为悬空指针，Ctrl+C 到达时
# 不再执行 sup.shutdown()，uvicorn 子进程无人回收，成为继续占用 :5002 的孤儿。
#
# 2026-10-02 实测证据：本进程 stdout（logs/erp-prod.log）里「已启动」出现 35 次、
# 「正在关闭」与「已停止」各 0 次 —— shutdown 从未执行过；每次 `nssm restart erp-prod`
# 都会留下上一棵后端进程树，同一端口上堆着两台后端。原写法把回调赋给**局部变量**
# （注释虽写"防止 GC 回收"，但函数返回即失去引用，实测连显式 GC 都不用等就已被回收）。
# 同款正确用法见 services/order/_common.py 的 _pending_tasks。
_console_handler_ref: object | None = None


def _install_signal_handlers(sup: Supervisor) -> None:
    if os.name == "nt":
        try:
            import ctypes

            def _win_handler(ctrl_type):
                # CTRL_C_EVENT=0, CTRL_BREAK_EVENT=1, CTRL_CLOSE_EVENT=2,
                # CTRL_LOGOFF_EVENT=5, CTRL_SHUTDOWN_EVENT=6
                # 先叫醒主循环再杀进程树（OCR 复核换序）：否则 shutdown 的
                # 数秒窗口里主循环 poll() 见子进程退出会 maybe_restart()
                # 把 uvicorn 复活成无人监督的孤儿（占 :5002）。
                sup.request_stop()
                sup.shutdown()
                return True  # 阻止默认终止，让 shutdown 完成

            global _console_handler_ref
            HANDLER_ROUTINE = ctypes.WINFUNCTYPE(ctypes.c_int, ctypes.c_uint)
            _console_handler_ref = HANDLER_ROUTINE(_win_handler)
            ctypes.windll.kernel32.SetConsoleCtrlHandler(_console_handler_ref, True)
        except (OSError, AttributeError):
            pass  # defensive: 异常静默处理,不影响主流程
    else:
        import signal

        def _posix_handler(*_a):
            sup.shutdown()
            sys.exit(0)

        signal.signal(signal.SIGTERM, _posix_handler)
        signal.signal(signal.SIGINT, _posix_handler)


def should_start_internal_arq(argv: list[str], env: Mapping[str, str]) -> bool:
    """是否启动内置 ARQ worker：--no-arq 或显式外部标记时都不启动。"""
    if "--no-arq" in argv:
        return False
    return env.get("ERP_ARQ_EXTERNAL", "").strip() != "1"


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    _load_dotenv()
    # ★ 最早时机打印版本指纹 + 固定输出编码（P0-6）：必须在任何业务日志之前，
    #   且要在 --check 分支之前 —— 自检输出也需要带指纹。
    _init_log_streams()

    api_port = _get_int_env("API_PORT", 5002)
    web_port = _get_int_env("WEB_PORT", 3000)
    workers = _default_workers()

    if "--check" in argv:
        return check(api_port, workers)

    # 分支闸门（P2-101）：NSSM 崩溃自愈直接重启本进程、不经过 server_manager，
    # 若工作区不在 main，会把分支代码跑进生产（AGENTS §6.1-6 事故）。
    # git 不可用/非 git 目录时 guard 自身 fail-open 并留痕；导入失败也不阻断启动。
    try:
        from server_manager.git_guard import check_production_branch, is_warning
        allowed, gate_message = check_production_branch()
        if not allowed:
            print(f'[prod_runner] 生产启动被分支闸门拒绝：{gate_message}', file=sys.stderr)
            return 3
        if is_warning(gate_message):
            print(f'[prod_runner] {gate_message}')
        else:
            print(f'[prod_runner] {gate_message}')
    except Exception as gate_err:  # broad-except: 闸门不可用不得打死生产启动
        print(f'[prod_runner] 分支闸门不可用，已放行：{gate_err}', file=sys.stderr)

    with_arq = should_start_internal_arq(argv, os.environ)
    sup = Supervisor(workers, api_port, web_port, with_arq=with_arq)
    _install_signal_handlers(sup)
    try:
        sup.run()
    except KeyboardInterrupt:
        pass
    finally:
        # 任何退出路径（含未捕获异常）都必须回收子进程树：否则 uvicorn/ARQ 子进程
        # 继续占着 :5002，成为孤儿后端（2026-10-02 实测同端口堆过两台后端）。
        # request_stop() 先叫醒主循环，shutdown() 再杀进程树，顺序不能反。
        sup.request_stop()
        sup.shutdown()
    return 0


if __name__ == "__main__":
    sys.exit(main())
