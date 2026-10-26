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

B1（2026-10-25 上线前检查，2026-10-26 修复）：健康 200 不绑定版本，旧进程
健康会被当发布成功。本脚本的成功口径收紧为五条全过：
1. 停前 PID 身份可确认；ServiceOps 结果 ``ok and effective``（effective=新 PID
   与停机前不同，同 PID = 停机未停成——即使旧进程健康也必须非零退出）；
2. 脚本侧独立复核 PID 身份，且新 supervisor 的启动年龄可证实；
3. /api/health 为 healthy、无 security_degraded，/api/health/ready 为 ready；
4. 回环健康响应中的实际 uvicorn worker runtime 存在，commit 等于目标 HEAD，
   worker 启动时刻晚于本次操作；
5. 重启前后 HEAD 一致，HEAD 任一次不可读都失败关闭。
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
from datetime import UTC, datetime
from pathlib import Path

# GBK 控制台会炸 emoji print（2026-10-25 实证：重启成功但 print('✅') 抛
# UnicodeEncodeError → exit 1，部署核验被误判 INCOMPLETE）。入口统一重配置，
# 输出不再依赖终端码页。
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

SERVICE_NAME = "erp-prod"
HEALTH_URL = "http://127.0.0.1:5002/api/health"
READY_URL = "http://127.0.0.1:5002/api/health/ready"
NSSM_CANDIDATES = (r"C:\nssm\nssm.exe", r"C:\Program Files\nssm\nssm.exe")


def _find_nssm() -> str | None:
    for path in NSSM_CANDIDATES:
        try:
            open(path, "rb").close()
            return path
        except OSError:
            continue
    return shutil.which("nssm")


def _fetch_json(url: str) -> dict:
    with urllib.request.urlopen(url, timeout=3) as resp:
        if resp.status != 200:
            raise ValueError(f"HTTP {resp.status}")
        body = json.loads(resp.read().decode("utf-8", "replace"))
    if not isinstance(body, dict):
        raise ValueError("响应不是 JSON 对象")
    return body


def _health_probe() -> dict | None:
    """发布验收健康检查：healthy + readiness + 实际 worker runtime。

    通用 ``/api/health`` 为兼容监督器，在 Redis 缺失/安全降级时仍可能 200；
    发布口径必须同时查 readiness 与 security_degraded。``runtime`` 仅由回环
    请求返回，用于绑定实际响应 worker 的 commit/启动代次。
    """
    try:
        body = _fetch_json(HEALTH_URL)
        ready = _fetch_json(READY_URL)
    except (urllib.error.URLError, OSError, ValueError, json.JSONDecodeError):
        return None
    if str(body.get("status", "")).lower() not in {"ok", "healthy"}:
        return None
    if body.get("security_degraded") is not False:
        return None
    if (
        ready.get("status") != "ready"
        or ready.get("database") is not True
        or ready.get("redis") is not True
    ):
        return None
    runtime = body.get("runtime")
    if not isinstance(runtime, dict):
        return None
    return {**body, "runtime": runtime}


def _parse_started_at(value: object) -> float | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(UTC).timestamp()


