"""统一业务验证工具函数

消除各服务中重复的内联验证逻辑（数量范围、名称非空等），
提供统一的验证函数和错误消息格式。
"""
from typing import Any

from fastapi_app.core.business_rules import MAX_QUANTITY, MIN_QUANTITY


def validate_quantity_range(
    quantity: int,
    field_name: str = "数量",
    min_val: int | None = None,
    max_val: int | None = None,
) -> int:
    """验证数量是否在有效范围内，通过则返回原值。

    Args:
        quantity: 待验证的数量
        field_name: 字段名称（用于错误消息）
        min_val: 最小值，默认使用业务规则常量
        max_val: 最大值，默认使用业务规则常量

    Raises:
        ValueError: 数量超出范围时抛出
    """
    lo = min_val if min_val is not None else MIN_QUANTITY
    hi = max_val if max_val is not None else MAX_QUANTITY
    if quantity < lo or quantity > hi:
        raise ValueError(f"{field_name}必须在 {lo}-{hi} 之间")
    return quantity


def validate_not_empty(value: Any, field_name: str = "字段") -> str:
    """验证字符串非空（去除空白后），通过则返回去除空白后的字符串。

    Raises:
        ValueError: 值为空时抛出
    """
    if value is None:
        raise ValueError(f"{field_name}不能为空")
    str_value = str(value).strip()
    if not str_value:
        raise ValueError(f"{field_name}不能为空")
    return str_value
