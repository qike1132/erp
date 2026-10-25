"""重启生产后端（委托 NSSM，显式 stop→start，不再手工拉起 uvicorn）。

2026-10-24 审计 P1 修复：原实现先 `taskkill /F /T` 杀掉 NSSM 托管的 erp-prod 进程树，
再 `os.chdir(scripts/)` 后执行 `python -m uvicorn fastapi_app.main:app` ——
此时 `sys.path[0]` 变成 `scripts/`，而 `fastapi_app` 在仓库根，必然
`ModuleNotFoundError`，且 subprocess 返回码被丢弃。结果是：生产被打断、操作者以为
「已用新代码重启」，实际靠 NSSM 的 5 秒自愈拉起了同一个旧进程。

现在只走唯一受支持的入口并轮询 /api/health 判定生效。`erp-prod` 是 NSSM 服务
（AGENTS §3），不要用本脚本手工起 uvicorn。
M-G（2026-10-25 复审）：重启**不用** `nssm restart` —— NSSM 2.24 的 restart 在
停机阶段返回非 0 就直接退出、start 根本不发出（nssm.cpp:271-275，service_ops.py
2026-10-13 实证根因），服务会永远停在 STOPPED。改为复用
``server_manager.service_ops.ServiceOps.restart_service_via_stop_start``：
显式 stop → 等 STOPPED → 无条件 start → 等 RUNNING（headless 构造，
与 server_manager 界面共用同一实现，避免两处停机口径漂移）。

B1（2026-10-25 上线前检查）：健康 200 不绑定版本，旧进程健康会被当发布成功。
本脚本的成功口径收紧为四条全过：
1. ServiceOps 结果 ``ok and effective``（effective=新 PID 与停机前不同，同 PID
   = 停机未停成，本次重启没发生——即使旧进程健康也必须非零退出）；
2. 脚本侧独立复核 PID 身份（不丢弃返回的 PID，不消费队列里的 WARNING 等于撒谎）；
3. /api/health 通过；
4. 版本指纹：重启前后 HEAD 一致（工作区没在发布中途换代码），新进程启动时刻
   晚于本脚本开始时刻（探测可得时必查）。
"""
from __future__ import annotations

import json
import queue as _queue
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

# GBK 控制台会炸 emoji print（2026-10-25 实证：重启成功但 print('✅') 抛
# UnicodeEncodeError → exit 1，部署核验被误判 INCOMPLETE）。入口统一重配置，
# 输出不再依赖终端码页。
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

SERVICE_NAME = "erp-prod"
HEALTH_URL = "http://127.0.0.1:5002/api/health"
NSSM_CANDIDATES = (r"C:\nssm\nssm.exe", r"C:\Program Files\nssm\nssm.exe")


def _find_nssm() -> str | None:
    for path in NSSM_CANDIDATES:
        try:
            open(path, "rb").close()
            return path
        except OSError:
            continue
    return shutil.which("nssm")


def _health_ok() -> bool:
    try:
        with urllib.request.urlopen(HEALTH_URL, timeout=3) as resp:
            body = json.loads(resp.read().decode("utf-8", "replace"))
        return resp.status == 200 and str(body.get("status", "")).lower() in {"ok", "healthy", "degraded"}
    except (urllib.error.URLError, OSError, ValueError, json.JSONDecodeError):
        return False


def _git_head(repo_root: Path) -> str | None:
    """当前 HEAD（版本指纹之一）；读不到返回 None（调用方按降级处理）。"""
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=str(repo_root),
            capture_output=True, text=True, timeout=15,
        )
        if out.returncode == 0:
            return out.stdout.strip() or None
    except (OSError, subprocess.SubprocessError):
        pass
    return None


def _process_age_seconds(pid: int) -> float | None:
    """进程已存活秒数（版本指纹之一：新进程必须比重启动作年轻）。

    用「存活时长」而不是绝对启动时刻，规避 PowerShell 输出的本地时区解析问题
    （统一在 PowerShell 内部以 UTC 计算差值，脚本只拿数字）。探测失败返回 None，
    调用方降级为 WARNING——PID 已变本身就是身份证据，启动时刻是加固项。
    """
    cmd = (
        "[int]((Get-Date).ToUniversalTime() - "
        f"(Get-Process -Id {int(pid)}).StartTime.ToUniversalTime()).TotalSeconds"
    )
    for exe in ("pwsh", "powershell"):
        path = shutil.which(exe)
        if not path:
            continue
        try:
            out = subprocess.run(
                [path, "-NoProfile", "-NonInteractive", "-Command", cmd],
                capture_output=True, text=True, timeout=20,
            )
            if out.returncode == 0:
                return abs(float(out.stdout.strip()))
        except (OSError, ValueError, subprocess.SubprocessError):
            continue
    return None


def _drain_queue(q: _queue.SimpleQueue) -> list[str]:
    """消费 ServiceOps 的 msg_queue，外发 WARNING/ERROR（B1：不得丢弃告警）。

    只回显告警级消息：INFO 行（"正在停止/启动..."）与脚本自身输出重复，
    全量打印只会淹没关键信息；WARNING/ERROR 是停机非零返回、未确认 STOPPED、
    重启未生效等如实汇报，丢了它们等于把失败藏起来。
    """
    surfaced: list[str] = []
    while True:
        try:
            kind, payload = q.get_nowait()
        except _queue.Empty:
            return surfaced
        if kind != "log" or not isinstance(payload, dict):
            continue
        level = str(payload.get("level", "INFO"))
        text = str(payload.get("text", ""))
        if level in ("WARNING", "ERROR") and text:
            prefix = "❌ " if level == "ERROR" else "⚠️ "
            print(f"{prefix}{text}")
            surfaced.append(text)


