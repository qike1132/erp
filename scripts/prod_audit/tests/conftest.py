"""生产审核 pipeline 测试共享 fixtures。"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest

# 确保项目根目录在 sys.path 中
_PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from scripts.prod_audit.config_loader import AuditConfig, ConfigLoader, RulesRegistry
from scripts.prod_audit.evidence_archiver import EvidenceArchiver
from scripts.prod_audit.tests._helpers import (
    MockLayerExecutor,
    build_mock_executors,
    make_issue,
    make_layer_result,
)

# 默认配置/规则文件路径
_CONFIG_PATH = _PROJECT_ROOT / "scripts" / "prod_audit" / "audit_config.yaml"
_RULES_PATH = _PROJECT_ROOT / "scripts" / "prod_audit" / "rules_registry.yaml"


# ---------------------------------------------------------------------------
# 路径与配置 fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def project_root() -> Path:
    """项目根目录。"""
    return _PROJECT_ROOT


@pytest.fixture
def config_path() -> Path:
    """审核配置文件路径。"""
    return _CONFIG_PATH


@pytest.fixture
def rules_path() -> Path:
    """规则注册表文件路径。"""
    return _RULES_PATH


@pytest.fixture
def audit_config() -> AuditConfig:
    """加载实际审核配置。"""
    return ConfigLoader.load(_CONFIG_PATH)


@pytest.fixture
def rules_registry() -> RulesRegistry:
    """加载实际规则注册表。"""
    return ConfigLoader.load_rules(_RULES_PATH)


@pytest.fixture
def evidence_dir(tmp_path: Path) -> Path:
    """临时证据目录。"""
    return tmp_path / "evidence"


@pytest.fixture
def archiver(evidence_dir: Path) -> EvidenceArchiver:
    """证据归档器实例。"""
    return EvidenceArchiver(evidence_dir)


@pytest.fixture
def issue_builder():
    """返回 :class:`IssueBuilder` 类。"""
    from scripts.prod_audit.base.issue_builder import IssueBuilder

    return IssueBuilder


# ---------------------------------------------------------------------------
# 工厂 fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def make_issue_factory():
    """返回 :func:`make_issue` 工厂。"""
    return make_issue


@pytest.fixture
def make_result_factory():
    """返回 :func:`make_layer_result` 工厂。"""
    return make_layer_result


@pytest.fixture
def mock_executor_factory():
    """返回 :class:`MockLayerExecutor` 工厂。"""

    def _factory(**kwargs: Any) -> MockLayerExecutor:
        return MockLayerExecutor(**kwargs)

    return _factory


@pytest.fixture
def mock_executors_factory(audit_config: AuditConfig):
    """返回 :func:`build_mock_executors` 工厂(绑定实际配置)。"""

    def _factory(**kwargs: Any) -> dict[str, MockLayerExecutor]:
        return build_mock_executors(audit_config, **kwargs)

    return _factory


# ---------------------------------------------------------------------------
# 上下文 fixture
# ---------------------------------------------------------------------------


@pytest.fixture
def audit_context_factory(audit_config: AuditConfig, rules_registry: RulesRegistry, archiver: EvidenceArchiver):
    """返回构造 :class:`AuditContext` 的工厂。"""
    from scripts.prod_audit.base.layer_base import AuditContext

    def _factory(
        previous_results: list | None = None,
        baseline_dir: Path | None = None,
    ) -> AuditContext:
        return AuditContext(
            config=audit_config,
            rules=rules_registry,
            archiver=archiver,
            baseline_dir=baseline_dir or archiver.evidence_dir,
            previous_results=list(previous_results) if previous_results else [],
        )

    return _factory
