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


# ---------------------------------------------------------------------------
# 2026-11-04：闸门因 git "dubious ownership" 长期静默失效
#
# NSSM 服务以 LocalSystem 运行、仓库属主是 Administrator，git 拒绝任何命令 →
# 原实现落到「无法确定分支，已放行」，分支闸门与脏工作区检查**同时失效**。
# 生产日志自 2026-11-02 起每次启动都复现该警告（erp-arq.log / erp-prod.log）。
# ---------------------------------------------------------------------------


def test_git_invocation_pins_safe_directory(tmp_path, monkeypatch):
    """每条 git 调用都必须带 -c safe.directory，否则跨账号运行时闸门直接失效。"""
    captured: list[list[str]] = []

    class _Proc:
        returncode = 0
        stdout = 'main'
        stderr = ''

    def _fake_run(argv, **kwargs):
        captured.append(argv)
        return _Proc()

    monkeypatch.setattr(git_guard.subprocess, 'run', _fake_run)

    git_guard._git(['rev-parse', '--abbrev-ref', 'HEAD'], tmp_path)

    assert captured, 'git 未被调用'
    argv = captured[0]
    assert argv[0] == 'git'
    assert '-c' in argv
    safe_arg = next(a for a in argv if a.startswith('safe.directory='))
    assert safe_arg == f'safe.directory={tmp_path.resolve()}'


def test_git_repo_but_unreadable_branch_blocks(tmp_path, monkeypatch):
    """有 .git 却读不出分支 = 闸门无法生效，必须拒绝而不是静默放行。"""
    monkeypatch.delenv(git_guard.OVERRIDE_ENV, raising=False)
    (tmp_path / '.git').mkdir()
    monkeypatch.setattr(
        git_guard,
        '_git',
        lambda args, cwd: (128, '', 'fatal: detected dubious ownership in repository'),
    )

    ok, msg = git_guard.check_production_branch(tmp_path)

    assert ok is False
    assert '无法读取 git 分支' in msg
    assert git_guard.OVERRIDE_ENV in msg


def test_git_repo_unreadable_branch_allows_with_override(tmp_path, monkeypatch):
    monkeypatch.setenv(git_guard.OVERRIDE_ENV, '1')
    (tmp_path / '.git').mkdir()
    monkeypatch.setattr(
        git_guard, '_git', lambda args, cwd: (128, '', 'fatal: dubious ownership')
    )

    ok, msg = git_guard.check_production_branch(tmp_path)

    assert ok is True
    assert '覆盖' in msg
