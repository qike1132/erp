"""material_registration_service(对外兼容入口)

从 material_registration_service.py 按职责拆分为 services/material_registration/ 子包。
- _queries: 查询域  - _commands: 命令域  - _export: 导出

本文件保留全部对外函数名的 re-export,历史调用方
`from fastapi_app.services.material_registration_service import X` 保持不变。
"""
from fastapi_app.services.material_registration._commands import (  # noqa: F401
    create_registration,
    update_registration,
    delete_registration,
    receive_material,
)
from fastapi_app.services.material_registration._export import (  # noqa: F401
    _sanitize_xlsx_formula,
    export_registrations,
)
from fastapi_app.services.material_registration._queries import (  # noqa: F401
    _parse_filter_date,
    get_registrations,
    get_registration,
    _compute_pct,
    get_supplier_detail,
    get_available_purchase_orders,
    get_stats_overview,
    get_purchase_order_items,
    preview_purchase_order,
    get_history,
    get_suggestions,
    get_stats_distribution,
    get_stats_trend,
)
