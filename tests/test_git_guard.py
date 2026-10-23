"""生产启停 git 分支闸门回归（2026-10-17 审计 AUD-28）

缺陷：NSSM 服务直接吃工作区源码，重启前无人校验分支；2026-10-14 已有
75 分钟实害事故。本测试用临时 git 仓库验证闸门行为。
"""
import subprocess

import pytest

from server_manager import git_guard


def _git(cwd, *args):
    subprocess.run(['git', *args], cwd=str(cwd), check=True, capture_output=True)


@pytest.fixture
def repo(tmp_path):
    _git(tmp_path, 'init', '-q')
    _git(tmp_path, 'config', 'user.email', 'audit@example.com')
    _git(tmp_path, 'config', 'user.name', 'audit')
    (tmp_path / 'a.txt').write_text('x', encoding='utf-8')
    _git(tmp_path, 'add', 'a.txt')
    _git(tmp_path, 'commit', '-q', '-m', 'init')
    return tmp_path


def test_main_branch_allowed(repo, monkeypatch):
    monkeypatch.delenv(git_guard.OVERRIDE_ENV, raising=False)
    _git(repo, 'checkout', '-q', '-b', 'main')

    ok, msg = git_guard.check_production_branch(repo)

    assert ok is True
    assert 'main' in msg


def test_feature_branch_rejected(repo, monkeypatch):
    monkeypatch.delenv(git_guard.OVERRIDE_ENV, raising=False)
    _git(repo, 'checkout', '-q', '-b', 'claude/feature')

    ok, msg = git_guard.check_production_branch(repo)

    assert ok is False
    assert 'claude/feature' in msg
    assert git_guard.OVERRIDE_ENV in msg


def test_override_allows_feature_branch(repo, monkeypatch):
    monkeypatch.setenv(git_guard.OVERRIDE_ENV, '1')
    _git(repo, 'checkout', '-q', '-b', 'claude/feature')

    ok, msg = git_guard.check_production_branch(repo)

    assert ok is True
    assert '覆盖' in msg


def test_dirty_main_blocks_by_default(repo, monkeypatch):
    """2026-10-24（P1）：脏工作区必须阻断。

    原行为是「警告后放行」，形态即 2026-10-22 事故（一个文件改了 import 而提供者
    未提交 → 撤销链路 ImportError 连崩 8 次）。AGENTS §6.1-9 要求 porcelain 为空。
    """
    monkeypatch.delenv(git_guard.OVERRIDE_ENV, raising=False)
    monkeypatch.delenv(git_guard.DIRTY_OVERRIDE_ENV, raising=False)
    _git(repo, 'checkout', '-q', '-b', 'main')
    (repo / 'a.txt').write_text('changed', encoding='utf-8')

    ok, msg = git_guard.check_production_branch(repo)

    assert ok is False
    assert '未提交改动' in msg


def test_dirty_main_allows_with_override(repo, monkeypatch):
    monkeypatch.delenv(git_guard.OVERRIDE_ENV, raising=False)
    monkeypatch.setenv(git_guard.DIRTY_OVERRIDE_ENV, '1')
    _git(repo, 'checkout', '-q', '-b', 'main')
    (repo / 'a.txt').write_text('changed', encoding='utf-8')

    ok, msg = git_guard.check_production_branch(repo)

    assert ok is True
    assert git_guard.DIRTY_OVERRIDE_ENV in msg


def test_non_git_directory_does_not_block(tmp_path, monkeypatch):
    monkeypatch.delenv(git_guard.OVERRIDE_ENV, raising=False)

    ok, msg = git_guard.check_production_branch(tmp_path)

    assert ok is True
    assert '无法确定' in msg
