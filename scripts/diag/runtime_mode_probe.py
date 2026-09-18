"""运行模式探针：判定 5002 上跑的是 dev 还是 prod，并权威判定 ARQ worker 是否在线。

为什么需要这个脚本：`logs/prod_runner.json` 只是一条**声明**，它会谎报。如果它声明 prod
而实际跑着 dev 单 worker，定时任务（备份/告警）会静默不执行，而端口探测完全看不出来。

════════════════════════════════════════════════════════════════════════════
⛔ 本脚本的历史缺陷与修复（2026-09-17 审计 S3，务必先读再改）
════════════════════════════════════════════════════════════════════════════
旧版把「5002 监听进程的 cmdline」当作**唯一可靠判据**，并据此判 ARQ：

    verdict = "not running"                      # 初值
    try:  cmdline = proc.cmdline()               # ← NSSM 提权派生进程读不到，抛 psutil.Error
    except psutil.Error as exc: detail.append(...)   # ← 异常只记 detail，verdict 保持初值
    report["arq_worker_processes"] = [... if "arq" in cmdline ...]   # ← cmdline 读不到 ⇒ 恒为空

后果：对**正在运行**的 ARQ 报「not running」（假阴性）。而真宕机时输出**一模一样**
⇒ 运维无法区分「真宕机」与「探针误报」，该工具本身成了误导源。

判活铁律（改本文件时必须遵守）：
  1. **ARQ 判活只认官方哨兵键**（`queue_name + ':health-check'`，见
     `fastapi_app/core/arq_app.py::check_worker_health`），端口在 **broker 实例**上，
     **不是** cache 实例（本机 broker=:6380、cache=:6379；在 cache 上查该键必然是 -2）。
  2. **「读不到」绝不能折算成「没在运行」**：三态显式区分
     `running` / `not_running` / `probe_unknown`。
  3. 一切判定失败都要带**可读原因**，不允许静默退化成默认值。

════════════════════════════════════════════════════════════════════════════
判据（前端）
════════════════════════════════════════════════════════════════════════════
生产 = nginx 服务 dist：`Server: nginx` + 首页不含 `@vite/client` 且不含 `/src/main.ts`。
⚠️ 不要用「3000 端口归属进程」判定：dev 模式下 psutil 会把 nginx 与 node(vite)
   同时列为监听者（句柄被继承），据此会误判成生产。

用法（需 psutil，用系统 Python）：
  C:/Users/Administrator/AppData/Local/Programs/Python/Python313/python.exe \
      scripts/diag/runtime_mode_probe.py

输出：stdout **纯 JSON**（`scripts/capture_baseline.py:68` 依赖顶层 `verdict` 键）；
      告警一律走 stderr。只读，不做任何修改。
"""

from __future__ import annotations

import json
import os
import re
import socket
import subprocess
import sys
import urllib.error
import urllib.request
from datetime import datetime

try:
    import psutil
except ImportError:  # pragma: no cover
    print("需要 psutil：请用系统 Python 运行（managed venv 未装 psutil）", file=sys.stderr)
    raise SystemExit(2)

API_PORT = 5002
WEB_PORT = 3000
REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
PROD_STATE = os.path.join(REPO_ROOT, "logs", "prod_runner.json")
ENV_FILE = os.path.join(REPO_ROOT, ".env")

# ARQ 哨兵键：arq.constants.default_queue_name + health_check_key_suffix
ARQ_QUEUE_NAME = "arq:queue"
ARQ_HEALTH_KEY = ARQ_QUEUE_NAME + ":health-check"
# 与 arq_app.WorkerSettings.health_check_interval 保持一致（TTL = interval + 1）
ARQ_HEALTH_INTERVAL = 60

_TS = "%Y-%m-%d %H:%M:%S"


# ───────────────────────────── 小工具 ─────────────────────────────

