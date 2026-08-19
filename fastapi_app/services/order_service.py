"""
订单管理业务逻辑服务（Facade）

从原 order_service.py 拆分为 crud/batch_create 两个子模块。
本模块作为 Facade，re-export 所有公共函数，保持向后兼容：
    from fastapi_app.services.order_service import batch_create_orders
仍可正常工作。

事件发布逻辑保留在各业务函数内部（create_order/delete_order 等），
本 Facade 不额外注册事件订阅。
"""
import logging

from fastapi_app.services.order_batch_create import (
    _SavepointRollbackSignalError,
    batch_create_orders,
)
from fastapi_app.services.order_crud import (
    PermissionDeniedError,
    _check_order_lock,
    _create_approval_log_obj,
    _ensure_no_pending_request,
    _generate_order_number,
    _safe_invalidate_purchase_cache,
    _submit_delete_approval,
    _submit_edit_approval,
    _update_order_directly,
    cancel_approval,
    create_order,
    delete_order,
    get_my_approvals,
    get_order_by_id,
    get_orders,
    update_deduct_quantity,
    update_order,
)

# Facade 显式 re-export 清单：防止 ruff F401 误删兼容层导入
__all__ = [
    'PermissionDeniedError',
    '_SavepointRollbackSignalError',
    '_check_order_lock',
    '_create_approval_log_obj',
    '_ensure_no_pending_request',
    '_generate_order_number',
    '_safe_invalidate_purchase_cache',
    '_submit_delete_approval',
    '_submit_edit_approval',
    '_update_order_directly',
    'batch_create_orders',
    'cancel_approval',
    'create_order',
    'delete_order',
    'get_my_approvals',
    'get_order_by_id',
    'get_orders',
    'update_deduct_quantity',
    'update_order',
]

logger = logging.getLogger(__name__)
