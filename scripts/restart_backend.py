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
"""
from __future__ import annotations

import json
import shutil
import sys
import time
import urllib.error
import urllib.request

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
    import sys
    from pathlib import Path

    _REPO_ROOT = str(Path(__file__).resolve().parent.parent)
    if _REPO_ROOT not in sys.path:
        sys.path.insert(0, _REPO_ROOT)

    from server_manager.git_guard import check_production_branch

    ok, guard_msg = check_production_branch(Path(__file__).resolve().parent.parent)
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
    # headless 构造 ServiceOps：msg_queue 用内存列表承接、gate 不参与该路径。
    import queue as _queue

    from server_manager.service_ops import ServiceOps

    ops = ServiceOps(
        msg_queue=_queue.SimpleQueue(),
        gate=None,
        project_dir=str(Path(__file__).resolve().parent.parent),
        log_message=lambda *_a, **_k: None,
    )
    ok, state, _pid = ops.restart_service_via_stop_start(SERVICE_NAME, nssm=nssm)
    if not ok:
        print(f"❌ 重启未生效（终态: {state}）。排查：nssm status erp-prod；"
              "日志 logs/后端(uvicorn).*.log")
        return 1

    print("等待健康检查通过（最多 90s）...")
    for i in range(30):
        time.sleep(3)
        if _health_ok():
            print(f"✅ 后端已就绪（{(i + 1) * 3}s）")
            return 0
        print(f"  ... {(i + 1) * 3}s 未就绪")

    print("❌ 90s 内 /api/health 未通过。请检查 logs/prod_runner.json 与 "
          "logs/后端(uvicorn).*.log；注意本脚本不再手工拉起 uvicorn。")
    return 1


if __name__ == "__main__":
    sys.exit(main())
