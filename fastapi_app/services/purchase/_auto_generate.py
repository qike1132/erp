"""采购订单自动生成：事务提交后**就地**生成（不依赖 ARQ worker）。

采购中心原先靠人工在「待审核订单」tab 勾选后点「一键审核订单」生成采购单 —— 那条路径
是**在 HTTP 请求内同步**调用 ``generate_purchase_orders_from_customer_orders``，不经过任何
后台队列。本模块把这步自动化，但保持同一形态：

- 订单/备货创建（以及 BOM 保存）的事务**提交成功后**，由 post-commit 回调**当场**跑一次
  自动生成（开独立会话，复用同一个生成函数）。
- 不用 ARQ：worker 不跑时（如 GUI 开发栈托管）任务会静默滞留，用户看到「生成中…」永不
  推进。就地执行没有这个失效模式。
- 失败只记日志，绝不影响创建/保存本身（下单成功即成功；生成失败下次创建或保存会再触发）。

生成逻辑本身复用 ``generate_purchase_orders_from_customer_orders``，一行不改。
"""
import logging
from functools import partial

logger = logging.getLogger(__name__)

#: 采购相关缓存前缀（与一键审核端点同口径）：采购列表 / 湖北订单 / 未处理列表。
_PURCHASE_CACHE_PATTERNS = ('orders:p*', 'orders:beile:*', 'orders:unprocessed:*')


async def invalidate_purchase_caches() -> None:
    """失效采购相关缓存（生成/撤销采购单后都要调，避免页面读到旧列表）。"""
    from fastapi_app.core.cache import invalidate_cache
    for pattern in _PURCHASE_CACHE_PATTERNS:
        try:
            await invalidate_cache(pattern)
        except (OSError, ValueError):
            logger.warning('缓存失效失败(auto_generate): %s', pattern, exc_info=True)


async def _run_auto_generate() -> None:
    """就地跑一次自动生成（best-effort：失败只记日志，不影响调用方主流程）。"""
    try:
        # 全部函数级导入：本模块被 services/order、stock_in、staging、batch_import 引用，
        # 模块级导入 core.* / services.* 会形成循环。
        from fastapi_app.core.database import require_async_session_local
        from fastapi_app.core.exceptions import db_transaction
        from fastapi_app.services.notification_service import StockEvent, publish_event
        from fastapi_app.services.purchase_order_generate import auto_generate_purchase_orders

        session_factory = require_async_session_local()
        async with session_factory() as db:
            async with db_transaction(db):
                result = await auto_generate_purchase_orders(db)

        await invalidate_purchase_caches()

        generated_count = int(result.get('generated_count') or 0)
        if generated_count:
            logger.info(
                '采购订单自动生成: 客户数=%d 采购单数=%d',
                result.get('customer_count', 0), generated_count,
            )
            # 推送实时事件：采购页（待生产）据此立即刷新，做到「下单即出现」
            try:
                await publish_event(StockEvent.PURCHASE_ORDER_CREATED, {'count': generated_count})
            except Exception:  # broad-except: 广播失败不影响生成结果
                logger.warning('采购订单生成事件广播失败', exc_info=True)
    except Exception:  # broad-except: 自动生成失败不得影响订单/备货创建主流程
        logger.warning('采购订单自动生成失败（不影响本次下单/保存）', exc_info=True)


def schedule_auto_generate_purchase_orders(session) -> None:
    """注册「事务提交成功后」就地执行的采购订单自动生成。

    与 ``core.domain_events.schedule_post_commit_domain_event`` 同款：回调挂到
    ``session.info['post_commit_callbacks']``，由 ``db_transaction`` / ``get_async_db``
    在提交成功后执行（回调失败隔离，只记日志，不影响主流程）。

    订单/备货创建、BOM 保存等路径各调用**一次**（每次操作一次）即可；同一事务内重复
    调用按回调列表去重为一次——**切勿**在逐行循环内调用。

    去重依赖「回调列表在提交后即被清空」（``run_post_commit_callbacks`` pop）这一事实，
    因此**按事务**去重；不要改用 ``session.info`` 上的持久标记——``info`` 的生命周期是
    **整个会话**而非单个事务，同一会话跨多个事务写单时会被永久屏蔽、后续事务再不触发。
    """
    info = getattr(session, 'info', None)
    if not isinstance(info, dict):
        return
    callbacks = info.setdefault('post_commit_callbacks', [])
    if _run_auto_generate not in callbacks:
        callbacks.append(_run_auto_generate)


async def _run_bom_saved(product_id: int) -> None:
    """BOM 保存提交后：若该产品 BOM 已删空 → 撤销其 pending 采购单；随后跑一次自动生成。

    撤销会把受影响订单状态重算回「待备货」，再由自动生成重新扫描——BOM 若已补回就会
    重新生成，删空则停在「待生成（未配置BOM）」。
    """
    try:
        from fastapi_app.core.database import require_async_session_local
        from fastapi_app.core.exceptions import db_transaction
        from fastapi_app.services.purchase_order_revoke import (
            revoke_pending_purchase_orders_for_product,
        )

        session_factory = require_async_session_local()
        async with session_factory() as db:
            async with db_transaction(db):
                await revoke_pending_purchase_orders_for_product(db, product_id)
    except Exception:  # broad-except: 撤销失败不得影响 BOM 保存本身
        logger.warning('删空 BOM 后撤销采购单失败（不影响本次保存）', exc_info=True)

    await _run_auto_generate()


def schedule_bom_saved_side_effects(session, product_id: int) -> None:
    """注册「BOM 保存提交成功后」的副作用：先撤销（若删空），再自动生成。

    与其它 ``schedule_*`` 同款：回调挂到 ``session.info['post_commit_callbacks']``，
    由 ``db_transaction`` 在提交成功后执行。BOM 保存端点每次请求调用一次即可。
    """
    info = getattr(session, 'info', None)
    if not isinstance(info, dict):
        return
    info.setdefault('post_commit_callbacks', []).append(partial(_run_bom_saved, product_id))
