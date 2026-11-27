"""工作流供应链基线：最小权限 + Actions 钉 commit SHA。

C1/C2：仓库此前未声明 ``permissions``，工作流继承仓库默认 token 权限；
13 处 ``uses:`` 全是浮动 tag（``@v5`` / ``@v6``），tag 可被上游改指向，
等于把构建交给一个可变的远端引用。

本测试锁住两条不变量：顶层必须有 ``permissions``；每个 ``uses`` 必须是
40 位 commit SHA（允许尾随 ``# v5`` 可读注释）。
"""
from __future__ import annotations

import re
from pathlib import Path

WF = Path(__file__).resolve().parents[2] / '.github' / 'workflows'
WORKFLOWS = ('ci-cd.yml', 'refresh-requirements-lock.yml')
_SHA_RE = re.compile(r'^[0-9a-f]{40}$')


def _uses_refs():
    for name in WORKFLOWS:
        for lineno, line in enumerate((WF / name).read_text(encoding='utf-8').splitlines(), 1):
            stripped = line.strip()
            if 'uses:' not in stripped:
                continue
            ref = stripped.split('uses:', 1)[1].split('#', 1)[0].strip()
            yield name, lineno, ref


def test_all_actions_pinned_to_commit_sha() -> None:
    floating = [
        f'{name}:{lineno} {ref}'
        for name, lineno, ref in _uses_refs()
        if not _SHA_RE.match(ref.split('@')[-1])
    ]
    assert not floating, f'以下 uses 未钉 commit SHA: {floating}'


def test_ci_workflow_declares_minimal_permissions() -> None:
    text = (WF / 'ci-cd.yml').read_text(encoding='utf-8')
    assert re.search(r'^permissions:', text, re.MULTILINE), '未声明顶层 permissions'
    assert 'contents: read' in text


def test_refresh_workflow_only_skips_on_open_pr() -> None:
    """刷新机器人独占的分支上会累积已 MERGED 的历史 PR（本仓 #26）。

    2026-11-27：旧实现用 ``gh pr view "$branch" --json number`` 判断「已有 PR」，
    会命中已合并的旧 PR 而跳过创建，导致每周推送的新提交永远没有 PR、跑不了 CI
    （aee8027e 因此悬空）。只允许 state=OPEN 走跳过分支。
    """
    text = (WF / 'refresh-requirements-lock.yml').read_text(encoding='utf-8')
    assert '--json state' in text, '必须按 PR 状态判断，而非「该分支上存在任意 PR」'
    assert re.search(r'if \[ "\$pr_state" = "OPEN" \]; then', text), \
        '只有 OPEN 状态才允许跳过创建 PR'
    assert re.search(r"--json state --jq '\.state'[^\n]*\|\| true", text), \
        '必须用 --jq 取纯状态值，并用 || true 兜住「无 PR 时 gh 非零退出」（set -e 会杀 job）'
    assert '--json number' not in text, '旧判断（--json number）会把已合并 PR 误当打开中'
