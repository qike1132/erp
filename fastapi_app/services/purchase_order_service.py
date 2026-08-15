"""
采购订单服务 — 向后兼容层。

原 facade 已扁平化至 purchase_center_service.py（领域事件订阅也移至该处）。
本文件仅保留 re-export 以兼容历史导入路径：
    from fastapi_app.services.purchase_order_service import get_purchase_orders

新代码请直接从 purchase_order_crud / purchase_order_query / purchase_order_generate 导入，
或统一从 purchase_center_service 导入。
"""

# 公共符号统一从 facade 转发，避免维护两份导入列表
from fastapi_app.services.purchase_center_service import *  # noqa: F401, F403
# 下划线私有符号不随 import * 转发，显式补充
from fastapi_app.services.purchase_center_service import (  # noqa: F401
    _build_order_summary,
    _fetch_bom_data,
    _parse_source_order_ids,
)