def listening_pids(port: int) -> list[int]:
    """netstat 取监听 pid。仅作旁证：该结果本身可能包含句柄被继承的进程。"""
    lines = subprocess.run(
        ["netstat", "-ano"], capture_output=True, text=True, errors="ignore"
    ).stdout.splitlines()
    pids: set[int] = set()
    for line in lines:
        if f":{port}" in line and "LISTENING" in line:
            parts = line.split()
            if parts and parts[-1].isdigit():
                pids.add(int(parts[-1]))
    return sorted(pids)


def _parse_env(path: str) -> dict[str, str]:
    """极简 .env 解析（不引入 dotenv 依赖，避免探针受应用导入链影响）。"""
    out: dict[str, str] = {}
    if not os.path.exists(path):
        return out
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            for raw in fh:
                line = raw.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                out[k.strip()] = v.strip().strip('"').strip("'")
    except OSError:
        pass
    return out


def _redis_target_from_env(env: dict[str, str]) -> dict[str, object]:
    """复刻 arq_app._build_redis_settings 的取值顺序：REDIS_BROKER_URL 优先。"""
    dsn = env.get("REDIS_BROKER_URL", "")
    if dsn:
        m = re.match(r"rediss?://(?:[^@/]*@)?([^:/]+)(?::(\d+))?(?:/(\d+))?", dsn)
        if m:
            userinfo = dsn.split("://", 1)[1].split("@", 1)[0] if "@" in dsn else ""
            password = ""
            if ":" in userinfo:
                password = userinfo.split(":", 1)[1]
            elif userinfo:
                password = userinfo
            return {
                "source": "REDIS_BROKER_URL",
                "host": m.group(1) or "127.0.0.1",
                "port": int(m.group(2) or 6379),
                "db": int(m.group(3) or 0),
                "password": password,
            }
    return {
        "source": "REDIS_HOST/REDIS_PORT/REDIS_PASSWORD",
        "host": env.get("REDIS_HOST") or "127.0.0.1",
        "port": int(env.get("REDIS_PORT") or 6379),
        "db": int(env.get("REDIS_DB") or 0),
        "password": env.get("REDIS_PASSWORD", ""),
    }


def _resp(sock: socket.socket, *args: str) -> None:
    payload = ("*%d\r\n" % len(args)).encode()
    for a in args:
        b = a.encode("utf-8")
        payload += b"$%d\r\n%s\r\n" % (len(b), b)
    sock.sendall(payload)


def _resp_read(sock: socket.socket, timeout: float = 4.0) -> str:
    sock.settimeout(timeout)
    buf = b""
    while not buf.endswith(b"\r\n"):
        chunk = sock.recv(4096)
        if not chunk:
            break
        buf += chunk
    return buf.decode("utf-8", "replace")


