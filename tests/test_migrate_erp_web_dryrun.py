"""迁移脚本 DryRun 输出与回滚注释断言。"""
from __future__ import annotations

from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SCRIPT = REPO / "scripts" / "migrate_erp_web.ps1"


def test_dryrun_prints_sequence() -> None:
    import subprocess

    r = subprocess.run(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(SCRIPT), "-DryRun"],
        capture_output=True, text=True, timeout=60,
    )
    out = (r.stdout or "") + (r.stderr or "")
    assert r.returncode == 0, out
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


def test_dryrun_order_stop_before_start_web_before_start_prod() -> None:
    """顺序即安全:必须先停旧树(erp-prod)再起 erp-web,最后起新 erp-prod 与 erp-arq。

    乱序(如先起 erp-web)会导致双 nginx 抢 :3000。
    """
    import subprocess

    r = subprocess.run(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(SCRIPT), "-DryRun"],
        capture_output=True, text=True, timeout=60,
    )
    out = (r.stdout or "") + (r.stderr or "")
    assert r.returncode == 0, out
    i_stop = out.index("nssm stop erp-prod")
    i_start_web = out.index("nssm start erp-web")
    i_start_prod = out.index("nssm start erp-prod")
    i_start_arq = out.index("nssm start erp-arq")
    assert i_stop < i_start_web < i_start_prod < i_start_arq, "迁移顺序错误:必须 stop erp-prod → start erp-web → start erp-prod → start erp-arq"


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
