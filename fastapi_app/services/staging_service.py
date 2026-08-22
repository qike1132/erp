"""暂存区管理服务层(对外兼容入口)

从 staging_service.py 按实体拆分为 services/staging/ 子包:
- _generic: 通用导入/更新骨架与辅助
- order: 暂存订单实体  - stockin: 暂存备货实体  - stockout: 暂存出货实体

本文件保留全部对外函数名的 re-export,历史调用方
`from fastapi_app.services.staging_service import X` 保持不变。
"""
from fastapi_app.services.staging._generic import (  # noqa: F401
    _find_product_by_name_or_barcode,
    _cached_product_id_map,
    _build_product_map,
    _validate_and_map_product,
    _format_import_result,
    _parse_deduct_flag,
    _generic_import_staging_from_excel,
    _generic_update_staging_entity,
)
from fastapi_app.services.staging.order import (  # noqa: F401
    _build_order_entity,
    _order_extra_updates,
    get_staging_orders,
    clear_staging_orders_by_session,
    clear_staging_orders,
    delete_staging_order,
    update_staging_order,
    confirm_staging_orders,
    import_staging_orders_from_excel,
)
from fastapi_app.services.staging.stockin import (  # noqa: F401
    _build_stockin_entity,
    _validate_stockin_customer,
    _stockin_extra_updates,
    get_staging_stockins,
    clear_staging_stockins_by_session,
    clear_staging_stockins,
    delete_staging_stockin,
    update_staging_stockin,
    confirm_staging_stockins,
    import_staging_stockins_from_excel,
)
from fastapi_app.services.staging.stockout import (  # noqa: F401
    _build_stockout_entity,
    _stockout_extra_updates,
    get_staging_stockouts,
    clear_staging_stockouts_by_session,
    clear_staging_stockouts,
    delete_staging_stockout,
    update_staging_stockout,
    confirm_staging_stockouts,
    import_staging_stockouts_from_excel,
    import_staging_stockouts_from_file,
)
