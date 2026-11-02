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
