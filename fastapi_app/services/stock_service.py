"""
库存管理业务逻辑服务（对外兼容入口）

本文件已按职责拆分为多个子模块：
- stock_in_service：入库（StockIn）业务逻辑
- stock_out_service：出库（StockOut）业务逻辑
- stock_return_service：退货（StockReturn）业务逻辑
- stock_inventory_service：库存查询 / 列表 / 统计（含 SQL 聚合辅助函数与 SQL 片段常量）
- stock_event_service：订单状态重算与事件发布
- stock_common：共享辅助工具（_parse_date_preserve_time）

本文件保留全部对外函数名的 re-export，历史调用方
`from fastapi_app.services.stock_service import X` 保持不变，可直接使用。

核心 CRUD 和库存计算已统一至 fastapi_app.shared.stock_crud_service。
本服务负责异步适配层：将同步 shared 函数包装为异步调用，
并处理事件发布等 FastAPI 特有逻辑。
"""
import logging

# ---------------------------------------------------------------------------
# 兼容层保留：以下名称在重构前即为本模块的模块级名称，测试通过
# `fastapi_app.services.stock_service.<name>` 打 patch 拦截内部调用，
# 因此保留在顶部以保证命名空间一致。
# ---------------------------------------------------------------------------
from fastapi_app.services.batch_service import calculate_available_shipment_quantity  # noqa: F401
from fastapi_app.services.notification_service import StockEvent, publish_stock_event  # noqa: F401
from fastapi_app.services.numbering import generate_stockin_number, generate_stockout_number  # noqa: F401
from fastapi_app.shared.stock_concurrency import get_product_for_update  # noqa: F401
from fastapi_app.utils import log_inventory_change  # noqa: F401

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 全部对外名称 re-export（保持历史 import 兼容）
# ---------------------------------------------------------------------------
from fastapi_app.services.stock_common import _parse_date_preserve_time  # noqa: E402, F401
from fastapi_app.services.stock_event_service import (  # noqa: E402, F401
    recalc_order_status_after_return,
    _recalc_shipment_order_statuses,
    _publish_shipment_completed_events,
)
from fastapi_app.services.stock_in_service import (  # noqa: E402, F401
    MAX_STOCK_QUANTITY,
    create_stockin_core,
    update_stockin_core,
    delete_stockin_core,
    create_stockin,
    update_stockin,
    delete_stockin,
    batch_create_stockins,
)
from fastapi_app.services.stock_inventory_service import (  # noqa: E402, F401
    get_stockins,
    get_stockouts,
    get_stockreturns,
    get_inventory,
    get_inventory_paginated,
    get_stock_overview_stats,
    _build_inventory_filter_params,
    _build_inventory_cte_sql,
    _format_inventory_rows,
    _empty_inventory_response,
    _parse_country_data,
    _get_all_countries,
    _get_all_customers,
    _resolve_products,
    _build_inventory_query_clauses,
    _build_country_data_dict,
    _merge_inventory_rows,
    _fetch_inventory,
    _run_sql,
    _get_prod_names,
    _CUST_CLAUSE,
    _SI_CUST,
    _SO_CUST,
    _O_CUST,
    _PID_CLAUSE,
    _SI_PID,
    _SO_PID,
    _O_PID,
    _PROD_PID,
)
from fastapi_app.services.stock_out_service import (  # noqa: E402, F401
    create_stockout_core,
    update_stockout_core,
    delete_stockout_core,
    create_stockout,
    update_stockout,
    delete_stockout,
    batch_create_stockouts,
    _validate_stockout_batch,
    _create_stockout_records,
    _process_single_stockout,
)
from fastapi_app.services.stock_return_service import (  # noqa: E402, F401
    generate_stockreturn_number,
    create_stockreturn_core,
    delete_stockreturn_core,
    create_stockreturn,
    delete_stockreturn,
)
