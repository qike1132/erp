"""bandit 门禁回归（2026-10-17 审计 F3-2）

缺陷：bandit 只产出报告（`-ii --exit-zero`），**没有任何判定步骤**——扫描与判定
之间是断的，新引入的安全发现不会让 CI 变红。

本文件覆盖：
1. 报告解析层（发现数 / 扫描错误 / 形状损坏）；
2. 端到端：真跑 quality_gate.py，报告里的发现数超基线即失败；
3. 接线：CI 必须把报告交给门禁判定（否则又回到「只出报告」）。
"""
import json
import os
import subprocess
import sys

import scripts.quality_gate as q

PROJECT_ROOT = q.PROJECT_ROOT
GATE_SCRIPT = PROJECT_ROOT / "scripts" / "quality_gate.py"
CI_WORKFLOW = PROJECT_ROOT / ".github" / "workflows" / "ci-cd.yml"


def _finding(index: int) -> dict:
    return {
        "filename": f"fastapi_app/probe_{index}.py",
        "line_number": index,
        "test_id": "B608",
        "issue_text": "hardcoded_sql_expressions",
        "issue_severity": "MEDIUM",
        "issue_confidence": "MEDIUM",
    }


def _report(count: int) -> dict:
    return {"errors": [], "results": [_finding(i) for i in range(count)]}


# ---------------------------------------------------------------------------
# 解析层
# ---------------------------------------------------------------------------


def test_summary_counts_findings():
    count, hard_error, details = q._bandit_summary(_report(3))
    assert hard_error is None
    assert count == 3
    assert len(details) == 3
    assert 'B608' in details[0]


def test_summary_clean_report_is_zero():
    count, hard_error, _details = q._bandit_summary({"errors": [], "results": []})
    assert (count, hard_error) == (0, None)


def test_summary_scan_error_is_hard_error():
    """bandit 没扫到的文件等于没被检查，不能当 0 处发现放过去。"""
    count, hard_error, _details = q._bandit_summary(
        {"errors": ["syntax error in probe.py"], "results": []}
    )
    assert count is None
    assert hard_error is not None


def test_summary_missing_results_is_hard_error():
    count, hard_error, _details = q._bandit_summary({"errors": []})
    assert count is None
    assert hard_error is not None


def test_summary_non_dict_is_hard_error():
    count, hard_error, _details = q._bandit_summary(["not", "a", "dict"])
    assert count is None
    assert hard_error is not None


def test_payload_tolerates_progress_line():
    """bandit 会在 JSON 之前打印进度行，解析不能要求 JSON 在起始处。"""
    text = 'Working... ---------------------------------------- 100% 0:00:09\n{"errors": [], "results": []}'
    payload = q._bandit_payload(text)
    assert payload is not None
    assert payload["results"] == []


def test_payload_rejects_garbage():
    assert q._bandit_payload("not json at all") is None


# ---------------------------------------------------------------------------
# 端到端
# ---------------------------------------------------------------------------


def _run_gate(*args):
    return subprocess.run(
        [sys.executable, str(GATE_SCRIPT), *args],
        cwd=PROJECT_ROOT, capture_output=True, text=True, encoding="utf-8",
        errors="replace", timeout=600, env=dict(os.environ),
    )


def test_gate_fails_when_findings_exceed_baseline(tmp_path):
    baseline = q.load_baseline()
    assert baseline and "bandit" in baseline, '基线必须先登记 bandit 计数'
    report = tmp_path / "security-report.json"
    report.write_text(json.dumps(_report(baseline["bandit"] + 1)), encoding="utf-8")

    proc = _run_gate("--only", "bandit", "--security-report", str(report))
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert "REGRESS" in proc.stdout


def test_gate_passes_when_findings_match_baseline(tmp_path):
    baseline = q.load_baseline()
    report = tmp_path / "security-report.json"
    report.write_text(json.dumps(_report(baseline["bandit"])), encoding="utf-8")

    proc = _run_gate("--only", "bandit", "--security-report", str(report))
    assert proc.returncode == 0, proc.stdout + proc.stderr


def test_gate_fails_closed_on_broken_report(tmp_path):
    """报告形状损坏 → 保守失败（绝不静默记 0 处发现）。"""
    report = tmp_path / "security-report.json"
    report.write_text("{not json", encoding="utf-8")

    proc = _run_gate("--only", "bandit", "--security-report", str(report))
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert "ERROR" in proc.stdout


def test_gate_fails_closed_on_missing_report(tmp_path):
    proc = _run_gate("--only", "bandit", "--security-report", str(tmp_path / "nope.json"))
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert "ERROR" in proc.stdout


# ---------------------------------------------------------------------------
# 接线
# ---------------------------------------------------------------------------


def test_ci_passes_bandit_report_to_the_gate():
    text = CI_WORKFLOW.read_text(encoding="utf-8")
    assert "--security-report security-report.json" in text, \
        "CI 必须把 bandit 报告交给门禁判定（否则又回到「只出报告、无人判定」）"


def test_bandit_gate_is_registered():
    keys = {gate.key for gate in q.GATES}
    assert "bandit" in keys
