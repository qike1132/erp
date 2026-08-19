"""
采购中心服务层 - 业务逻辑（子模块重导出 facade）

原始 1922 行 God File 已拆分为以下子模块：
- purchase_product_service: 产品/BOM API + 物料计算
- purchase_supplier_service: 供应商 CRUD + 信息同步
- purchase_history_service: 修改历史/保存查询/状态日志
- purchase_bom_copy_service: BOM 复制功能
- purchase_customer_service: 客户管理 API
- purchase_order_crud/query/generate: 采购订单 CRUD + 汇总（原 purchase_order_service 已扁平化）

此文件保留所有原始导入路径的向后兼容，endpoint 层通过
`from fastapi_app.services import purchase_center_service as svc` 访问。

领域事件订阅注册保留在此处，确保模块加载时自动注册。
"""
import logging

from fastapi_app.core.domain_events import DomainEventType, subscribe
from fastapi_app.services.purchase_bom_copy_service import (  # noqa: F401
    batch_delete_purchase_orders,
    copy_bom_to_product,
    get_bom_preview,
    search_products_for_bom_copy,
)
from fastapi_app.services.purchase_customer_service import (  # noqa: F401
    batch_get_customers,
    get_customer_detail,
    get_customers,
    get_customers_statistics,
)
from fastapi_app.services.purchase_history_service import (  # noqa: F401
    delete_saved_query,
    get_modification_logs,
    get_saved_queries,
    get_status_logs,
    save_query,
    use_saved_query,
)

# 直接从 crud/query/generate 三个子模块导入，移除 purchase_order_service 中间层
from fastapi_app.services.purchase_order_crud import (  # noqa: F401
    _build_order_summary,
    batch_complete_purchase_orders,
    cleanup_orphan_pending_purchase_orders,
    complete_purchase_order,
    create_purchase_order,
    delete_purchase_order,
    save_factory_summary_edits,
    update_purchase_order,
)
from fastapi_app.services.purchase_order_generate import (  # noqa: F401
    fetch_existing_pending_for_composite_ids,
    generate_purchase_orders_from_customer_orders,
    one_click_generate_order,
)
from fastapi_app.services.purchase_order_query import (  # noqa: F401
    _fetch_bom_data,
    _parse_source_order_ids,
    export_completed_orders,
    get_completed_order_quick_filters,
    get_completed_order_suggestions,
    get_completed_purchase_orders,
    get_factory_order_summary,
    get_purchase_order,
    get_purchase_orders,
    get_supplier_order_summary,
    get_unprocessed_orders,
    query_supplier_groups,
)
from fastapi_app.services.purchase_product_service import (  # noqa: F401
    calculate_material,
    get_product_bom,
    get_products,
    get_products_batch_bom,
    get_products_statistics,
    get_search_suggestions,
    product_has_bom,
    save_product_bom,
)
from fastapi_app.services.purchase_supplier_service import (  # noqa: F401
    create_supplier,
    delete_supplier,
    get_suppliers,
    update_supplier,
)

logger = logging.getLogger(__name__)


# ===== 领域事件订阅注册 =====
# 订阅 order_service/approval_service 发布的 ORDER_DELETED 事件，
# 异步清理关联的 pending 采购订单，解耦 order ↔ purchase_order 的循环依赖。
# 事件处理器使用独立的数据库会话（get_async_db_context），不阻塞订单删除主流程。
def _register_order_event_subscriptions():
    """注册订单领域事件订阅：订单删除 → 清理关联 pending 采购订单"""
    try:
        from fastapi_app.core.database import get_async_db_context

        async def _on_order_deleted(event):
            """订单删除 → 清理关联的 pending 采购订单"""
            payload = event.payload or {}
            order_id = payload.get('order_id')
            if not order_id:
                return
            try:
                async with get_async_db_context() as db:
                    await cleanup_orphan_pending_purchase_orders(db, [order_id])
            except Exception as e:  # defensive: 单个事件处理失败不影响其他事件
                logger.error(
                    'ORDER_DELETED 处理失败: order_id=%s error=%s',
                    order_id, e, exc_info=True,
                )

        subscribe(DomainEventType.ORDER_DELETED, _on_order_deleted)
        logger.info('采购订单领域事件订阅已注册: ORDER_DELETED')
    except Exception as e:  # defensive: 订阅注册失败不影响模块加载
        logger.warning('采购订单领域事件订阅注册失败（可忽略）: %s', e)


# 模块加载时注册订阅
_register_order_event_subscriptions()


# ==================== 查询函数（自 purchase_center 路由下沉，纯查询搬移） ====================
from sqlalchemy import select as _select
from sqlalchemy.ext.asyncio import AsyncSession as _AsyncSession
from sqlalchemy.orm import selectinload as _selectinload

from fastapi_app.shared_models import Order as _SysOrder
from fastapi_app.shared_models import PurchaseOrder as _PurchaseOrder
from fastapi_app.shared_models import PurchaseOrderItem as _PurchaseOrderItem


async def get_purchase_orders_with_items(db: _AsyncSession, ids: list[int]) -> list[_PurchaseOrder]:
    """按 ID 列表获取采购订单（预加载明细项）"""
    result = await db.execute(
        _select(_PurchaseOrder).where(_PurchaseOrder.id.in_(ids)).options(_selectinload(_PurchaseOrder.items))
    )
    return list(result.scalars().unique().all())


async def get_purchase_orders_by_source_ids(db: _AsyncSession, source_order_ids: list[int]) -> list[_PurchaseOrder]:
    """按系统订单来源 ID 列表获取关联采购订单（预加载明细项）"""
    result = await db.execute(
        _select(_PurchaseOrder).where(
            _PurchaseOrder.source_order_id.in_(source_order_ids)
        ).options(_selectinload(_PurchaseOrder.items))
    )
    return list(result.scalars().unique().all())


async def get_purchase_order_items_by_order_ids(db: _AsyncSession, order_ids: list[int]) -> list[_PurchaseOrderItem]:
    """按采购订单 ID 列表获取全部明细项"""
    result = await db.execute(
        _select(_PurchaseOrderItem).where(_PurchaseOrderItem.order_id.in_(order_ids))
    )
    return list(result.scalars().all())


async def get_system_orders_by_ids(db: _AsyncSession, source_order_ids: list[int]) -> list[_SysOrder]:
    """按 ID 列表获取系统订单（用于打印关联来源订单信息）"""
    result = await db.execute(
        _select(_SysOrder).where(_SysOrder.id.in_(source_order_ids))
    )
    return list(result.scalars().all())
