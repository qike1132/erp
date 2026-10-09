#!/usr/bin/env python
"""ERP 运行看门狗（可观测性 S2）。

为什么需要它
------------
仓库里的 Prometheus / Grafana / OTel / Promtail / Alertmanager 配置全部指向 Docker
主机名（app:5002、nginx:80、loki:3100），但仓库内既无 Dockerfile 也无
docker-compose —— 即这些配置**没有任何运行体**，7 条告警规则是死配置。
/metrics 又要求 METRICS_BEARER_TOKEN，未配置时 fail-closed 返回 503。
结果是三类事故**没有任何对外信号**：

1. 服务静默停摆（尤其 erp-arq —— 它是定时备份的唯一定时器，停摆 = 数据保护静默失效）；
2. 备份停摆 / 备份陈旧（备份目录长时间无新文件）；
3. 磁盘写满（备份与数据库同盘，写满即全站故障）。

本脚本用 Python 标准库实现一个零依赖看门狗，由 Windows 计划任务每 5 分钟调用，
异常时通过**既有告警通道**（BACKUP_ALERT_WEBHOOK_URL / SMTP）通知。

设计约束（重要）
----------------
1. **只用标准库**：看门狗必须在 FastAPI / Redis / PostgreSQL 全挂时仍能运行，
   所以不 import 任何项目模块、不依赖第三方包。
2. **不写数据库**：不复用 BackupAlertService.send_alert —— 其 _log_alert_to_db 会按
   `filename LIKE %task_name%` 把命中的备份记录改成 failed，看门狗不该有这个副作用。
3. **冷却去重**：同一检查项在 WATCHDOG_ALERT_COOLDOWN_MINUTES 内只告警一次，
   状态落在 logs/watchdog_state.json（logs/ 已 gitignore）。
4. **不误判**：`erp-arq` 的 probe_unknown（探测自身失败）与 not_running（worker 确实不在线）
   必须区分，否则会把运维引向重启一个正常的 worker。

退出码
------
0 = 全部检查通过；1 = 有检查项失败（fail/warn）；2 = 脚本自身异常。

用法
----
    python scripts/ops/watchdog.py                 # 跑一轮，异常时告警
    python scripts/ops/watchdog.py --json          # 机器可读输出
    python scripts/ops/watchdog.py --no-alert      # 只检查不通知（排障用）
    python scripts/ops/watchdog.py --expect-services  # 生产模式：NSSM 服务必须 RUNNING
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import smtplib
import ssl
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass
from email.message import EmailMessage
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

OK = "ok"
WARN = "warn"
FAIL = "fail"

DEFAULT_SERVICES = "erp-web,erp-prod,erp-arq,erp-redis,erp-redis-broker"

# 只把真正的归档文件算作「备份」：backups/server 下同时躺着 backup_metrics_*.json、
# *.meta 之类的伴随文件，若一并计入，新鲜度检查会被最近写出的指标文件永远刷绿。
ARCHIVE_SUFFIXES = (".zip.enc", ".zip", ".tar.gz", ".tgz", ".sql.gz", ".gz", ".sql", ".dump", ".7z", ".enc")


@dataclass
class CheckResult:
    """单项检查结果。"""

    key: str
    title: str
    status: str
    detail: str


# ---------------------------------------------------------------- 环境与工具

def load_env_file(path: Path) -> int:
    """把 .env 读进 os.environ（不覆盖已存在的真实环境变量）。

    计划任务启动的进程没有项目环境变量，必须自己加载 .env；
    这里刻意不依赖 python-dotenv，保持零依赖。
    """
    if not path.is_file():
        return 0
    loaded = 0
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.startswith("export "):
            line = line[len("export "):]
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value
            loaded += 1
    return loaded


def env_str(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def env_float(name: str, default: float) -> float:
    try:
        return float(env_str(name) or default)
    except ValueError:
        return default


def env_bool(name: str, default: bool = False) -> bool:
    raw = env_str(name)
    if not raw:
        return default
    return raw.lower() in {"1", "true", "yes", "on"}


def _web_url_scheme() -> str:
    """web 入口探针的 scheme：取 WEB_HEALTH_SCHEME，默认 http（与 prod_runner 同源）。"""
    return env_str("WEB_HEALTH_SCHEME", "http").lower() or "http"


def _ssl_context_for(url: str) -> ssl.SSLContext | None:
    """https 时容忍自签/过期证书——本机回环探针只判「端口有人在服务」，不做证书链校验。

    否则 erp-web/nginx 给 :3000 上 TLS 后探针会因自签证书一律失败，
    制造「服务正常却报 web_entry=fail」的假故障（2026-10-09 新机事故的第四类）。
    """
    if not url.lower().startswith("https://"):
        return None
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx


def http_get(url: str, timeout: float) -> tuple[int, str]:
    """返回 (status_code, body[:4096])；HTTP 错误码也正常返回而不抛异常。"""
    request = urllib.request.Request(url, headers={"User-Agent": "erp-watchdog/1.0"})
    try:
        with urllib.request.urlopen(request, timeout=timeout, context=_ssl_context_for(url)) as response:
            return response.status, response.read(4096).decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read(4096).decode("utf-8", "replace")


# ---------------------------------------------------------------- 各项检查

def check_http(key: str, title: str, url: str, timeout: float) -> CheckResult:
    """通用 HTTP 探活：200 视为正常。"""
    try:
        code, body = http_get(url, timeout)
    except (urllib.error.URLError, OSError, ValueError) as exc:
        return CheckResult(key, title, FAIL, f"请求失败: {type(exc).__name__}: {exc}")
    snippet = " ".join(body.split())[:160]
    if code == 200:
        return CheckResult(key, title, OK, f"HTTP 200 {snippet}")
    return CheckResult(key, title, FAIL, f"HTTP {code} {snippet}")


def check_arq(base_url: str, timeout: float) -> CheckResult:
    """ARQ worker 三态探针（契约见 fastapi_app/core/health.py 的 /api/health/arq）。"""
    key, title = "arq_worker", "ARQ worker 存活（定时备份的唯一定时器）"
    try:
        code, body = http_get(f"{base_url}/api/health/arq", timeout)
    except (urllib.error.URLError, OSError, ValueError) as exc:
        return CheckResult(key, title, FAIL, f"探测失败: {type(exc).__name__}: {exc}")
    if code == 200:
        return CheckResult(key, title, OK, body[:200])
    try:
        state = str(json.loads(body).get("status", ""))
    except (json.JSONDecodeError, AttributeError):
        state = ""
    if state == "not_running":
        return CheckResult(key, title, FAIL, f"worker 确实不在线（备份调度已停摆）: {body[:200]}")
    if state == "probe_unknown":
        return CheckResult(key, title, WARN, f"探测自身失败（查 broker，勿判定 worker 已死）: {body[:200]}")
    return CheckResult(key, title, FAIL, f"HTTP {code} {body[:200]}")


def check_backup_freshness(backup_dir: Path, max_age_minutes: float) -> CheckResult:
    """备份新鲜度：备份目录中最新的归档文件不得超过 max_age_minutes。"""
    key, title = "backup_freshness", "备份新鲜度"
    if not backup_dir.is_dir():
        return CheckResult(key, title, FAIL, f"备份目录不存在: {backup_dir}")
    newest_mtime, newest_name, count = 0.0, "", 0
    for path in backup_dir.rglob("*"):
        if not path.is_file() or not path.name.endswith(ARCHIVE_SUFFIXES):
            continue
        count += 1
        try:
            mtime = path.stat().st_mtime
        except OSError:
            continue
        if mtime > newest_mtime:
            newest_mtime, newest_name = mtime, path.name
    if not newest_name:
        return CheckResult(key, title, FAIL, f"备份目录为空: {backup_dir}")
    age_minutes = (time.time() - newest_mtime) / 60.0
    detail = f"最新 {newest_name}（{age_minutes:.0f} 分钟前，共 {count} 个归档）"
    if age_minutes > max_age_minutes:
        return CheckResult(key, title, FAIL, f"{detail}；超过阈值 {max_age_minutes:.0f} 分钟")
    return CheckResult(key, title, OK, detail)


def check_disk_free(min_free_gb: float, drives: tuple[str, ...] = ("C:", "D:")) -> CheckResult:
    """磁盘剩余空间：任一盘低于阈值即失败。"""
    key, title = "disk_free", "磁盘剩余空间"
    problems: list[str] = []
    observed: list[str] = []
    for drive in drives:
        try:
            usage = shutil.disk_usage(f"{drive}\\")
        except OSError as exc:
            problems.append(f"{drive} 不可读（{type(exc).__name__}）")
            continue
        free_gb = usage.free / (1024 ** 3)
        observed.append(f"{drive} 剩余 {free_gb:.1f}GB")
        if free_gb < min_free_gb:
            problems.append(f"{drive} 剩余 {free_gb:.1f}GB < 阈值 {min_free_gb:.1f}GB")
    if problems:
        return CheckResult(key, title, FAIL, "; ".join(problems))
    return CheckResult(key, title, OK, "; ".join(observed))


def _service_state(name: str, timeout: float) -> str:
    """用 sc.exe 读 Windows 服务状态；返回 RUNNING / STOPPED / 未注册 / 查询失败。"""
    try:
        proc = subprocess.run(
            ["sc.exe", "query", name],
            capture_output=True,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return f"查询失败({type(exc).__name__})"
    text = (proc.stdout or b"").decode("utf-8", "replace")
    if proc.returncode != 0 and "STATE" not in text:
        return "未注册"
    for line in text.splitlines():
        if "STATE" in line:
            return "RUNNING" if "RUNNING" in line else "STOPPED"
    return "未知"


def check_services(services: list[str], timeout: float) -> CheckResult:
    """NSSM 服务存活（仅生产模式启用，见 --expect-services）。"""
    key, title = "services", "NSSM 服务存活"
    stopped: list[str] = []
    observed: list[str] = []
    for name in services:
        state = _service_state(name, timeout)
        observed.append(f"{name}={state}")
        if state != "RUNNING":
            stopped.append(f"{name}({state})")
    if stopped:
        return CheckResult(key, title, FAIL, f"未运行: {', '.join(stopped)}")
    return CheckResult(key, title, OK, ", ".join(observed))


def run_checks(options: argparse.Namespace) -> list[CheckResult]:
    """按顺序跑完全部检查。任何单项异常都不应中断整轮检查。"""
    timeout = options.timeout
    results = [
        check_http("backend_health", "后端 /api/health", f"{options.backend_url}/api/health", timeout),
        check_http("backend_ready", "后端就绪 /api/health/ready", f"{options.backend_url}/api/health/ready", timeout),
        check_arq(options.backend_url, timeout),
        check_http("web_entry", "Web 入口存活", f"{options.web_url}/nginx-health", timeout),
        check_backup_freshness(options.backup_dir, options.backup_max_age_minutes),
        check_disk_free(options.min_free_gb),
    ]
    if options.expect_services:
        results.append(check_services(options.services, timeout))
    return results


# ---------------------------------------------------------------- 告警

def load_state(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def save_state(path: Path, state: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def select_alerts(results: list[CheckResult], state: dict, cooldown_minutes: float) -> list[CheckResult]:
    """挑出需要通知的检查项：状态非 ok 且已过冷却期；恢复正常则清掉冷却记录。"""
    now = time.time()
    alerts = state.setdefault("alerts", {})
    selected: list[CheckResult] = []
    for result in results:
        if result.status == OK:
            alerts.pop(result.key, None)
            continue
        last_sent = float(alerts.get(result.key, {}).get("last_sent", 0))
        if now - last_sent >= cooldown_minutes * 60:
            selected.append(result)
            alerts[result.key] = {"last_sent": now, "status": result.status, "detail": result.detail}
    return selected


def _alert_payload(alerts: list[CheckResult], results: list[CheckResult]) -> dict:
    worst = FAIL if any(r.status == FAIL for r in alerts) else WARN
    return {
        "task_name": "watchdog",
        "task_type": "health_check",
        "severity": "critical" if worst == FAIL else "warning",
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "hostname": os.environ.get("COMPUTERNAME", "unknown"),
        "error": "; ".join(f"[{a.key}] {a.detail}" for a in alerts),
        "checks": [asdict(r) for r in results],
    }


def send_webhook(payload: dict, timeout: float) -> bool:
    url = env_str("BACKUP_ALERT_WEBHOOK_URL")
    if env_str("BACKUP_ALERT_WEBHOOK_ENABLED").lower() != "true" or not url:
        return False
    try:
        headers = json.loads(env_str("BACKUP_ALERT_WEBHOOK_HEADERS", "{}") or "{}")
    except json.JSONDecodeError:
        headers = {}
    headers.setdefault("Content-Type", "application/json")
    request = urllib.request.Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return 200 <= response.status < 300
    except (urllib.error.URLError, OSError) as exc:
        print(f"[watchdog] webhook 发送失败: {type(exc).__name__}: {exc}", file=sys.stderr)
        return False


def send_email(payload: dict, timeout: float) -> bool:
    if not env_bool("BACKUP_ALERT_EMAIL_ENABLED"):
        return False
    host = env_str("BACKUP_ALERT_SMTP_HOST")
    recipients = [x.strip() for x in env_str("BACKUP_ALERT_EMAIL_TO").split(",") if x.strip()]
    if not host or not recipients:
        return False
    message = EmailMessage()
    prefix = env_str("BACKUP_ALERT_EMAIL_SUBJECT_PREFIX", "[ERP Alert]")
    message["Subject"] = f"{prefix} 看门狗告警（{payload['severity']}）"
    message["From"] = env_str("BACKUP_ALERT_EMAIL_FROM") or env_str("BACKUP_ALERT_SMTP_USERNAME")
    message["To"] = ", ".join(recipients)
    body = [f"主机: {payload['hostname']}", f"时间: {payload['timestamp']}", ""]
    body += [f"- [{c['key']}] {c['status']}: {c['detail']}" for c in payload["checks"]]
    message.set_content("\n".join(body))
    try:
        with smtplib.SMTP(host, int(env_float("BACKUP_ALERT_SMTP_PORT", 587)), timeout=timeout) as smtp:
            smtp.starttls()
            username = env_str("BACKUP_ALERT_SMTP_USERNAME")
            if username:
                smtp.login(username, env_str("BACKUP_ALERT_SMTP_PASSWORD"))
            smtp.send_message(message)
        return True
    except (OSError, smtplib.SMTPException) as exc:
        print(f"[watchdog] 邮件发送失败: {type(exc).__name__}: {exc}", file=sys.stderr)
        return False


def notify(alerts: list[CheckResult], results: list[CheckResult], timeout: float) -> list[str]:
    """按配置的通道发告警，返回实际使用的通道名。"""
    payload = _alert_payload(alerts, results)
    used: list[str] = []
    if send_webhook(payload, timeout):
        used.append("webhook")
    if send_email(payload, timeout):
        used.append("email")
    return used


# ---------------------------------------------------------------- 输出与入口

def log_line(path: Path, text: str) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {text}\n")
    except OSError as exc:
        print(f"[watchdog] 写日志失败: {exc}", file=sys.stderr)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="ERP 运行看门狗（可观测性 S2）")
    parser.add_argument("--json", action="store_true", help="以 JSON 输出检查结果")
    parser.add_argument("--no-alert", action="store_true", help="只检查，不发送告警（不影响退出码）")
    parser.add_argument("--verbose", action="store_true", help="打印全部检查项，含通过项")
    parser.add_argument("--expect-services", action="store_true", help="要求 NSSM 服务处于 RUNNING")
    parser.add_argument("--backend-url", default=env_str("WATCHDOG_BACKEND_URL", "http://127.0.0.1:5002"))
    parser.add_argument("--web-url", default=env_str("WATCHDOG_WEB_URL", f"{_web_url_scheme()}://127.0.0.1:3000"))
    parser.add_argument("--timeout", type=float, default=env_float("WATCHDOG_TIMEOUT_SECONDS", 10.0))
    return parser


def build_options(argv: list[str] | None = None) -> argparse.Namespace:
    options = build_parser().parse_args(argv)
    backup_dir = env_str("WATCHDOG_BACKUP_DIR") or env_str("BACKUP_DIR", "backups/server")
    options.backup_dir = (ROOT / backup_dir) if not Path(backup_dir).is_absolute() else Path(backup_dir)
    options.backup_max_age_minutes = env_float("WATCHDOG_BACKUP_MAX_AGE_MINUTES", 90.0)
    min_free = env_float("WATCHDOG_MIN_FREE_SPACE_GB", 0.0)
    options.min_free_gb = max(min_free, env_float("BACKUP_MIN_FREE_SPACE_GB", 10.0), 20.0)
    options.services = [s.strip() for s in env_str("WATCHDOG_SERVICES", DEFAULT_SERVICES).split(",") if s.strip()]
    options.expect_services = options.expect_services or env_bool("WATCHDOG_EXPECT_SERVICES", False)
    options.cooldown_minutes = env_float("WATCHDOG_ALERT_COOLDOWN_MINUTES", 30.0)
    options.state_file = ROOT / env_str("WATCHDOG_STATE_FILE", "logs/watchdog_state.json")
    options.log_file = ROOT / env_str("WATCHDOG_LOG_FILE", "logs/watchdog.log")
    return options


def main(argv: list[str] | None = None) -> int:
    load_env_file(ROOT / ".env")
    options = build_options(argv)
    results = run_checks(options)
    failed = [r for r in results if r.status != OK]

    state = load_state(options.state_file)
    state["last_run"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    alerts = [] if options.no_alert else select_alerts(results, state, options.cooldown_minutes)
    channels = notify(alerts, results, options.timeout) if alerts else []
    save_state(options.state_file, state)

    summary = f"检查 {len(results)} 项，异常 {len(failed)} 项，告警 {len(alerts)} 项，通道 {channels or '无'}"
    log_line(options.log_file, summary + " | " + "; ".join(f"{r.key}={r.status}" for r in results))

    if options.json:
        print(json.dumps({"summary": summary, "results": [asdict(r) for r in results]}, ensure_ascii=False, indent=2))
    else:
        print(f"[watchdog] {summary}")
        for result in results if options.verbose else failed:
            print(f"  [{result.status.upper():4}] {result.key}: {result.title} — {result.detail}")
    return 1 if failed else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:  # 脚本自身异常：退出码 2，计划任务可据此区分「检查失败」与「看门狗坏了」
        print(f"[watchdog] 自身异常: {type(exc).__name__}: {exc}", file=sys.stderr)
        sys.exit(2)
