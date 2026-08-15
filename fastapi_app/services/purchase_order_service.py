"""
采购订单服务 — 向后兼容层。

原 facade 已扁平化至 purchase_center_service.py（领域事件订阅也移至该处）。
本文件仅保留 re-export 以兼容历史导入路径：
    from fastapi_app.services.purchase_order_service import get_purchase_orders

新代码请直接从 purchase_order_crud / purchase_order_query / purchase_order_generate 导入，
或统一从 purchase_center_service 导入。
"""

# 显式 re-export（替代 import *）：与 purchase_center_service 的公共导出面逐项对齐，
# 便于静态检查与未来收窄
from fastapi_app.services.purchase_center_service import (  # noqa: F401
    batch_complete_purchase_orders,
    batch_delete_purchase_orders,
    batch_get_customers,
    calculate_material,
    cleanup_orphan_pending_purchase_orders,
    complete_purchase_order,
    copy_bom_to_product,
    create_purchase_order,
    create_supplier,
    delete_purchase_order,
    delete_saved_query,
    delete_supplier,
    export_completed_orders,
    fetch_existing_pending_for_composite_ids,
    generate_purchase_orders_from_customer_orders,
    get_bom_preview,
    get_completed_order_quick_filters,
    get_completed_order_suggestions,
    get_completed_purchase_orders,
    get_customer_detail,
    get_customers,
    get_customers_statistics,
    get_factory_order_summary,
    get_modification_logs,
    get_product_bom,
    get_products,
    get_products_batch_bom,
    get_products_statistics,
    get_purchase_order,
    get_purchase_orders,
    get_saved_queries,
    get_search_suggestions,
    get_status_logs,
    get_supplier_order_summary,
    get_suppliers,
    get_unprocessed_orders,
    one_click_generate_order,
    product_has_bom,
    query_supplier_groups,
    save_factory_summary_edits,
    save_product_bom,
    save_query,
    search_products_for_bom_copy,
    update_purchase_order,
    update_supplier,
    use_saved_query,
)
# 下划线私有符号不随 import * 转发，显式补充
from fastapi_app.services.purchase_center_service import (  # noqa: F401
    _build_order_summary,
    _fetch_bom_data,
    _parse_source_order_ids,
)
