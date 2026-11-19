"""生产启停 git 分支闸门回归（2026-10-17 审计 AUD-28）

缺陷：NSSM 服务直接吃工作区源码，重启前无人校验分支；2026-10-14 已有
75 分钟实害事故。本测试用临时 git 仓库验证闸门行为。
"""
import json
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


# ---------------------------------------------------------------------------
# 2026-11-05：未跟踪的纯文档目录不得阻断生产
#
# 事故：他人留下的 deliverables/*.html 未跟踪 → 脏工作区检查 fail-closed →
# erp-prod 反复被拒、NSSM 进 PAUSED，五个服务全停（2026-11-05 08:10）。
# 未跟踪的非 Python 文件不会被 import；真正危险的是已跟踪改动与未跟踪 .py。
# ---------------------------------------------------------------------------


def test_untracked_doc_directory_allowed(repo, monkeypatch):
    monkeypatch.delenv(git_guard.OVERRIDE_ENV, raising=False)
    monkeypatch.delenv(git_guard.DIRTY_OVERRIDE_ENV, raising=False)
    _git(repo, 'checkout', '-q', '-b', 'main')
    doc = repo / 'deliverables' / 'review'
    doc.mkdir(parents=True)
    (doc / 'index.html').write_text('<html></html>', encoding='utf-8')

    ok, msg = git_guard.check_production_branch(repo)

    assert ok is True, '未跟踪的纯文档目录不应阻断生产启动'
    assert '未跟踪' in msg


def test_untracked_python_file_blocks(repo, monkeypatch):
    """未跟踪的 .py 可能被 import，必须继续阻断（2026-10-22 事故形态）。"""
    monkeypatch.delenv(git_guard.OVERRIDE_ENV, raising=False)
    monkeypatch.delenv(git_guard.DIRTY_OVERRIDE_ENV, raising=False)
    _git(repo, 'checkout', '-q', '-b', 'main')
    (repo / 'new_module.py').write_text('x = 1', encoding='utf-8')

    ok, msg = git_guard.check_production_branch(repo)

    assert ok is False
    assert 'new_module.py' in msg


def test_untracked_directory_containing_python_blocks(repo, monkeypatch):
    """目录形式也要展开检查：目录里藏着 .py 同样阻断。"""
    monkeypatch.delenv(git_guard.OVERRIDE_ENV, raising=False)
    monkeypatch.delenv(git_guard.DIRTY_OVERRIDE_ENV, raising=False)
    _git(repo, 'checkout', '-q', '-b', 'main')
    pkg = repo / 'newpkg'
    pkg.mkdir()
    (pkg / 'mod.py').write_text('x = 1', encoding='utf-8')

    ok, msg = git_guard.check_production_branch(repo)

    assert ok is False
    assert 'newpkg' in msg


def test_dirty_override_writes_persistent_evidence(repo, monkeypatch, tmp_path):
    """P2-13（2026-10-17 审计）：覆盖开关放行必须**落盘留痕**。

    两个 override 只靠「环境变量=1」就能放行，事后没有任何痕迹 —— 一旦有人把它写进
    机器级环境变量或 NSSM 服务配置，闸门就长期静默失效（2026-11-02~04 的
    safe.directory 事故正是这种形态：每次启动只打一行警告，没人看）。
    """
    _git(repo, 'checkout', '-q', '-b', 'main')
    (repo / 'a.txt').write_text('changed', encoding='utf-8')      # 已跟踪文件被改 = 脏
    ledger = tmp_path / 'logs' / 'gate_override.jsonl'
    monkeypatch.setattr(git_guard, 'OVERRIDE_LEDGER', ledger)
    monkeypatch.delenv(git_guard.OVERRIDE_ENV, raising=False)
    monkeypatch.setenv(git_guard.DIRTY_OVERRIDE_ENV, '1')

    ok, msg = git_guard.check_production_branch(repo)

    assert ok is True and '放行' in msg
    entries = [
        json.loads(ln) for ln in ledger.read_text(encoding='utf-8').splitlines() if ln.strip()
    ]
    assert len(entries) == 1, f'每次覆盖必须恰好留一条痕迹，实际 {entries}'
    assert entries[0]['env'] == git_guard.DIRTY_OVERRIDE_ENV
    assert entries[0]['ts'] and entries[0]['detail'], '痕迹必须带时间与明细（否则事后没法查）'


