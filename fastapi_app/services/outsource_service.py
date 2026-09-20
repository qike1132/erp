"""outsource_service(对外兼容入口)

从 outsource_service.py 按职责拆分为 services/outsource/ 子包。
- _common: 序列化/状态  - _queries: 查询
- _process_types: 工艺类型 CRUD  - _order_processes: 订单工艺生成与操作

本文件保留全部对外函数名的 re-export,历史调用方
`from fastapi_app.services.outsource_service import X` 保持不变。
"""
from fastapi_app.services.outsource._common import (  # noqa: F401
    _fmt_dt,
    _serialize_process_type,
    _serialize_order_process,
    _is_fully_received,
    _derive_status,
    _format_process_progress,
    _matches_process_status,
    _attach_progress_to_orders,
)
from fastapi_app.services.outsource._order_processes import (  # noqa: F401
    _load_order_with_skus,
    _collect_order_skus,
    sync_outsource_processes_for_order,
    auto_generate_for_order,
    generate_order_processes,
    sync_orders_for_product,
    update_order_process,
    ship_order_process,
    ship_order_processes_batch,
    ship_processes_multi,
    receive_order_process,
    receive_order_processes_batch,
    delete_order_process,
)
from fastapi_app.services.outsource._process_types import (  # noqa: F401
    list_process_types,
    create_process_type,
    batch_create_process_types,
    update_process_type,
    delete_process_type,
    get_presets_for_products,
    search_hubei_products,
)
from fastapi_app.services.outsource._queries import (  # noqa: F401
    _process_target_quantity,
    list_outsource_orders,
    list_order_processes,
    list_order_flows,
    list_unshipped_processes,
    list_shippable_processes,
)
from fastapi_app.services.outsource._shipments import (  # noqa: F401
    create_shipment,
    create_shipments_batch,
    get_shipment,
    list_shipments,
    receive_shipment,
)
