"""
采购模块共享工具函数

从 purchase_order_service.py 提取的重复逻辑，集中管理采购相关的纯函数工具。

包含：
- parse_source_order_ids: 解析采购订单关联的客户订单ID列表
"""
import json
import logging

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
