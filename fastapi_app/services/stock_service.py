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

库存 CRUD 的异步实现位于 stock_*_service 子模块（本文件下方各 import）；
编号生成统一至 services/numbering（北京口径 + numbering_counter 单一水位源，仅异步）。
原 shared/stock_crud_service.py 的同步 CRUD 双轨已消除（死代码移除）。
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
from fastapi_app.services.stock_common import _parse_date_preserve_time  # noqa: F401
from fastapi_app.services.stock_event_service import (  # noqa: F401
    _publish_shipment_completed_events,
    _recalc_shipment_order_statuses,
    recalc_order_status_after_return,
)
from fastapi_app.services.stock_in_service import (  # noqa: F401
    MAX_STOCK_QUANTITY,
    batch_create_stockins,
    create_stockin,
    create_stockin_core,
    delete_stockin,
    delete_stockin_core,
    update_stockin,
    update_stockin_core,
)
from fastapi_app.services.stock_inventory_service import (  # noqa: F401
    _CUST_CLAUSE,
    _O_CUST,
    _O_PID,
    _PID_CLAUSE,
    _PROD_PID,
    _SI_CUST,
    _SI_PID,
    _SO_CUST,
    _SO_PID,
    _build_inventory_cte_sql,
    _build_inventory_filter_params,
    _empty_inventory_response,
    _format_inventory_rows,
    _get_all_customers,
    _resolve_products,
    get_inventory,
    get_inventory_balance,
    get_inventory_balance_detail,
    get_inventory_paginated,
    get_stock_overview_stats,
    get_stockins,
    get_stockouts,
    get_stockreturns,
)
from fastapi_app.services.stock_out_service import (  # noqa: F401
    _create_stockout_records,
    _process_single_stockout,
    _validate_stockout_batch,
    batch_create_stockouts,
    create_stockout,
    create_stockout_core,
    delete_stockout,
    delete_stockout_core,
    update_stockout,
    update_stockout_core,
)
from fastapi_app.services.stock_return_service import (  # noqa: F401
    cancel_stockreturn,
    cancel_stockreturn_core,
    create_stockreturn,
    create_stockreturn_core,
    generate_stockreturn_number,
)