def _verify_runtime(runtime: dict, head_before: str, wall_started: float) -> tuple[bool, str]:
    """校验回环 ``runtime`` 是否属于「本次重启拉起的、目标 commit 的 worker」。

    H4（2026-10-26）：健康 200 只是必要条件之一。真正的验收对象是**实际响应
    请求的那个 uvicorn worker**：commit 必须等于目标 HEAD（否则旧进程还在服务），
    启动时刻必须晚于本次操作（否则进程根本没换），PID 必须可读（否则身份未证实）。
    任一不满足即失败关闭——这三项都能被「旧进程健康」同时满足而骗过状态码。
    """
    commit = runtime.get('commit')
    if not isinstance(commit, str) or len(commit.strip()) != 40:
        return False, 'runtime 未提供有效 commit（无法绑定发布版本）'
    if commit.strip().lower() != head_before.strip().lower():
        return False, (
            f'worker commit={commit.strip()[:12]} 与目标 HEAD={head_before.strip()[:12]} 不一致'
        )
    pid = runtime.get('pid')
    if not isinstance(pid, int) or isinstance(pid, bool) or pid <= 0:
        return False, 'runtime 未提供有效 worker PID（身份未证实）'
    started = _parse_started_at(runtime.get('started_at'))
    if started is None:
        return False, 'runtime.started_at 缺失或非带时区 ISO 时间（启动代次未证实）'
    if started < wall_started - 5:
        return False, (
            f'worker 启动于 {time.time() - started:.0f}s 前，早于本次重启开始'
            f'（{time.time() - wall_started:.0f}s 前）——不是本次重启拉起的进程'
        )
    return True, ''


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
    **调用方必须失败关闭**（H4：无法证明是新进程 == 不能宣告发布成功）。
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
    # 用 svc_pid_ex 区分「服务未运行（None, ok=True）」与「探测通道故障
    # (None, ok=False)」——后者意味着停机前后都无法证实身份，评审 finding 2。
    prev_pid, prev_ok = ops.svc_pid_ex(SERVICE_NAME)
    if not prev_ok:
        print("❌ 停机前 PID 探测通道不可用（sc queryex 失败）——"
              "无法证明重启是否真的换了进程，已在停服前拒绝执行。")
        return 1
    head_before = _git_head(repo_root)
    if not head_before:
        print("❌ 无法读取目标 HEAD，发布版本指纹不可证实，已在停服前拒绝执行。")
        return 1
    wall_started = time.time()
    print(f"停机前 PID: {prev_pid}" if prev_pid is not None else "停机前服务确认为未运行")
    print(f"目标 commit: {head_before[:12]}")

    try:
        result = ops.restart_service_via_stop_start(SERVICE_NAME, nssm=nssm)
    finally:
        # B1：即使重启调用抛未捕获异常，也要把队列里已投递的停机告警吐出来
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
    # 脚本侧独立复核（不信任 ServiceOps 内部判定）：用 svc_pid_ex 再查一次当前 PID，
    # 通道故障或与 ServiceOps 报告不一致都按身份未证实处理（评审 finding 2/5）。
    now_pid, now_ok = ops.svc_pid_ex(SERVICE_NAME)
    if not now_ok or now_pid != result.pid:
        print(f"❌ PID 独立复核不一致（ServiceOps: {result.pid}, 复核: {now_pid}, "
              f"通道{'不可用' if not now_ok else '正常'}），不得宣告发布成功。")
        return 1

    print("等待发布验收通过（health + readiness + 版本代次，最多 90s）...")
    verified_runtime: dict | None = None
    last_reason = '未收到任何健康响应'
    for i in range(30):
        time.sleep(3)
        probe = _health_probe()
        if probe is None:
            last_reason = ('/api/health 或 /api/health/ready 未通过'
                           '（含 security_degraded / DB / Redis）')
        else:
            ok_runtime, reason = _verify_runtime(probe['runtime'], head_before, wall_started)
            if ok_runtime:
                verified_runtime = probe['runtime']
                print(f"✅ 后端已就绪且版本已绑定（{(i + 1) * 3}s，"
                      f"supervisor PID: {result.pid}，"
                      f"worker PID: {verified_runtime['pid']}，"
                      f"commit: {head_before[:12]}）")
                break
            last_reason = f"健康但 worker 版本代次不符：{reason}"
        print(f"  ... {(i + 1) * 3}s 未就绪：{last_reason}")
    if verified_runtime is None:
        print(f"❌ 90s 内发布验收未通过：{last_reason}")
        print("   健康 200 不等于新代码已加载；请检查 logs/prod_runner.json 与 "
              "logs/后端(uvicorn).*.log；注意本脚本不再手工拉起 uvicorn。")
        return 1

    # B1 版本指纹：发布中途工作区换代码 / 新进程其实是老进程，都不得报成功。
    head_after = _git_head(repo_root)
    if not head_after:
        print("❌ 重启后无法读取 HEAD，发布版本指纹不可证实（fail-closed）。")
        return 1
    if head_before != head_after:
        print(f"❌ 版本指纹不符：重启前 HEAD={head_before[:12]}，重启后={head_after[:12]}。"
              "发布期间工作区被改动，本次重启加载的代码版本不可信。")
        return 1
    if verified_runtime.get('commit', '').strip().lower() != head_after.lower():
        print(f"❌ worker 报告的 commit={str(verified_runtime.get('commit'))[:12]} "
              f"与重启后 HEAD={head_after[:12]} 不一致，发布版本不可信。")
        return 1
    age = _process_age_seconds(result.pid)
    elapsed = time.time() - wall_started
    if age is None:
        # H4：探测失败不再降级为 WARNING——「无法证明是新进程」与「确认是老进程」
        # 对发布结论等价，都必须非零退出（worker runtime 已另行证明启动代次）。
        print(f"❌ 无法探测 PID {result.pid} 的启动时刻（Get-Process 不可用），"
              "supervisor 身份未证实，本次发布不得宣告成功。")
        return 1
    if age > elapsed + 5:
        # +5s 余量：探测本身有 ~1s 开销、进程启动时刻与 wall_started 之间还有
        # 停机等待（服务收尾数秒），新进程 age 贴着 elapsed 属正常；老进程（数
        # 百秒起步）远超该阈值。真实重启 elapsed ≥ 3s（健康轮询首查前必 sleep）。
        print(f"❌ 版本指纹不符：PID {result.pid} 已存活 {age:.0f}s，明显早于本次重启开始"
              f"（{elapsed:.0f}s 前）——这不是本次重启拉起的新进程。")
        return 1

    print(f"✅ 重启完成并已验证：supervisor PID {prev_pid} → {result.pid}，"
          f"worker PID {verified_runtime['pid']}，HEAD {head_after[:12]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