def main() -> int:
    # AUD-17（2026-10-24 审计 P1）：重启 = 把工作区当前签出的代码跑进生产。
    # 生产直接吃 D:\erp_system 源码（AGENTS §6.1-6/§6.1-9），工作区在非 main
    # 分支或半改状态时重启，就会把那条分支/半改代码跑进生产（2026-10-14 实害
    # 75 分钟、2026-10-22 连崩 8 次两次事故的旁路入口——其余全部重启路径
    # 已接闸门，唯本脚本漏接）。与 start.py:97 同款语义。
    # OCR-H1（2026-10-24 推送前评审）：本脚本以 `python scripts/restart_backend.py`
    # 直跑时 sys.path[0] 是 scripts/，仓库根不在路径上——先插根再导入
    # server_manager.git_guard，否则闸门自身 ModuleNotFoundError（fail-closed
    # 但把操作者推向未接闸门的手工 nssm restart，更糟）。
    repo_root = Path(__file__).resolve().parent.parent

    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))

    from server_manager.git_guard import check_production_branch

    ok, guard_msg = check_production_branch(repo_root)
    if not ok:
        print(f"❌ {guard_msg}")
        print("   生产重启只允许在 main 分支且工作区干净时进行（server_manager / start.py 同闸门）。")
        return 2
    if guard_msg.startswith('警告') or '覆盖' in guard_msg:
        print(f"⚠️ {guard_msg}")

    nssm = _find_nssm()
    if not nssm:
        print("❌ 找不到 nssm.exe。生产后端由 NSSM 托管，请安装 NSSM 或用 "
              "`python start.py --prod` / server_manager 界面重启。")
        return 2

    print(f"=== 重启 {SERVICE_NAME}（显式 stop → start，等终态） ===")
    # M-G：不用 `nssm restart`（NSSM 2.24 停机失败即放弃启动，服务永久 STOPPED）。
    # headless 构造 ServiceOps：msg_queue 用 SimpleQueue 承接（重启后由
    # _drain_queue 消费 WARNING/ERROR，B1：丢弃告警 = 假成功）、gate 不参与该路径。
    from server_manager.service_ops import ServiceOps

    msg_queue: _queue.SimpleQueue = _queue.SimpleQueue()
    ops = ServiceOps(
        msg_queue=msg_queue,
        gate=None,
        project_dir=str(repo_root),
        log_message=lambda *_a, **_k: None,
    )
    # B1 版本指纹：停机前 PID / HEAD / 起始时刻——重启后再独立复核。
    prev_pid = ops.svc_pid(SERVICE_NAME)
    head_before = _git_head(repo_root)
    wall_started = time.time()
    if prev_pid is not None:
        print(f"停机前 PID: {prev_pid}")
    if head_before:
        print(f"目标 commit: {head_before[:12]}")

    result = ops.restart_service_via_stop_start(SERVICE_NAME, nssm=nssm)
    _drain_queue(msg_queue)

    if not result.ok:
        print(f"❌ 重启未生效（终态: {result.state}）。排查：nssm status erp-prod；"
              "日志 logs/后端(uvicorn).*.log")
        return 1
    if not result.effective:
        print(f"❌ 服务在跑但本次重启未生效（停机未停成，PID 仍是 {result.pid}）。"
              "旧进程健康也不代表新代码已加载，本次发布必须判失败。")
        return 1
    if result.pid is None or (prev_pid is not None and result.pid == prev_pid):
        print(f"❌ PID 身份核验失败（prev={prev_pid}, now={result.pid}），不得宣告发布成功。")
        return 1

    print("等待健康检查通过（最多 90s）...")
    healthy = False
    for i in range(30):
        time.sleep(3)
        if _health_ok():
            print(f"✅ 后端已就绪（{(i + 1) * 3}s，PID: {result.pid}）")
            healthy = True
            break
        print(f"  ... {(i + 1) * 3}s 未就绪")
    if not healthy:
        print("❌ 90s 内 /api/health 未通过。请检查 logs/prod_runner.json 与 "
              "logs/后端(uvicorn).*.log；注意本脚本不再手工拉起 uvicorn。")
        return 1

    # B1 版本指纹：发布中途工作区换代码 / 新进程其实是老进程，都不得报成功。
    head_after = _git_head(repo_root)
    if head_before and head_after and head_before != head_after:
        print(f"❌ 版本指纹不符：重启前 HEAD={head_before[:12]}，重启后={head_after[:12]}。"
              "发布期间工作区被改动，本次重启加载的代码版本不可信。")
        return 1
    age = _process_age_seconds(result.pid)
    elapsed = time.time() - wall_started
    if age is None:
        print("⚠️ 新进程启动时刻探测失败（Get-Process 不可用），已按 PID 变化判定身份。")
    elif age > elapsed + 5:
        # +5s 余量：探测本身有 ~1s 开销、进程启动时刻与 wall_started 之间还有
        # 停机等待（服务收尾数秒），新进程 age 贴着 elapsed 属正常；老进程（数
        # 百秒起步）远超该阈值。真实重启 elapsed ≥ 3s（健康轮询首查前必 sleep）。
        print(f"❌ 版本指纹不符：PID {result.pid} 已存活 {age:.0f}s，明显早于本次重启开始"
              f"（{elapsed:.0f}s 前）——这不是本次重启拉起的新进程。")
        return 1

    print(f"✅ 重启完成并已验证：PID {prev_pid} → {result.pid}，"
          f"HEAD {head_after[:12] if head_after else '(未知)'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
