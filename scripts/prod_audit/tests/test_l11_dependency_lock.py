"""L11 依赖锁定检查回归（审计 P1-33）：requirements/<tier>.txt ↔ <tier>.lock。

旧实现只读根 requirements.txt 兼容壳（并跳过 -r 行）→ 分档重构后恒 0 issue。
"""
from __future__ import annotations

from pathlib import Path

from scripts.prod_audit.base.issue_builder import IssueBuilder
from scripts.prod_audit.layers import l11_deployment as l11
from scripts.prod_audit.layers.l11_deployment import L11Deployment

_RULE = 'L11-DEP-UNLOCKED-001'


def _setup(tmp_path: Path, monkeypatch, files: dict[str, str]) -> None:
    req_dir = tmp_path / 'requirements'
    req_dir.mkdir(parents=True, exist_ok=True)
    for name, content in files.items():
        (req_dir / name).write_text(content, encoding='utf-8')
    monkeypatch.setattr(l11, 'PROJECT_ROOT', tmp_path)


async def _run() -> tuple[list, str]:
    return await L11Deployment()._check_dependency_lock(IssueBuilder())


def _dep_issues(issues: list) -> list:
    return [i for i in issues if i.rule_id == _RULE]


async def test_missing_lock_is_reported(tmp_path: Path, monkeypatch) -> None:
    _setup(tmp_path, monkeypatch, {'base.txt': 'requests==2.31.0\n'})

    issues, _ = await _run()

    assert any('缺少对应锁文件' in i.description for i in _dep_issues(issues))


async def test_uncovered_declaration_is_reported(tmp_path: Path, monkeypatch) -> None:
    _setup(tmp_path, monkeypatch, {
        'base.txt': 'requests==2.31.0\n',
        'base.lock': 'other==1.0\n',
    })

    issues, _ = await _run()

    assert any('锁未覆盖声明依赖' in i.description for i in _dep_issues(issues))


async def test_version_drift_is_reported(tmp_path: Path, monkeypatch) -> None:
    _setup(tmp_path, monkeypatch, {
        'base.txt': 'requests==2.31.0\n',
        'base.lock': 'requests==2.32.0\n',
    })

    issues, _ = await _run()

    assert any('锁版本与声明漂移' in i.description for i in _dep_issues(issues))


async def test_floating_declaration_covered_is_ok(tmp_path: Path, monkeypatch) -> None:
    _setup(tmp_path, monkeypatch, {
        'base.txt': 'requests>=2.31.0\nruff==0.11.0\n',
        'base.lock': 'requests==2.32.5\nruff==0.11.0\n',
    })

    issues, _ = await _run()

    assert _dep_issues(issues) == []


async def test_missing_requirements_dir_is_reported(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(l11, 'PROJECT_ROOT', tmp_path)

    issues, _ = await _run()

    assert any('不存在' in i.description for i in _dep_issues(issues))


async def test_real_repo_all_tiers_are_locked() -> None:
    issues, raw = await _run()

    dep = _dep_issues(issues)
    assert not any('缺少对应锁文件' in i.description for i in dep), dep
    assert not any('锁未覆盖声明依赖' in i.description for i in dep), dep
    assert 'requirements/base.txt' in raw
