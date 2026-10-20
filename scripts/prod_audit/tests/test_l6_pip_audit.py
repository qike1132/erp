"""L6 pip-audit 解析与审计目标回归（审计 P1-31）。

旧实现三重失效：只扫根 requirements.txt 兼容壳、未传 --format json、
按不存在的 cvss 键过滤 → 依赖漏洞恒报 0。
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

from scripts.prod_audit.base.issue_builder import IssueBuilder
from scripts.prod_audit.layers import l6_security as l6
from scripts.prod_audit.layers.l6_security import L6Security

_VULN_JSON = json.dumps({
    "dependencies": [
        {
            "name": "aiohttp",
            "version": "3.14.3",
            "vulns": [
                {
                    "id": "CVE-2026-111064",
                    "fix_versions": ["3.14.4"],
                    "aliases": [{"id": "GHSA-2g87-pp6c-29x5"}],
                    "description": "x",
                },
                {
                    "id": "CVE-2026-111063",
                    "fix_versions": [],
                    "aliases": [],
                    "description": "y",
                },
            ],
        }
    ],
    "fixes": [],
})


async def test_parse_json_reports_vulns_without_cvss() -> None:
    layer = L6Security()

    issues = layer._parse_pip_audit_output(
        _VULN_JSON, IssueBuilder(), source="requirements/test.lock",
    )

    assert len(issues) == 2
    assert {i.severity for i in issues} == {l6.Severity.MEDIUM}
    assert {i.rule_id for i in issues} == {"L6-PIP-VULN-001"}
    assert {i.file for i in issues} == {"requirements/test.lock"}
    first = next(i for i in issues if "CVE-2026-111064" in i.description)
    assert "aiohttp 3.14.3" in first.description
    assert "修复版本: 3.14.4" in first.description
    assert "GHSA-2g87-pp6c-29x5" in first.description
    assert "升级 aiohttp 至 3.14.4" in first.suggestion
    no_fix = next(i for i in issues if "CVE-2026-111063" in i.description)
    assert "修复版本: 无" in no_fix.description


async def test_parse_json_without_vulns_is_empty() -> None:
    layer = L6Security()
    payload = json.dumps({"dependencies": [{"name": "x", "version": "1", "vulns": []}]})

    assert layer._parse_pip_audit_output(payload, IssueBuilder()) == []


async def test_text_fallback_matches_vuln_id() -> None:
    layer = L6Security()

    issues = layer._parse_pip_audit_output(
        "aiohttp 3.14.3 CVE-2026-111064 3.14.4", IssueBuilder(),
    )

    assert len(issues) == 1
    assert "文本输出" in issues[0].description


async def test_run_pip_audit_scans_all_locks_and_dedupes(monkeypatch) -> None:
    layer = L6Security()
    cmds: list[list[str]] = []

    def fake_run(cmd, **kwargs):
        cmds.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, _VULN_JSON, "")

    monkeypatch.setattr(l6.subprocess, "run", fake_run)

    issues, raw = await layer._run_pip_audit(IssueBuilder())

    lock_files = sorted((l6.PROJECT_ROOT / "requirements").glob("*.lock"))
    assert len(cmds) == len(lock_files)
    assert all("--format" in c and "json" in c for c in cmds)
    assert all(c[c.index("-r") + 1].endswith(".lock") for c in cmds)
    # 同一漏洞在多档锁中重复出现 → 去重后只报一次
    assert len(issues) == 2
    assert raw.count("=== requirements/") == len(lock_files)


async def test_run_pip_audit_skips_when_no_locks(monkeypatch, tmp_path: Path) -> None:
    layer = L6Security()
    monkeypatch.setattr(l6, "PROJECT_ROOT", tmp_path)

    issues, raw = await layer._run_pip_audit(IssueBuilder())

    assert issues == []
    assert "不存在" in raw