def probe_arq(env: dict[str, str]) -> dict[str, object]:
    """按官方哨兵键判活。三态：running / not_running / probe_unknown。"""
    tgt = _redis_target_from_env(env)
    info: dict[str, object] = {
        "method": "ARQ 官方健康哨兵键（与 core/arq_app.check_worker_health 同一契约）",
        "key": ARQ_HEALTH_KEY,
        "broker_source": tgt["source"],
        "broker": "%s:%s/%s" % (tgt["host"], tgt["port"], tgt["db"]),
        "expected_ttl_upper_bound": ARQ_HEALTH_INTERVAL + 1,
    }
    sock = None
    try:
        sock = socket.create_connection((str(tgt["host"]), int(tgt["port"])), timeout=4)
        if tgt["password"]:
            _resp(sock, "AUTH", str(tgt["password"]))
            auth = _resp_read(sock)
            if not auth.startswith("+OK"):
                info.update({
                    "verdict": "probe_unknown",
                    "message": "broker 认证失败（%s）——无法据此判断 ARQ 是否在运行" % auth.strip()[:40],
                })
                return info
        if int(tgt["db"] or 0):
            _resp(sock, "SELECT", str(int(tgt["db"])))
            _resp_read(sock)

        _resp(sock, "TTL", ARQ_HEALTH_KEY)
        ttl_raw = _resp_read(sock).strip()
        _resp(sock, "GET", ARQ_HEALTH_KEY)
        get_raw = _resp_read(sock).strip()

        ttl = int(ttl_raw[1:]) if ttl_raw.startswith(":") else None
        info["ttl_seconds"] = ttl

        if get_raw.startswith("$-1") or ttl == -2:
            info.update({
                "verdict": "not_running",
                "message": "哨兵键不存在 ⇒ ARQ worker 未在线（key absent, TTL=%s）" % ttl,
            })
            return info

        # 提取心跳正文
        body = get_raw
        if body.startswith("$"):
            nl = body.find("\r\n")
            body = body[nl + 2:]
        body = body.rstrip("\r\n")
        info["heartbeat"] = body

        m = re.search(r"([A-Z][a-z]{2}-\d{2} \d{2}:\d{2}:\d{2})", body)
        if m:
            info["heartbeat_at"] = m.group(1)
            try:
                hb = datetime.strptime(
                    "%d-%s" % (datetime.now().year, m.group(1)), "%Y-%b-%d %H:%M:%S"
                )
                info["heartbeat_age_seconds"] = round(
                    (datetime.now() - hb).total_seconds(), 1
                )
            except ValueError:
                pass
        for key, field in (("j_complete", "j_complete"), ("j_failed", "j_failed"),
                           ("j_retried", "j_retried"), ("j_ongoing", "j_ongoing"),
                           ("queued", "queued")):
            mm = re.search(r"\b%s=(\d+)" % key, body)
            if mm:
                info[field] = int(mm.group(1))

        info.update({
            "verdict": "running",
            "message": "ARQ worker 在线（心跳 %s）" % body,
        })
        return info
    except OSError as exc:
        info.update({
            "verdict": "probe_unknown",
            "message": "无法连接 broker（%s: %s）——**不能**据此判定 ARQ 未运行"
                       % (type(exc).__name__, exc),
        })
        return info
    finally:
        if sock is not None:
            try:
                sock.close()
            except OSError:
                pass


def probe_frontend() -> dict[str, object]:
    """前端是否由 nginx 服务 dist（四条硬判据，禁用端口归属进程判定）。"""
    out: dict[str, object] = {}
    # urllib 默认会读 HTTP_PROXY 环境变量把 127.0.0.1 走代理 → 显式禁用
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def fetch(path: str, method: str = "GET") -> tuple[int, dict[str, str], str]:
        req = urllib.request.Request("http://127.0.0.1:%d%s" % (WEB_PORT, path), method=method)
        with opener.open(req, timeout=8) as resp:
            return resp.status, dict(resp.headers), resp.read().decode("utf-8", "replace")

    try:
        _, headers, body = fetch("/")
        out["status"] = 200
        out["server_header"] = headers.get("Server") or headers.get("server")
        out["has_vite_client"] = "@vite/client" in body
        out["has_src_main_ts"] = "/src/main.ts" in body
        out["has_hashed_assets"] = "/assets/index-" in body
    except (urllib.error.URLError, OSError, ValueError) as exc:
        out["verdict"] = "probe_unknown"
        out["message"] = "无法请求 :%d/（%s: %s）" % (WEB_PORT, type(exc).__name__, exc)
        return out

    is_prod = (
        (out.get("server_header") or "").lower() == "nginx"
        and not out["has_vite_client"]
        and not out["has_src_main_ts"]
    )
    out["verdict"] = "production (nginx serving dist)" if is_prod else "development (vite dev server)"
    out["is_production"] = is_prod
    return out


def ancestor_names(proc: "psutil.Process", limit: int = 8) -> list[str]:
    """向上走父链取进程名。**不读 cmdline** —— 因为 NSSM 提权派生进程的 cmdline 读不到，
    但父链与进程名是可读的，因此它是 cmdline 不可用时唯一可靠的替代判据。"""
    names: list[str] = []
    cur = proc
    for _ in range(limit):
        try:
            par = cur.parent()
        except psutil.Error:
            break
        if par is None:
            break
        try:
            names.append(par.name())
        except psutil.Error:
            names.append("<unknown>")
        cur = par
    return names


