"""运行模式探针：判定 5002 上跑的是 dev 还是 prod。

为什么需要这个脚本：`logs/prod_runner.json` 只在 prod 模式下被写；如果它声明 prod
而实际跑着 dev 单 worker，定时任务（备份/告警）会静默不执行，而端口探测完全看不出来。
唯一可靠判据 = 5002 监听进程的 cmdline。

判据：
  - 含 `--reload`、无 `--workers`  -> dev 单 worker（GUI 服务器管理器直接拉起）
  - 父进程链 services.exe -> nssm -> prod_runner -> uvicorn + `--workers 4` -> prod

用法（需 psutil，用系统 Python）：
  C:/Users/Administrator/AppData/Local/Programs/Python/Python313/python.exe \
      scripts/diag/runtime_mode_probe.py

只读，不做任何修改。
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
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


def listening_pids(port: int) -> list[int]:
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


def classify(cmdline: list[str]) -> str:
    joined = " ".join(cmdline)
    if "uvicorn" not in joined:
        return "unknown"
    has_reload = "--reload" in cmdline
    has_workers = "--workers" in cmdline
    if has_reload and not has_workers:
        return "dev (single worker, no ARQ worker)"
    if has_workers and not has_reload:
        return "prod (multi worker)"
    return f"suspicious (reload={has_reload}, workers={has_workers})"


def main() -> int:
    report: dict[str, object] = {
        "checked_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "api_port": API_PORT,
    }

    pids = listening_pids(API_PORT)
    report["api_listening_pids"] = pids
    report["web_3000_listen_count"] = len(listening_pids(WEB_PORT))

    verdict = "not running"
    detail: list[dict[str, object]] = []
    for pid in pids:
        try:
            proc = psutil.Process(pid)
            cmdline = proc.cmdline()
            parent = proc.parent()
            entry = {
                "pid": pid,
                "started": datetime.fromtimestamp(proc.create_time()).strftime("%Y-%m-%d %H:%M:%S"),
                "cmdline": " ".join(cmdline),
                "ppid": proc.ppid(),
                "parent": parent.name() if parent else None,
                "mode": classify(cmdline),
            }
            detail.append(entry)
            verdict = str(entry["mode"])
        except psutil.Error as exc:
            detail.append({"pid": pid, "error": str(exc)})

    report["api_processes"] = detail
    report["verdict"] = verdict

    # prod_runner.json 只是一条声明，必须与 verdict 交叉验证
    if os.path.exists(PROD_STATE):
        report["prod_runner_json_mtime"] = datetime.fromtimestamp(
            os.path.getmtime(PROD_STATE)
        ).strftime("%Y-%m-%d %H:%M:%S")
        try:
            with open(PROD_STATE, encoding="utf-8") as fh:
                state = json.load(fh)
            report["prod_runner_claims"] = {
                "mode": state.get("mode"),
                "workers": state.get("workers"),
                "started_at": state.get("started_at"),
                "backend_pid": (state.get("services") or {}).get("backend", {}).get("pid"),
                "arq_pid": (state.get("services") or {}).get("arq", {}).get("pid"),
            }
        except (OSError, ValueError) as exc:
            report["prod_runner_json_error"] = str(exc)

    # 检查声明的 pid 是否仍然存活 —— 不存活说明 prod_runner.json 是失效声明
    claims = report.get("prod_runner_claims") or {}
    if isinstance(claims, dict):
        alive = {
            key: psutil.pid_exists(pid)
            for key, pid in (
                ("backend_pid_alive", claims.get("backend_pid")),
                ("arq_pid_alive", claims.get("arq_pid")),
            )
            if isinstance(pid, int)
        }
        report["claimed_pids_alive"] = alive

    report["arq_worker_processes"] = [
        p.info["pid"]
        for p in psutil.process_iter(["pid", "cmdline"])
        if "arq" in " ".join(p.info.get("cmdline") or []).lower()
    ]

    print(json.dumps(report, ensure_ascii=False, indent=2))

    if str(verdict).startswith("dev"):
        print(
            "\n[WARN] 5002 正在以 dev 单 worker 运行："
            "ARQ worker 未启动 -> 备份/告警等定时任务不会执行。",
            file=sys.stderr,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
