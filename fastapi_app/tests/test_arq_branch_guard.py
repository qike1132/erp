"""ARQ worker 启动必须与 prod_runner 同口径拦非 main 分支。

背景（AGENTS §6.1-6）：erp-prod 直接吃工作区源码，工作区不在 main 时重启
就把分支代码跑进生产。prod_runner 已有闸门，但 NSSM 服务 erp-arq 用
`python -m arq fastapi_app.core.arq_app.WorkerSettings` 独立启动，绕过了它。
worker 同样执行工作区代码，因此必须补同一道闸门。

闸门只在 production 生效：开发机上跑 `arq` 通常就在功能分支，不应被打断。
"""
from __future__ import annotations

import pytest

from fastapi_app.core import arq_app


def test_rejects_non_main_branch_in_production(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        'server_manager.git_guard.check_production_branch',
        lambda *a, **k: (False, '当前分支 feature/x，不允许启动生产'),
    )
    with pytest.raises(RuntimeError, match='分支闸门'):
        arq_app._enforce_production_branch_guard(is_production=True)


def test_allows_main_branch_in_production(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        'server_manager.git_guard.check_production_branch',
        lambda *a, **k: (True, '当前分支 main'),
    )
    arq_app._enforce_production_branch_guard(is_production=True)  # 不抛即过


def test_skips_outside_production(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[int] = []

    def _record(*a, **k):
        calls.append(1)
        return False, 'blocked'

    monkeypatch.setattr('server_manager.git_guard.check_production_branch', _record)
    arq_app._enforce_production_branch_guard(is_production=False)
    assert calls == [], '非生产环境不该执行分支闸门'


def test_unavailable_guard_does_not_block_startup(monkeypatch: pytest.MonkeyPatch) -> None:
    """闸门自身不可用时 fail-open（与 prod_runner 一致），不得打死 production worker。"""
    def _explode(*a, **k):
        raise ImportError('git_guard unavailable')

    monkeypatch.setattr('server_manager.git_guard.check_production_branch', _explode)
    arq_app._enforce_production_branch_guard(is_production=True)
