"""迁移脚本 DryRun 输出与回滚注释断言。"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
SCRIPT = REPO / "scripts" / "migrate_erp_web.ps1"

# 迁移脚本只在 Windows 生产机执行；CI 的 ubuntu runner 没有 powershell 可执行文件。
_windows_only = pytest.mark.skipif(
    sys.platform != "win32", reason="迁移脚本仅在 Windows 生产机执行"
)

# 安全顺序：先停旧树(erp-prod)再起 erp-web，否则双 nginx 抢 :3000。
_SAFE_ORDER = ("stop erp-prod", "start erp-web", "start erp-prod", "start erp-arq")


def _run_dryrun() -> str:
    """执行 -DryRun 并返回合并输出。

    Windows PowerShell 5.1 按 OEM 代码页(cp936)写 stdout，若直接以 UTF-8 解码会抛
    UnicodeDecodeError —— 该异常发生在 subprocess 的读取线程内，会被静默吞掉，
    最终表现为 stdout 为空且 returncode=0（看起来"脚本什么都没输出"，而不是报错）。
    故这里显式令 PowerShell 以 UTF-8 输出，并保留 errors="replace" 兜底。

    用 -Command 而非 -File：-File 没有机会在脚本执行前设置 [Console]::OutputEncoding，
    而该设置正是本修复的关键。路径已按 PowerShell 单引号字面量规则转义。
    """
    script_arg = str(SCRIPT).replace("'", "''")
    r = subprocess.run(
        [
            "powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
            "-Command", f"[Console]::OutputEncoding=[Text.Encoding]::UTF8; & '{script_arg}' -DryRun",
        ],
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60,
    )
    out = (r.stdout or "") + (r.stderr or "")
    assert r.returncode == 0, out
    return out


@_windows_only
def test_dryrun_prints_sequence() -> None:
    out = _run_dryrun()
    for expected in (
        "nssm stop erp-prod",
        "nssm start erp-web",
        "nssm start erp-prod",
        "nssm start erp-arq",
        "runtime_mode_probe.py",
    ):
        assert expected in out, f"missing: {expected}"
    # 注册分支二选一:服务不存在 → install;已存在 → set Application(幂等更新)
    assert ("nssm install erp-web" in out) or ("nssm set erp-web Application" in out), out


@_windows_only
def test_dryrun_order_stop_before_start_web_before_start_prod() -> None:
    """顺序即安全:必须先停旧树(erp-prod)再起 erp-web,最后起新 erp-prod 与 erp-arq。

    乱序(如先起 erp-web)会导致双 nginx 抢 :3000。
    """
    out = _run_dryrun()
    positions = [out.index(name) for name in _SAFE_ORDER]
    assert positions == sorted(positions), (
        "迁移顺序错误:必须 stop erp-prod → start erp-web → start erp-prod → start erp-arq"
    )


def test_real_execution_steps_follow_safe_order() -> None:
    """静态锚定**真实执行序列**(Invoke-Step)，在 CI(Linux) 上同样生效。

    上面的 DryRun 用例只断言"手写预览"的文本顺序，而预览与真实执行是两份独立的
    代码；本用例直接读真实执行的 Invoke-Step 步骤名，防止二者漂移，并补回
    Windows-only 用例在 CI 上失去的覆盖。
    """
    steps = re.findall(r'Invoke-Step\s+"([^"]+)"', SCRIPT.read_text(encoding="utf-8-sig"))
    assert steps, "未在脚本中找到 Invoke-Step 步骤序列"

    positions = []
    for stage in _SAFE_ORDER:
        matched = [i for i, name in enumerate(steps) if name.startswith(stage)]
        assert matched, f"真实执行序列缺少步骤 {stage!r};实际步骤={steps}"
        positions.append(matched[0])

    assert positions == sorted(positions), (
        f"真实执行顺序不安全,必须 {_SAFE_ORDER};实际={[steps[i] for i in positions]}"
    )



def test_idempotent_state_guards_present() -> None:
    """幂等:起停前查服务状态、已在目标态则跳过——任意中间态可安全重跑。"""
    text = SCRIPT.read_text(encoding="utf-8-sig")
    assert "function Get-SvcStateText" in text
    assert "function Start-SvcIfNeeded" in text
    assert "已是 RUNNING,跳过 start" in text
    assert "已是 STOPPED,跳过 stop" in text


def test_arq_start_and_verify_present() -> None:
    """erp-arq(定时备份唯一调度者)必须在迁移中拉起并验证,否则备份静默停摆。"""
    text = SCRIPT.read_text(encoding="utf-8-sig")
    assert "start erp-arq (backup scheduler)" in text
    assert "verify erp-arq running" in text


def test_rollback_notes_static() -> None:
    text = SCRIPT.read_text(encoding="utf-8-sig")
    for expected in ("SERVICE_DISABLED", "git revert", "nssm stop erp-web", "nssm restart erp-prod"):
        assert expected in text, f"missing: {expected}"
