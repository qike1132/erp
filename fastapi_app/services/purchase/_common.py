"""采购查询公共辅助

从 purchase_order_query_helpers.py 按主题拆出,行为与原实现完全一致。
"""
import logging

from fastapi_app.services.purchase_utils import parse_source_order_ids

logger = logging.getLogger(__name__)


def _parse_source_order_ids(po) -> list[int]:
    """解析采购订单关联的客户订单ID列表

    合并单值字段 source_order_id 与多值字段 source_order_ids（JSON/list）。
    多值字段的解析委托给 purchase_utils.parse_source_order_ids。
    """
    ids: list[int] = []
    if po.source_order_id:
        ids.append(po.source_order_id)
    ids.extend(parse_source_order_ids(po.source_order_ids))
    return ids