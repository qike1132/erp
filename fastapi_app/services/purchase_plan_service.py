"""
采购计划管理服务（Facade）

从原 purchase_plan_service.py 拆分为 crud/fifo 两个子模块。
本模块作为 Facade，re-export 所有公共函数，保持向后兼容：
    from fastapi_app.services.purchase_plan_service import recalc_plans_after_stockout_create
仍可正常工作。

领域事件订阅注册保留在此处，确保模块加载时自动注册。
"""
import logging

from fastapi_app.core.domain_events import DomainEventType, subscribe
from fastapi_app.services.fifo_allocation import (
    FIFO_CACHE_PREFIX,
    FIFO_CACHE_TTL,
    _aggregate_shipped_by_key,
    _fifo_query_with_timeout,
    _get_shipped_fifo_map,
    _invalidate_fifo_cache,
    allocate_fifo,
)
from fastapi_app.services.purchase_plan_crud import (
    INVENTORY_CACHE_PREFIX,
    INVENTORY_CACHE_TTL,
    SHIPMENT_RECORD_LOOKBACK_MONTHS,
    _calc_stock_status,
    _check_inventory_realtime,
    _compute_shipment_lookback_limit,
    _enrich_customer_icon_urls,
    _format_insufficient_error,
    _generate_plan_no,
    _get_inventory_map,
    _invalidate_plan_caches,
    _log_action,
    _persist_plan_with_retry,
    _recalc_plan_status,
    _recalc_plans_common,
    _validate_details_cross_month,
    _validate_plan_month,
    _validate_products_exist,
    add_details,
    clear_staging,
    confirm_staging,
    create_plan,
    delete_detail,
    delete_plan,
    get_customer_summary,
    get_inventory_compare,
    get_monthly_calendar,
    get_plan_detail,
    get_plan_list,
    get_shipment_progress,
    get_shipment_records,
    get_shipment_records_by_date,
    get_staging_list,
    recalc_plans_after_stockout_create,
    recalc_plans_after_stockout_delete,
    update_detail,
    update_plan,
    upload_excel,
    validate_barcode,
    validate_staging,
)

logger = logging.getLogger(__name__)


# ===== 领域事件订阅注册 =====
# 订阅 stock_service 发布的领域事件，异步执行采购计划重算与缓存失效，
# 解耦 stock_service ↔ purchase_plan_service 的循环依赖。
# 事件处理器使用独立的数据库会话（get_async_db_context），不阻塞 stockout 主流程。
def _make_stock_handler(event_name: str, *, need_recalc_create: bool=False, need_recalc_delete: bool=False):
    """S6 工厂函数：生成统一的库存领域事件处理器

    消除 5 个 _on_stock_* 处理器的重复样板代码（payload 提取 + DB context + 缓存失效）。

    Args:
        event_name: 事件名（用于日志标识），如 'STOCK_OUT_CREATED'
        need_recalc_create: True 时调用 recalc_plans_after_stockout_create（出货创建场景）
        need_recalc_delete: True 时调用 recalc_plans_after_stockout_delete（出货删除/退货场景）
    """
    async def handler(event):
        payload = event.payload or {}
        customer_name = payload.get('customer', '')
        product_name = payload.get('product_name', '')
        stockout_no = payload.get('stockout_no', '')
        deleted_quantity = payload.get('deleted_quantity', 0)
        plan_month = payload.get('plan_month', '')

        # 仅缓存失效场景（STOCK_OUT_UPDATED）：不需要 customer_name/product_name
        if not need_recalc_create and not need_recalc_delete:
            if not plan_month:
                return
            try:
                await _invalidate_plan_caches(plan_month)
            except Exception as e:  # defensive: 单个事件处理失败不影响其他事件
                logger.error(
                    '%s 处理失败: plan_month=%s error=%s',
                    event_name, plan_month, e, exc_info=True,
                )
            return

        # 重算场景：需要 customer_name + product_name
        if not customer_name or not product_name:
            return
        try:
            # lazy import 避免模块加载时与 core.database 形成循环依赖
            from fastapi_app.core.database import get_async_db_context
            async with get_async_db_context() as db:
                if need_recalc_create:
                    await recalc_plans_after_stockout_create(db, customer_name, product_name)
                elif need_recalc_delete:
                    await recalc_plans_after_stockout_delete(
                        db, customer_name, product_name, stockout_no, deleted_quantity,
                    )
            if plan_month:
                await _invalidate_plan_caches(plan_month)
        except Exception as e:  # defensive: 单个事件处理失败不影响其他事件
            logger.error(
                '%s 处理失败: customer=%s product=%s error=%s',
                event_name, customer_name, product_name, e, exc_info=True,
            )
    return handler


def _register_stock_event_subscriptions():
    """注册库存领域事件订阅：出库/退货变更 → 采购计划重算 + 缓存失效"""
    try:
        subscribe(DomainEventType.STOCK_OUT_CREATED, _make_stock_handler(
            'STOCK_OUT_CREATED', need_recalc_create=True,
        ))
        subscribe(DomainEventType.STOCK_OUT_UPDATED, _make_stock_handler(
            'STOCK_OUT_UPDATED',  # 仅缓存失效
        ))
        subscribe(DomainEventType.STOCK_OUT_DELETED, _make_stock_handler(
            'STOCK_OUT_DELETED', need_recalc_delete=True,
        ))
        subscribe(DomainEventType.STOCK_RETURN_CREATED, _make_stock_handler(
            'STOCK_RETURN_CREATED', need_recalc_delete=True,
        ))
        subscribe(DomainEventType.STOCK_RETURN_DELETED, _make_stock_handler(
            'STOCK_RETURN_DELETED', need_recalc_delete=True,
        ))
        logger.info(
            '采购计划领域事件订阅已注册: STOCK_OUT_CREATED, STOCK_OUT_UPDATED, '
            'STOCK_OUT_DELETED, STOCK_RETURN_CREATED, STOCK_RETURN_DELETED'
        )
    except Exception as e:  # defensive: 订阅注册失败不影响模块加载
        logger.warning('采购计划领域事件订阅注册失败（可忽略）: %s', e)


# 模块加载时注册订阅
_register_stock_event_subscriptions()
