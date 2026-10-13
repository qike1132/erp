"""订单 CRUD Facade（批次1-3 拆分，2026-08-22）

按职责拆分至 services/order/ 子包：queries / commands / deduction / approval_flow。
本模块保留全部原名称 re-export（含 beile 转发），既有 52 处引用零改动；
新增代码请直接 import 对应子模块。
"""
# ruff: noqa: F401 - 兼容 Facade re-export
import logging

from fastapi_app.services.order._common import (  # 兼容：调用方曾经 order_crud 隐式再导出
    PermissionDeniedError,
    _safe_invalidate_purchase_cache,
)
from fastapi_app.services.order.approval_flow import (
    _check_order_lock,
    _create_approval_log_obj,
    _ensure_no_pending_request,
    _submit_delete_approval,
    _submit_edit_approval,
    cancel_approval,
)
from fastapi_app.services.order.beile import (
    _build_beile_order_record,
    _build_beile_stockin_record,
    _build_beile_unified_query,
    _fetch_beile_records_by_ids,
    confirm_beile_order,
    confirm_beile_stockin,
    get_beile_orders_with_stockins,
    get_beile_unconfirmed_count,
)
from fastapi_app.services.order.commands import (
    _delete_order_directly,
    _update_order_directly,
    create_order,
    delete_order,
    delete_order_item,
    update_order,
    update_order_item,
)
from fastapi_app.services.order.deduction import (
    _decrease_deduction,
    _increase_deduction,
    update_deduct_quantity,
)
from fastapi_app.services.order.queries import (
    _build_order_filters,
    _fetch_orders_page,
    _parse_date_condition,
    _serialize_orders,
    get_my_approvals,
    get_order_by_id,
    get_orders,
)

logger = logging.getLogger(__name__)
