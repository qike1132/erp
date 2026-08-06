"""
采购订单服务 — 向后兼容层。

原 facade 已扁平化至 purchase_center_service.py（领域事件订阅也移至该处）。
本文件仅保留 re-export 以兼容历史导入路径：
    from fastapi_app.services.purchase_order_service import get_purchase_orders

新代码请直接从 purchase_order_crud / purchase_order_query / purchase_order_generate 导入，
或统一从 purchase_center_service 导入。
"""

from fastapi_app.services.purchase_order_crud import (  # noqa: F401
    _build_order_summary,
    batch_complete_purchase_orders,
    cleanup_orphan_pending_purchase_orders,
    complete_purchase_order,
    create_purchase_order,
    delete_purchase_order,
    save_factory_summary_edits,
    update_purchase_order,
)
from fastapi_app.services.purchase_order_generate import (  # noqa: F401
    fetch_existing_pending_for_composite_ids,
    generate_purchase_orders_from_customer_orders,
    one_click_generate_order,
)
from fastapi_app.services.purchase_order_query import (  # noqa: F401
    _fetch_bom_data,
    _parse_source_order_ids,
    export_completed_orders,
    get_completed_order_quick_filters,
    get_completed_order_suggestions,
    get_completed_purchase_orders,
    get_factory_order_summary,
    get_purchase_order,
    get_purchase_orders,
    get_supplier_order_summary,
    get_unprocessed_orders,
    query_supplier_groups,
)
