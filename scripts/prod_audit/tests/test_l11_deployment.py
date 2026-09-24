"""L11 部署就绪层 —— 判据回归测试(2026-09-24)。

背景(两个已修缺陷,同一病根: 判据照「通用 Web 项目模板」写,而本仓库是
**内网 Windows 原生 + NSSM**):

    1. ``_check_migrations`` **假阴性**: 原实现只找仓库根的 ``alembic.ini`` /
       ``alembic/`` / ``fastapi_app/alembic/``,本仓库三者皆无 ⇒ 直接
       ``return "Alembic 未配置,跳过迁移检查"`` —— **整个迁移检查被静默跳过**,
       真实 schema 漂移会被无声放过。
    2. ``_check_container_config`` **假阳性**: 原实现只认 ``Dockerfile`` /
       ``docker-compose.*`` / ``deploy-*.ps1``(后两者已于 commit 15e13a79 删除)
       ⇒ 稳定输出 ``L11-CONTAINER-001``。

本文件的作用是**让这两个缺陷无法回归**: 若把判据改回「模板假设」,下列用例会失败。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from scripts.prod_audit.base.issue_builder import IssueBuilder
from scripts.prod_audit.layers import l11_deployment as l11
from scripts.prod_audit.layers.l11_deployment import L11Deployment

_RULE_CONTAINER = "L11-CONTAINER-001"
_RULE_CONFIG = "L11-CONFIG-MISSING-001"


@pytest.fixture
def layer() -> L11Deployment:
    """L11 层执行器实例。"""
    return L11Deployment()


async def _run(layer: L11Deployment, name: str) -> tuple[list, str]:
    """调用某个子检查,返回 ``(issues, raw)``。"""
    return await getattr(layer, name)(IssueBuilder())


def _rules(issues: list) -> set[str]:
    return {i.rule_id for i in issues}


# ---------------------------------------------------------------------------
# 1. 迁移检查: 必须识别本仓库的 migrations/ 布局,且不得静默跳过
# ---------------------------------------------------------------------------


async def test_migrations_detects_repo_layout(layer: L11Deployment, project_root: Path) -> None:
    """本仓库实际布局(migrations/alembic.ini + migrations/versions)必须被识别。

    修复前: raw 只有「Alembic 未配置,跳过迁移检查」⇒ 本用例失败。
    """
    issues, raw = await _run(layer, "_check_migrations")

    assert "migrations/alembic.ini" in raw, f"未识别本仓库 ini 路径, raw={raw!r}"
    assert "migrations/versions" in raw, f"未识别 versions 目录, raw={raw!r}"
    assert issues == [], f"本仓库迁移就绪,不应有 issue: {[(i.rule_id, i.description) for i in issues]}"


async def test_migrations_reports_real_migration_count(layer: L11Deployment) -> None:
    """必须真的数出迁移文件数(证明检查真的执行了,而不是跳过)。"""
    _, raw = await _run(layer, "_check_migrations")

    assert "migration_files: " in raw, f"未输出迁移文件数, raw={raw!r}"
    count = int(raw.split("migration_files: ")[1].split()[0])
    assert count > 0, f"迁移文件数应 > 0, 实际 {count}"


async def test_migrations_not_silently_skipped_when_config_absent(
    layer: L11Deployment, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """找不到 Alembic 配置时,必须发 LOW 提示(而非静默返回空 issue)。

    修复前: issues == [] 且 raw 只有一句「跳过」⇒ 本用例失败。
    """
    monkeypatch.setattr(l11, "PROJECT_ROOT", tmp_path)

    issues, raw = await _run(layer, "_check_migrations")

    assert len(issues) == 1, f"「跳过」必须可见, 实际 issues={issues!r}, raw={raw!r}"
    assert issues[0].rule_id == _RULE_CONFIG
    assert "跳过" in issues[0].description


# ---------------------------------------------------------------------------
# 2. 部署就绪检查: Windows 原生 NSSM 必须被认作有效部署路径
# ---------------------------------------------------------------------------


async def test_container_check_accepts_native_nssm_deployment(layer: L11Deployment) -> None:
    """本仓库有 NSSM 部署证据 ⇒ 不得报 L11-CONTAINER-001。

    修复前: 稳定报该 MEDIUM issue ⇒ 本用例失败。
    """
    issues, raw = await _run(layer, "_check_container_config")

    assert _RULE_CONTAINER not in _rules(issues), (
        f"本仓库是 Windows 原生 NSSM 部署, 不应要求 Dockerfile: raw={raw!r}"
    )
    assert "native_nssm=True" in raw, f"未识别 NSSM 部署证据, raw={raw!r}"


async def test_container_check_detects_nssm_from_script(
    layer: L11Deployment, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """仅凭运维脚本里的 nssm 关键字也应识别为已具备部署路径。"""
    (tmp_path / "restart_prod.ps1").write_text(
        "# 正确姿势: nssm restart erp-prod\n", encoding="utf-8"
    )
    monkeypatch.setattr(l11, "PROJECT_ROOT", tmp_path)

    issues, raw = await _run(layer, "_check_container_config")

    assert _RULE_CONTAINER not in _rules(issues), f"应识别脚本证据, raw={raw!r}"
    assert "restart_prod.ps1" in raw, f"证据来源应出现在 raw 中, raw={raw!r}"


async def test_container_check_still_flags_when_no_deploy_path(
    layer: L11Deployment, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """两者皆无时仍须报 L11-CONTAINER-001(防止「修假阳性」变成「永真」)。"""
    monkeypatch.setattr(l11, "PROJECT_ROOT", tmp_path)

    issues, _ = await _run(layer, "_check_container_config")

    assert _RULE_CONTAINER in _rules(issues), "无任何部署路径时必须报问题"


async def test_container_check_still_validates_dockerfile_non_root(
    layer: L11Deployment, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """走容器路径时,原有「非 root 用户」校验不得丢失。"""
    (tmp_path / "Dockerfile").write_text("FROM python:3.13\n", encoding="utf-8")
    monkeypatch.setattr(l11, "PROJECT_ROOT", tmp_path)

    issues, raw = await _run(layer, "_check_container_config")

    assert "dockerfile_non_root_user: False" in raw, f"raw={raw!r}"
    assert _RULE_CONTAINER in _rules(issues), "Dockerfile 以 root 运行时应报问题"


# ---------------------------------------------------------------------------
# 3. 契约守卫: 层元数据不得改动(被 test_layer_loading.py 依赖)
# ---------------------------------------------------------------------------


def test_layer_metadata_unchanged() -> None:
    """layer_id / layer_name / weight 是外部契约,不得改动。"""
    assert L11Deployment.layer_id == "L11"
    assert L11Deployment.layer_name == "部署就绪与配置审核"
    assert L11Deployment.weight == pytest.approx(0.04)


def test_deploy_candidates_have_no_phantom_files() -> None:
    """部署脚本候选里不得再出现已删除的幽灵文件名(否则检查会静默失效)。"""
    phantom = {"deploy-windows.ps1", "deploy_nginx.ps1", "build_and_release.py"}
    assert phantom.isdisjoint(l11._DEPLOY_SCRIPTS), (
        f"候选列表含已删除/从未存在的文件: {sorted(phantom & set(l11._DEPLOY_SCRIPTS))}"
    )
