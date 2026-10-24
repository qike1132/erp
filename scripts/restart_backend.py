"""重启生产后端（委托 NSSM，不再手工拉起 uvicorn）。

2026-10-24 审计 P1 修复：原实现先 `taskkill /F /T` 杀掉 NSSM 托管的 erp-prod 进程树，
再 `os.chdir(scripts/)` 后执行 `python -m uvicorn fastapi_app.main:app` ——
此时 `sys.path[0]` 变成 `scripts/`，而 `fastapi_app` 在仓库根，必然
`ModuleNotFoundError`，且 subprocess 返回码被丢弃。结果是：生产被打断、操作者以为
「已用新代码重启」，实际靠 NSSM 的 5 秒自愈拉起了同一个旧进程。

现在只走唯一受支持的入口：`nssm restart erp-prod`，然后轮询 /api/health 判定生效。
`erp-prod` 是 NSSM 服务（AGENTS §3），不要用本脚本手工起 uvicorn。
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request

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
    from pathlib import Path

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

    print(f"=== 重启 {SERVICE_NAME}（nssm restart） ===")
    result = subprocess.run([nssm, "restart", SERVICE_NAME], capture_output=True, text=True)
    if result.returncode != 0:
        print(f"❌ nssm restart 失败（rc={result.returncode}）: {result.stderr.strip() or result.stdout.strip()}")
        print("   排查：nssm status erp-prod；日志 logs/后端(uvicorn).*.log")
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
