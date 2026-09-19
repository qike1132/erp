"""
采购模块共享工具函数

从 purchase_order_service.py 提取的重复逻辑，集中管理采购相关的纯函数工具。

包含：
- parse_source_order_ids: 解析采购订单关联的客户订单ID列表
- normalize_spare_rate: 归一化损耗率（千分之几）
- calc_spare_quantity: 计算备品数量（前后端同源的唯一后端实现）
"""
import json
import logging
import math

logger = logging.getLogger(__name__)


def parse_source_order_ids(source_order_ids: str | list | None) -> list[int]:
    """解析采购订单的 source_order_ids 字段为整数 ID 列表。

    该字段可能以两种形式存储：
    - JSON 字符串（如 '[1, 2, 3]'）
    - 已反序列化的 list

    解析失败时返回空列表，不抛出异常，与原内联实现保持一致。

    注意：本函数仅处理 source_order_ids 字段本身；
    若需同时合并 source_order_id（单值字段），请由调用方自行追加。

    Args:
        source_order_ids: 原始字段值，可为 JSON 字符串、list 或 None。

    Returns:
        解析后的整数 ID 列表；输入为空或解析失败时返回空列表。
    """
    if not source_order_ids:
        return []
    try:
        parsed = json.loads(source_order_ids) if isinstance(source_order_ids, str) else source_order_ids
        return [int(x) for x in parsed]
    except (ValueError, TypeError):
        return []


def normalize_spare_rate(rate: float | None) -> float | None:
    """归一化损耗率（单位：千分之几）。

    口径与前端 `useSummaryModal.calcSpareQuantity` 保持一致：
    - `None` → `None`（语义为「不覆盖已存值 / 跳过」）；
    - 非数值或非有限值（NaN/Inf）→ `0.0`；
    - `< 0`（非法）→ `0.0`；
    - `> 1000` → 截断为 `1000.0`（与前端输入框 `max=1000` 一致）；
    - 其余原值返回。

    Args:
        rate: 原始损耗率，可为 None。

    Returns:
        归一化后的损耗率；输入为 None 时返回 None。
    """
    if rate is None:
        return None
    try:
        value = float(rate)
    except (TypeError, ValueError):
        return 0.0
    if not math.isfinite(value) or value < 0:
        return 0.0
    if value > 1000:
        return 1000.0
    return value


def calc_spare_quantity(qty: float | None, rate: float | None) -> int:
    """计算备品数量：`ceil(qty × rate / 1000)`（前后端同源的唯一后端实现）。

    与前端 `calcSpareQuantity` 语义逐字一致：
    - 归一化后 `rate` 为 `None` / `<= 0`，或 `qty` 非有限 / `<= 0` → `0`；
    - 否则返回 `math.ceil(qty × rate / 1000)`（向上取整到整数）。

    Args:
        qty: 订单数量（可含小数）。
        rate: 损耗率（千分之几）。

    Returns:
        向上取整后的备品数量（非负整数）。
    """
    normalized = normalize_spare_rate(rate)
    if normalized is None or normalized <= 0:
        return 0
    try:
        quantity = float(qty)
    except (TypeError, ValueError):
        return 0
    if not math.isfinite(quantity) or quantity <= 0:
        return 0
    return math.ceil(quantity * normalized / 1000)
