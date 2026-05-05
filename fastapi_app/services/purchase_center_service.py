"""
采购中心服务层 - 业务逻辑（子模块重导出 facade）

原始 1922 行 God File 已拆分为以下子模块：
- purchase_product_service: 产品/BOM API + 物料计算
- purchase_supplier_service: 供应商 CRUD + 信息同步
- purchase_history_service: 修改历史/保存查询/状态日志
- purchase_bom_copy_service: BOM 复制功能
- purchase_customer_service: 客户管理 API
- purchase_order_service: 采购订单 CRUD + 汇总

此文件保留所有原始导入路径的向后兼容，endpoint 层通过
`from fastapi_app.services import purchase_center_service as svc` 访问。
"""

from fastapi_app.services.purchase_bom_copy_service import (  # noqa: F401
    batch_delete_purchase_orders,
    copy_bom_to_product,
    get_bom_preview,
    search_products_for_bom_copy,
)
from fastapi_app.services.purchase_customer_service import (  # noqa: F401
    batch_get_customers,
    get_customer_detail,
    get_customers,
    get_customers_statistics,
)
from fastapi_app.services.purchase_history_service import (  # noqa: F401
    delete_saved_query,
    get_modification_logs,
    get_saved_queries,
    get_status_logs,
    save_query,
    use_saved_query,
)
from fastapi_app.services.purchase_order_service import (  # noqa: F401
    batch_complete_purchase_orders,
    cleanup_orphan_pending_purchase_orders,
    complete_purchase_order,
    create_purchase_order,
    delete_purchase_order,
    export_completed_orders,
    generate_purchase_order_no,
    generate_purchase_orders_from_customer_orders,
    get_completed_order_quick_filters,
    get_completed_order_suggestions,
    get_completed_purchase_orders,
    get_factory_order_summary,
    get_purchase_order,
    get_purchase_orders,
    get_supplier_order_summary,
    get_unprocessed_orders,
    one_click_generate_order,
    query_supplier_groups,
    save_factory_summary_edits,
    update_purchase_order,
)
from fastapi_app.services.purchase_product_service import (  # noqa: F401
    calculate_material,
    get_product_bom,
    get_products,
    get_products_batch_bom,
    get_products_statistics,
    get_search_suggestions,
    product_has_bom,
    save_product_bom,
)
from fastapi_app.services.purchase_supplier_service import (  # noqa: F401
    create_supplier,
    delete_supplier,
    get_supplier_materials,
    get_suppliers,
    update_supplier,
)