def test_no_override_leaves_no_ledger(repo, monkeypatch, tmp_path):
    """阴性对照：没使用覆盖时不得凭空写痕迹（否则「有痕迹」不再等于「有人放行」）。"""
    _git(repo, 'checkout', '-q', '-b', 'main')
    ledger = tmp_path / 'logs' / 'gate_override.jsonl'
    monkeypatch.setattr(git_guard, 'OVERRIDE_LEDGER', ledger)
    monkeypatch.delenv(git_guard.OVERRIDE_ENV, raising=False)
    monkeypatch.delenv(git_guard.DIRTY_OVERRIDE_ENV, raising=False)

    ok, _msg = git_guard.check_production_branch(repo)

    assert ok is True
    assert not ledger.exists(), '未使用覆盖开关却写了留痕'


def test_branch_override_writes_persistent_evidence(repo, monkeypatch, tmp_path):
    """P2-13 的**第二条** override：非白名单分支放行同样必须落痕。

    变异实测（2026-11-19）：把 git_guard:136 的 _record_override 删掉，原有用例全绿 ——
    因为唯一的留痕用例只覆盖「脏工作区」那条（DIRTY_OVERRIDE_ENV）。也就是说
    「三处 override 各记一条」当时只有一处被钉住，另外两处删了没人知道。
    """
    _git(repo, 'checkout', '-q', '-b', 'feature-x')
    ledger = tmp_path / 'logs' / 'gate_override.jsonl'
    monkeypatch.setattr(git_guard, 'OVERRIDE_LEDGER', ledger)
    monkeypatch.setenv(git_guard.OVERRIDE_ENV, '1')
    monkeypatch.delenv(git_guard.DIRTY_OVERRIDE_ENV, raising=False)

    ok, msg = git_guard.check_production_branch(repo)

    assert ok is True and '覆盖' in msg
    entries = [
        json.loads(ln) for ln in ledger.read_text(encoding='utf-8').splitlines() if ln.strip()
    ]
    assert len(entries) == 1, f'分支覆盖必须恰好一条痕迹，实际 {entries}'
    assert entries[0]['env'] == git_guard.OVERRIDE_ENV
    assert entries[0]['branch'] == 'feature-x'
    assert entries[0]['ts'] and '分支' in entries[0]['detail']


def test_unreadable_branch_override_writes_persistent_evidence(tmp_path, monkeypatch):
    """P2-13 的**第三条** override：有 .git 却读不出分支时放行，同样必须落痕。"""
    ledger = tmp_path / 'logs' / 'gate_override.jsonl'
    monkeypatch.setattr(git_guard, 'OVERRIDE_LEDGER', ledger)
    monkeypatch.setenv(git_guard.OVERRIDE_ENV, '1')
    (tmp_path / '.git').mkdir()
    monkeypatch.setattr(
        git_guard, '_git', lambda args, cwd: (128, '', 'fatal: dubious ownership')
    )

    ok, msg = git_guard.check_production_branch(tmp_path)

    assert ok is True and '覆盖' in msg
    entries = [
        json.loads(ln) for ln in ledger.read_text(encoding='utf-8').splitlines() if ln.strip()
    ]
    assert len(entries) == 1, f'读不出分支的覆盖也必须留痕，实际 {entries}'
    assert entries[0]['env'] == git_guard.OVERRIDE_ENV
    assert entries[0]['branch'] == '(git 不可用)'
