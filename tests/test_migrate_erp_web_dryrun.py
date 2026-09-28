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
        "nssm install erp-web",
        "nssm set erp-web Application",
        "nssm stop erp-prod",
        "nssm start erp-web",
        "nssm start erp-prod",
        "runtime_mode_probe.py",
    ):
        assert expected in out, f"missing: {expected}"


def test_rollback_notes_static() -> None:
    text = SCRIPT.read_text(encoding="utf-8-sig")
    for expected in ("SERVICE_DISABLED", "git revert", "nssm stop erp-web", "nssm restart erp-prod"):
        assert expected in text, f"missing: {expected}"
