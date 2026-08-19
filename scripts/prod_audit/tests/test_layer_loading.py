"""Group 14.1 — 验证 12 层执行器加载。

测试内容:
    - 12 层类均可导入(通过实际文件名或 LAYER_MODULE_NAMES)
    - 每层 layer_id / layer_name / weight 正确
    - 权重之和 = 1.0
    - :func:`_load_layer_executor` 动态加载(可加载的层返回实例)
"""

from __future__ import annotations

import importlib

import pytest

from scripts.prod_audit.base.layer_base import LayerBase
from scripts.prod_audit.layers import LAYER_MODULE_NAMES, LAYER_ORDER
from scripts.prod_audit.orchestrator import _load_layer_executor

# 期望的层元数据(layer_id → (class_name, layer_name, weight))
_EXPECTED_LAYER_META: dict[str, tuple[str, str, float]] = {
    "L1": ("L1StaticAnalysis", "静态分析门禁审核", 0.10),
    "L2": ("L2Architecture", "架构与分层审核", 0.08),
    "L3": ("L3BusinessLogic", "业务逻辑与正确性审核", 0.12),
    "L4": ("L4DataAccess", "数据访问层审核", 0.10),
    "L5": ("L5ApiContract", "API 契约与版本兼容审核", 0.08),
    "L6": ("L6Security", "安全蓝红队审核", 0.15),
    "L7": ("L7Performance", "性能与可扩展性审核", 0.10),
    "L8": ("L8Observability", "可观测性审核", 0.07),
    "L9": ("L9TestQuality", "测试质量审核", 0.08),
    "L10": ("L10Frontend", "前端与移动端审核", 0.05),
    "L11": ("L11Deployment", "部署就绪与配置审核", 0.04),
    "L12": ("L12Report", "报告与上线决策", 0.03),
}

# 实际文件名(L10/L11 文件名与 LAYER_MODULE_NAMES 不一致)
_ACTUAL_MODULE_FILES: dict[str, str] = {
    "L1": "l1_static",
    "L2": "l2_architecture",
    "L3": "l3_business_logic",
    "L4": "l4_data_access",
    "L5": "l5_api_contract",
    "L6": "l6_security",
    "L7": "l7_performance",
    "L8": "l8_observability",
    "L9": "l9_test_quality",
    "L10": "l10_frontend",
    "L11": "l11_deployment",
    "L12": "l12_report",
}

# LAYER_MODULE_NAMES 中映射与实际文件名一致的层(可被 _load_layer_executor 加载)
_LOADABLE_LAYERS: list[str] = [
    lid for lid in LAYER_ORDER
    if LAYER_MODULE_NAMES.get(lid) == _ACTUAL_MODULE_FILES.get(lid)
]


def _find_layer_class(module: object) -> type[LayerBase] | None:
    """在模块中查找 LayerBase 子类。"""
    for attr_name in dir(module):
        attr = getattr(module, attr_name)
        if (
            isinstance(attr, type)
            and issubclass(attr, LayerBase)
            and attr is not LayerBase
        ):
            return attr
    return None


# ---------------------------------------------------------------------------
# 14.1a 12 层模块均可导入(通过实际文件名)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("layer_id", list(LAYER_ORDER))
def test_layer_module_importable(layer_id: str) -> None:
    """每层模块(实际文件)均可导入。"""
    module_name = _ACTUAL_MODULE_FILES[layer_id]
    full_module = f"scripts.prod_audit.layers.{module_name}"
    module = importlib.import_module(full_module)
    assert module is not None


@pytest.mark.parametrize("layer_id", list(LAYER_ORDER))
def test_layer_class_exists(layer_id: str) -> None:
    """每层模块定义了 :class:`LayerBase` 子类。"""
    module_name = _ACTUAL_MODULE_FILES[layer_id]
    full_module = f"scripts.prod_audit.layers.{module_name}"
    module = importlib.import_module(full_module)
    cls = _find_layer_class(module)
    assert cls is not None, f"Layer {layer_id} module {full_module} has no LayerBase subclass"


# ---------------------------------------------------------------------------
# 14.1b 层元数据正确
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("layer_id", list(LAYER_ORDER))
def test_layer_metadata(layer_id: str) -> None:
    """每层 layer_id / layer_name / weight 与期望一致。"""
    module_name = _ACTUAL_MODULE_FILES[layer_id]
    full_module = f"scripts.prod_audit.layers.{module_name}"
    module = importlib.import_module(full_module)

    expected_cls_name, expected_name, expected_weight = _EXPECTED_LAYER_META[layer_id]
    cls = _find_layer_class(module)

    assert cls is not None
    assert cls.__name__ == expected_cls_name
    assert cls.layer_id == layer_id
    assert cls.layer_name == expected_name
    assert cls.weight == pytest.approx(expected_weight)


# ---------------------------------------------------------------------------
# 14.1c 权重之和 = 1.0
# ---------------------------------------------------------------------------


def test_weights_sum_to_one() -> None:
    """12 层权重之和 = 1.0。"""
    total = sum(weight for _, _, weight in _EXPECTED_LAYER_META.values())
    assert total == pytest.approx(1.0)


def test_layer_order_count() -> None:
    """LAYER_ORDER 含 12 层。"""
    assert len(LAYER_ORDER) == 12
    assert LAYER_ORDER == (
        "L1", "L2", "L3", "L4", "L5", "L6",
        "L7", "L8", "L9", "L10", "L11", "L12",
    )


def test_layer_module_names_count() -> None:
    """LAYER_MODULE_NAMES 含 12 层映射。"""
    assert len(LAYER_MODULE_NAMES) == 12
    assert set(LAYER_MODULE_NAMES.keys()) == set(LAYER_ORDER)


# ---------------------------------------------------------------------------
# 14.1d 动态加载(仅测试可加载的层)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("layer_id", _LOADABLE_LAYERS)
def test_load_layer_executor_returns_instance(layer_id: str) -> None:
    """_load_layer_executor 返回 :class:`LayerBase` 实例(可加载的层)。"""
    executor = _load_layer_executor(layer_id)
    assert executor is not None
    assert isinstance(executor, LayerBase)
    assert executor.layer_id == layer_id


def test_load_layer_executor_unknown_returns_none() -> None:
    """未知 layer_id 返回 None。"""
    assert _load_layer_executor("L99") is None
    assert _load_layer_executor("INVALID") is None


@pytest.mark.parametrize("layer_id", _LOADABLE_LAYERS)
def test_loaded_executor_metadata(layer_id: str) -> None:
    """动态加载的执行器元数据正确。"""
    executor = _load_layer_executor(layer_id)
    assert executor is not None
    _, expected_name, expected_weight = _EXPECTED_LAYER_META[layer_id]
    assert executor.layer_name == expected_name
    assert executor.weight == pytest.approx(expected_weight)


def test_all_12_layer_classes_have_correct_metadata() -> None:
    """所有 12 层类(通过实际文件加载)元数据正确。"""
    for layer_id in LAYER_ORDER:
        module_name = _ACTUAL_MODULE_FILES[layer_id]
        full_module = f"scripts.prod_audit.layers.{module_name}"
        module = importlib.import_module(full_module)
        cls = _find_layer_class(module)
        assert cls is not None
        assert cls.layer_id == layer_id
