"""
采购计划 CRUD 与业务操作（Facade / re-export 中心）

原"上帝类"文件已按职责拆分为以下子模块，本模块保留对外接口，re-export
全部函数与常量，保证如下导入方式继续兼容：
    from fastapi_app.services.purchase_plan_crud import X

子模块：
    - purchase_plan_common.py    基础辅助：事务提交回调、缓存失效、编号生成、操作日志
    - purchase_plan_inventory.py 库存映射 + 实时库存校验
    - purchase_plan_crud_ops.py  主单/明细 CRUD 与数据校验
    - purchase_plan_queries.py   列表/详情/进度/流水/日历/汇总/库存对比等查询
    - purchase_plan_staging.py   暂存区管理与 Excel 导入
    - purchase_plan_shipment.py  出货重算与 FIFO 读路径封装

FIFO 分配算法已拆分至 fifo_allocation.py。
从 purchase_plan_service.py 拆分而来，保持函数签名不变。
"""
# ruff: noqa: F401  (本文件为 re-export 兼容层，导入名称供外部调用方使用)
import logging

from fastapi_app.services.purchase_plan_common import (
    _generate_plan_no,
    _invalidate_plan_caches,
    _log_action,
    _schedule_post_commit,
)
from fastapi_app.services.purchase_plan_crud_ops import (
    PlanExistsError,
    _format_insufficient_error,
    _persist_plan_with_retry,
    _validate_details_cross_month,
    _validate_plan_month,
    _validate_products_exist,
    add_details,
    create_plan,
    delete_detail,
    delete_plan,
    update_detail,
    update_plan,
)
from fastapi_app.services.purchase_plan_inventory import (
    INVENTORY_CACHE_PREFIX,
    INVENTORY_CACHE_TTL,
    _aggregate_barcode_demand,
    _aggregate_name_demand,
    _check_inventory_realtime,
    _collect_insufficient,
    _fetch_barcode_stock,
    _fetch_name_stock,
    _get_inventory_map,
)
from fastapi_app.services.purchase_plan_queries import (
    SHIPMENT_RECORD_LOOKBACK_MONTHS,
    _calc_stock_status,
    _compute_shipment_lookback_limit,
    _enrich_customer_icon_urls,
    get_customer_summary,
    get_day_details,
    get_inventory_compare,
    get_monthly_aggregated,
    get_monthly_calendar,
    get_plan_detail,
    get_plan_list,
    get_shipment_progress,
    get_shipment_records,
    get_shipment_records_by_date,
)
from fastapi_app.services.purchase_plan_shipment import (
    _build_recalc_log_values,
    _fetch_affected_plans_and_details,
    _get_shipped_fifo_map_safe,
    _recalc_plan_status,
    _recalc_plan_statuses,
    _recalc_plans_common,
    _update_shipped_qty,
    recalc_plans_after_stockout_create,
    recalc_plans_after_stockout_delete,
)
from fastapi_app.services.purchase_plan_staging import (
    _create_details_for_group,
    _get_or_create_plan_for_group,
    _group_staging_records,
    _load_excel_rows,
    _parse_excel_row,
    _validate_excel_row,
    clear_staging,
    confirm_staging,
    get_staging_list,
    upload_excel,
    validate_barcode,
    validate_staging,
)

# 保留本模块级 logger 定义（与子模块共享同一实例），供外部按原方式引用
logger = logging.getLogger(__name__)
