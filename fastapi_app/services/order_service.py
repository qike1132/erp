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
    _safe_invalidate_purchase_cache,
    _update_order_directly,
    create_order,
    delete_order,
    delete_order_item,
    get_order_by_id,
    get_orders,
    update_deduct_quantity,
    update_order,
    update_order_item,
)

# Facade 显式 re-export 清单：防止 ruff F401 误删兼容层导入
__all__ = [
    'PermissionDeniedError',
    '_SavepointRollbackSignalError',
    '_safe_invalidate_purchase_cache',
    '_update_order_directly',
    'batch_create_orders',
    'create_order',
    'delete_order',
    'delete_order_item',
    'get_order_by_id',
    'get_orders',
    'update_deduct_quantity',
    'update_order',
    'update_order_item',
]

logger = logging.getLogger(__name__)