def python_child_count(proc: "psutil.Process") -> int:
    """直接子进程中 python 解释器的数量。
    prod（uvicorn --workers N）→ master 下挂 N 个 worker；dev 单 worker → 0。"""
    n = 0
    try:
        for c in proc.children(recursive=False):
            try:
                if "python" in c.name().lower():
                    n += 1
            except psutil.Error:
                continue
    except psutil.Error:
        pass
    return n


def classify(cmdline: list[str]) -> str:
    joined = " ".join(cmdline)
    if "uvicorn" not in joined:
        return "unknown (监听进程非 uvicorn)"
    has_reload = "--reload" in cmdline
    has_workers = "--workers" in cmdline
    if has_reload and not has_workers:
        return "dev (single worker, no ARQ worker)"
    if has_workers and not has_reload:
        return "prod (multi worker)"
    return f"suspicious (reload={has_reload}, workers={has_workers})"


def main() -> int:
    warnings: list[str] = []
    report: dict[str, object] = {
        "checked_at": datetime.now().strftime(_TS),
        "api_port": API_PORT,
        "web_port": WEB_PORT,
    }

    # ── 后端 5002：cmdline 判定（读不到 → probe_unknown，绝不折算成 not running） ──
    pids = listening_pids(API_PORT)
    report["api_listening_pids"] = pids
    if not pids:
        verdict = "not_running (5002 无监听进程)"
        report["api_mode_evidence"] = "netstat 未发现 5002 监听者"
    else:
        verdict = "probe_unknown (无法读取监听进程信息)"
        evidence: list[str] = []
        modes: list[str] = []
        tree_signals: list[dict[str, object]] = []
        detail: list[dict[str, object]] = []
        for pid in pids:
            entry: dict[str, object] = {"pid": pid}
            workers = 0
            try:
                proc = psutil.Process(pid)
                entry["started"] = datetime.fromtimestamp(proc.create_time()).strftime(_TS)
                entry["ppid"] = proc.ppid()
                try:
                    entry["parent"] = proc.parent().name() if proc.parent() else None
                except psutil.Error:
                    entry["parent"] = None
                # 与 cmdline 无关的两条判据：父链是否含 nssm、master 下挂几个 python worker
                try:
                    chain = ancestor_names(proc)
                    entry["ancestor_chain"] = chain
                    entry["supervised_by_nssm"] = "nssm.exe" in [n.lower() for n in chain]
                except psutil.Error:
                    entry["ancestor_chain"] = None
                    entry["supervised_by_nssm"] = None
                workers = python_child_count(proc)
                entry["python_worker_children"] = workers
                tree_signals.append({
                    "pid": pid,
                    "nssm": entry.get("supervised_by_nssm"),
                    "workers": workers,
                })
                try:
                    cmdline = proc.cmdline()
                    entry["cmdline"] = " ".join(cmdline)
                    entry["mode"] = classify(cmdline)
                    modes.append(str(entry["mode"]))
                except psutil.Error as exc:
                    # 关键：NSSM 提权派生进程的 cmdline 对非提权读取者不可见。
                    # 这是「读不到」，与「没在运行」是两件事，必须显式区分。
                    entry["cmdline"] = None
                    entry["cmdline_error"] = (
                        "cmdline 不可读（%s）——常见于 NSSM 提权派生进程；"
                        "该现象不代表进程未运行" % type(exc).__name__
                    )
                    evidence.append("pid=%d cmdline 不可读（%s）" % (pid, type(exc).__name__))
            except psutil.Error as exc:
                entry["error"] = "%s: %s" % (type(exc).__name__, exc)
                evidence.append("pid=%d 查询失败（%s）" % (pid, type(exc).__name__))
            detail.append(entry)
        report["api_processes"] = detail

        if modes:
            # ① cmdline 可读 → 用它（最强）
            verdict = modes[0] if len(set(modes)) == 1 else "suspicious (%s)" % modes
            evidence.append("cmdline 判定=%s" % modes)
        elif tree_signals:
            # ② cmdline 不可读 → 退回进程树判据（父链 nssm + python 子进程数）
            nssm_all = all(t.get("nssm") for t in tree_signals)
            workers_max = max(int(t.get("workers") or 0) for t in tree_signals)
            if nssm_all and workers_max >= 2:
                verdict = "prod (multi worker, 判定依据=进程树)"
                evidence.append("父链含 nssm.exe 且 master 下挂 %d 个 worker" % workers_max)
            elif not any(t.get("nssm") for t in tree_signals) and workers_max == 0:
                verdict = "dev (single worker, no ARQ worker, 判定依据=进程树)"
                evidence.append("父链无 nssm.exe 且 master 无 python 子进程（单 worker）")
            else:
                verdict = "probe_unknown (进程树判据不足以定论)"
                evidence.append(
                    "进程树信号=%s（cmdline 不可读，且 nssm/worker 组合不唯一）" % tree_signals
                )
        report["api_mode_evidence"] = "; ".join(evidence)
    report["verdict"] = verdict
    report["api_mode"] = verdict

    # ── 前端 3000：四条硬判据（端口归属只能当旁证） ──
    report["web_3000_listen_count"] = len(listening_pids(WEB_PORT))
    report["frontend"] = probe_frontend()

    # ── ARQ：官方哨兵键判活 ──
    env = _parse_env(ENV_FILE)
    arq = probe_arq(env)
    report["arq"] = arq

    # ── prod_runner.json：只是声明，必须交叉验证 ──
    if os.path.exists(PROD_STATE):
        report["prod_runner_json_mtime"] = datetime.fromtimestamp(
            os.path.getmtime(PROD_STATE)
        ).strftime(_TS)
        try:
            with open(PROD_STATE, encoding="utf-8") as fh:
                state = json.load(fh)
            report["prod_runner_claims"] = {
                "mode": state.get("mode"),
                "workers": state.get("workers"),
                # ⚠️ started_at 是"本次写盘时刻"，不是进程启动时刻（见审计 H3）
                "started_at": state.get("started_at"),
                "started_at_semantics": "写盘时刻（非进程启动时刻），勿用于判断是否刚重启",
                "backend_pid": (state.get("services") or {}).get("backend", {}).get("pid"),
                "arq_pid": (state.get("services") or {}).get("arq", {}).get("pid"),
            }
        except (OSError, ValueError) as exc:
            report["prod_runner_json_error"] = str(exc)
        claims = report.get("prod_runner_claims") or {}
        if isinstance(claims, dict):
            report["claimed_pids_alive"] = {
                key: psutil.pid_exists(pid)
                for key, pid in (
                    ("backend_pid_alive", claims.get("backend_pid")),
                    ("arq_pid_alive", claims.get("arq_pid")),
                )
                if isinstance(pid, int)
            }

    # ── 告警（stderr，保持 stdout 纯 JSON） ──
    if str(verdict).startswith("dev"):
        warnings.append(
            "5002 正以 dev 单 worker 运行：ARQ worker 未由此链路启动 → 备份/告警等定时任务不会执行"
        )
    if str(verdict).startswith("probe_unknown"):
        warnings.append(
            "后端模式判定为 probe_unknown（读不到监听进程 cmdline，常见于 NSSM 提权派生进程）："
            "这**不是**「未运行」。请改用真实 HTTP 请求或日志写入交叉验证。"
        )
    arq_verdict = str(arq.get("verdict"))
    if arq_verdict == "not_running":
        warnings.append("ARQ worker 未运行（哨兵键缺失）→ 定时备份/异步任务不会执行")
    elif arq_verdict == "probe_unknown":
        warnings.append(
            "ARQ 判活为 probe_unknown（%s）：**不能**据此认定 ARQ 未运行" % arq.get("message")
        )
    fail = arq.get("j_failed")
    if isinstance(fail, int) and fail > 0:
        warnings.append("ARQ 存在失败任务：j_failed=%d" % fail)
    if warnings:
        report["warnings"] = warnings

    print(json.dumps(report, ensure_ascii=False, indent=2))
    for w in warnings:
        print("[WARN] %s" % w, file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
