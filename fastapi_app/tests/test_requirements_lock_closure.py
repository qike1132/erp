"""锁文件闭包校验：锁内不得存在无法从声明推导出的包。

C3 的背景：原门禁只比对 ``.txt`` 里的**直接声明**，锁里多出的包「默认不判定」，
所以往 ``.lock`` 追加一行任意包即可过门禁，而 CI 会真的安装它。
``--strict`` 能发现，但它重新联网解析，上游每发补丁就让全档同时失配——
2026-10-26 已因此把默认判据从「整树比对」改成「只看直接依赖」。

本校验改用锁内自带的 ``# via`` 依赖图做确定性闭包检查：不需要网络，
不受上游发版影响，又能拦住注入。
"""
from __future__ import annotations

from scripts.check_requirements_lock import closure_failures


def test_declared_closure_passes() -> None:
    text = (
        'fastapi==1.0 \\\n'
        '    --hash=sha256:aa\n'
        '    # via -r requirements/x.txt\n'
        'starlette==1.0\n'
        '    # via\n'
        '    #   -c requirements/x.lock\n'
        '    #   fastapi\n'
    )
    assert closure_failures(text, {'fastapi'}) == []


def test_transitive_chain_is_reachable() -> None:
    text = (
        'a==1.0\n    # via -r requirements/x.txt\n'
        'b==1.0\n    # via a\n'
        'c==1.0\n    # via b\n'
    )
    assert closure_failures(text, {'a'}) == []


def test_injected_package_without_via_is_rejected() -> None:
    text = (
        'fastapi==1.0\n    # via -r requirements/x.txt\n'
        'evil==9.9\n'
    )
    failures = closure_failures(text, {'fastapi'})
    assert any('evil' in f for f in failures), failures


def test_package_with_forged_unreachable_via_is_rejected() -> None:
    text = (
        'fastapi==1.0\n    # via -r requirements/x.txt\n'
        'evil==9.9\n    # via not-a-locked-package\n'
    )
    failures = closure_failures(text, {'fastapi'})
    assert any('evil' in f for f in failures), failures


def test_real_locks_have_no_orphans() -> None:
    """真实锁必须整体通过闭包校验（防止规则写反把全部判红）。"""
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    for tier in ('base', 'dev', 'test', 'ocr', 's3', 'desktop', 'migration'):
        lock = root / 'requirements' / f'{tier}.lock'
        txt = root / 'requirements' / f'{tier}.txt'
        from scripts.check_requirements_lock import parse_declared

        declared = {req.name for req in parse_declared(txt)}
        failures = closure_failures(lock.read_text(encoding='utf-8'), declared)
        assert failures == [], f'{tier}.lock: {failures}'
