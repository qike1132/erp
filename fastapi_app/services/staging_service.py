"""暂存区管理服务层(对外兼容入口)

从 staging_service.py 按实体拆分为 services/staging/ 子包:
- _generic: 通用导入/更新骨架与辅助
- order: 暂存订单实体  - stockin: 暂存备货实体  - stockout: 暂存出货实体

本文件保留全部对外函数名的 re-export,历史调用方
`from fastapi_app.services.staging_service import X` 保持不变。
"""
from fastapi_app.services.staging._generic import (  # noqa: F401
    _build_product_map,
    _cached_product_id_map,
    _find_product_by_name_or_barcode,
    _format_import_result,
    _generic_import_staging_from_excel,
    _generic_update_staging_entity,
    _parse_deduct_flag,
    _validate_and_map_product,
)
from fastapi_app.services.staging.order import (  # noqa: F401
    _build_order_entity,
    _order_extra_updates,
    clear_staging_orders,
    clear_staging_orders_by_session,
    confirm_staging_orders,
    delete_staging_order,
    get_staging_orders,
    import_staging_orders_from_excel,
    update_staging_order,
)
from fastapi_app.services.staging.stockin import (  # noqa: F401
    _build_stockin_entity,
    _stockin_extra_updates,
    _validate_stockin_customer,
    clear_staging_stockins,
    clear_staging_stockins_by_session,
    confirm_staging_stockins,
    delete_staging_stockin,
    get_staging_stockins,
    import_staging_stockins_from_excel,
    update_staging_stockin,
)
from fastapi_app.services.staging.stockout import (  # noqa: F401
    _build_stockout_entity,
    _stockout_extra_updates,
    clear_staging_stockouts,
    clear_staging_stockouts_by_session,
    confirm_staging_stockouts,
    delete_staging_stockout,
    get_staging_stockouts,
    import_staging_stockouts_from_excel,
    import_staging_stockouts_from_file,
    update_staging_stockout,
)
