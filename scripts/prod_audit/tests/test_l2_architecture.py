"""L2 分层审核 —— 反向依赖判据回归测试(2026-10-20)。

背景(审计 #18a,误报型检查器缺陷):

    ``l2_architecture.py`` 的禁止清单把 ``core → services`` 列为 HIGH 违规,
    但 AGENTS.md §2 明文写着「core 是**组合根**,允许 import services(契约未禁止,
    勿当越层修)」——检查器把**契约允许**的依赖判成违规,每次 prod_audit 必然
    报 1 条 HIGH 误报(fastapi_app/core/arq_app.py)。长期「狼来了」会训练团队
    忽略 L2 的真实发现。

本文件的作用是**让这个误报无法回归**,同时守住 L2 其它真实判据:

    - 真实仓库不得报 core → services;
    - core → endpoints / endpoints → models / services → endpoints 仍须报。
"""

from __future__ import annotations

import pytest

from scripts.prod_audit.base.issue_builder import IssueBuilder
from scripts.prod_audit.layers.l2_architecture import L2Architecture


@pytest.fixture
def layer() -> L2Architecture:
    """L2 层执行器实例。"""
    return L2Architecture()


def _reverse_deps(layer: L2Architecture, graph: dict[str, set[str]]) -> list:
    """跑反向依赖检测,返回 issue 列表。"""
    return layer._detect_reverse_dependencies(graph, IssueBuilder())


# ---------------------------------------------------------------------------
# 1. 真实仓库: core → services 不得被报
# ---------------------------------------------------------------------------


def test_real_repo_has_no_core_to_services_violation(layer: L2Architecture) -> None:
    """真实仓库不得出现 core → services 反向依赖告警(契约允许的组合根模式)。"""
    graph = layer._build_dependency_graph()
    issues = _reverse_deps(layer, graph)

    offenders = [
        i for i in issues if "core → services" in i.description
    ]
    assert offenders == [], (
        f"core → services 被误报为分层违规(AGENTS.md §2: core 是组合根): "
        f"{[(i.file, i.description) for i in offenders]}"
    )


def test_real_repo_core_only_depends_on_allowed_layers(layer: L2Architecture) -> None:
    """core 层只允许依赖 core 自身(不得依赖 endpoints)。"""
    graph = layer._build_dependency_graph()
    issues = _reverse_deps(layer, graph)

    core_offenders = [
        i for i in issues if i.description.startswith("core →")
    ]
    assert core_offenders == [], (
        f"core 层出现非法依赖: {[(i.file, i.description) for i in core_offenders]}"
    )


# ---------------------------------------------------------------------------
# 2. 判据本身: 该报的仍要报
# ---------------------------------------------------------------------------


def test_core_to_endpoints_is_still_reported(layer: L2Architecture) -> None:
    """core → endpoints 仍是违规(core 不得依赖 API 层)。"""
    issues = _reverse_deps(layer, {"core:fastapi_app/core/x.py": {"endpoints"}})

    assert len(issues) == 1, f"core → endpoints 应报 1 条,实际 {issues}"
    assert "core → endpoints" in issues[0].description


def test_endpoints_to_models_is_still_reported(layer: L2Architecture) -> None:
    """endpoints → models 仍是违规。"""
    issues = _reverse_deps(layer, {"endpoints:fastapi_app/api/v1/endpoints/x.py": {"models"}})

    assert len(issues) == 1, f"endpoints → models 应报 1 条,实际 {issues}"


def test_services_to_endpoints_is_still_reported(layer: L2Architecture) -> None:
    """services → endpoints 仍是违规。"""
    issues = _reverse_deps(layer, {"services:fastapi_app/services/x.py": {"endpoints"}})

    assert len(issues) == 1, f"services → endpoints 应报 1 条,实际 {issues}"


def test_core_to_services_is_allowed(layer: L2Architecture) -> None:
    """core → services 不报(AGENTS.md §2 组合根)。"""
    issues = _reverse_deps(layer, {"core:fastapi_app/core/x.py": {"services"}})

    assert issues == [], f"core → services 不应报,实际 {[(i.description) for i in issues]}"
