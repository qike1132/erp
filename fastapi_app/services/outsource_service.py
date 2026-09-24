"""outsource_service(对外兼容入口)

从 outsource_service.py 按职责拆分为 services/outsource/ 子包。
- _common: 序列化/状态  - _queries: 查询
- _process_types: 工艺类型 CRUD  - _order_processes: 订单工艺生成与操作

本文件保留全部对外函数名的 re-export,历史调用方
`from fastapi_app.services.outsource_service import X` 保持不变。
"""
from fastapi_app.services.outsource._common import (  # noqa: F401
    _attach_progress_to_orders,
    _derive_status,
    _fmt_dt,
    _format_process_progress,
    _is_fully_received,
    _matches_process_status,
    _serialize_order_process,
    _serialize_process_type,
)
from fastapi_app.services.outsource._order_processes import (  # noqa: F401
    _collect_order_skus,
    _load_order_with_skus,
    auto_generate_for_order,
    delete_order_process,
    generate_order_processes,
    receive_order_process,
    receive_order_processes_batch,
    ship_order_process,
    ship_order_processes_batch,
    ship_processes_multi,
    sync_orders_for_product,
    sync_outsource_processes_for_order,
    update_order_process,
)
from fastapi_app.services.outsource._process_types import (  # noqa: F401
    batch_create_process_types,
    create_process_type,
    delete_process_type,
    get_presets_for_products,
    list_process_types,
    search_hubei_products,
    update_process_type,
)
from fastapi_app.services.outsource._queries import (  # noqa: F401
    _process_target_quantity,
    list_order_flows,
    list_order_processes,
    list_outsource_orders,
    list_shippable_processes,
    list_unshipped_processes,
)
from fastapi_app.services.outsource._shipments import (  # noqa: F401
    create_merged_shipment,
    create_shipment,
    create_shipments_batch,
    get_shipment,
    list_shipments,
    receive_shipment,
)
