"""12 层审核执行器子包。

层执行器按 ``layer_id`` 顺序加载:
``l1_static`` ~ ``l12_report``。各层执行器继承
:class:`scripts.prod_audit.base.LayerBase` 并实现 ``run`` 方法。
本包在基础设施阶段仅提供占位,具体实现由后续任务组完成。
"""

LAYER_MODULE_NAMES: dict[str, str] = {
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

LAYER_ORDER: tuple[str, ...] = (
    "L1",
    "L2",
    "L3",
    "L4",
    "L5",
    "L6",
    "L7",
    "L8",
    "L9",
    "L10",
    "L11",
    "L12",
)

__all__ = ["LAYER_MODULE_NAMES", "LAYER_ORDER"]
