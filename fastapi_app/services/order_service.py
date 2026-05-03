"""
订单管理业务逻辑服务

从 Flask order.py 提取的核心业务逻辑，适配异步 SQLAlchemy。
"""
import asyncio
import json
import logging
from datetime import UTC, datetime

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload, selectinload

from fastapi_app.core.cache import CacheDomain, cache_result, invalidate_related_caches
from fastapi_app.core.state_machine import can_transition
from fastapi_app.services import escape_like
from fastapi_app.shared.stock_concurrency import get_product_for_update
from fastapi_app.shared_models import (
    ApprovalLog,
    ApprovalRequest,
    InventoryLog,
    Order,
    OrderSyncRecord,
    StockOut,
    User,
)

logger = logging.getLogger(__name__)


class PermissionDeniedError(Exception):
    """用户无权限执行此操作"""
    pass


async def get_order_by_id(db: AsyncSession, order_id: int) -> dict | None:
    """根据ID获取单个订单详情（含关联数据）"""
    from sqlalchemy.orm import selectinload

    from fastapi_app.shared_models import Order

    query = select(Order).options(
        joinedload(Order.product),
        selectinload(Order.order_stockouts),
        joinedload(Order.locked_by)
    ).where(Order.id == order_id, not Order.is_deleted)

    result = await db.execute(query)
    o = result.scalars().unique().first()
    if not o:
        return None

    deduct_quantity = sum(so.quantity for so in o.order_stockouts if so.stockin_id is not None) if o.order_stockouts else 0
    return {
        'id': o.id,
        'order_no': o.order_no,
        'customer': o.customer,
        'order_date': o.order_date.strftime('%Y-%m-%d %H:%M') if o.order_date else '',
        'product': {
            'id': o.product.id,
            'name': o.product.name,
            'barcode': o.product.barcode or '',
            'image': o.product.image or ''
        } if o.product else None,
        'quantity': o.quantity,
        'deduct_quantity': deduct_quantity,
        'status': o.status,
        'note': o.note or '',
        'order_type': o.order_type,
        'country': o.country or '',
        'is_locked': o.is_locked,
        'locked_by_name': o.locked_by.username if o.locked_by else None,
    }


@cache_result(
    key_prefix="orders:list",
    ttl=60,
    local_ttl=15,
    key_builder=lambda *args, **kwargs: f"p{kwargs.get('page', 1)}:pp{kwargs.get('per_page', 50)}:c{kwargs.get('customer', '')}:pid{kwargs.get('product_id', '')}:s{kwargs.get('status', '')}:ot{kwargs.get('order_type', '')}",
)
async def get_orders(db: AsyncSession, page: int = 1, per_page: int = 50,
                     customer: str | None = None, product_id: int | None = None,
                     status: str | None = None, order_type: str | None = None) -> dict:
    """获取订单列表（含关联数据，支持分页和筛选）"""
    # 基础查询
    query = select(Order).options(
        joinedload(Order.product),
        selectinload(Order.order_stockouts),
        joinedload(Order.locked_by)
    ).where(not Order.is_deleted)
    count_query = select(func.count(Order.id)).where(not Order.is_deleted)

    # 筛选条件（共用，避免 DRY 违反）
    conditions = []
    if customer:
        conditions.append(Order.customer.like(f'%{escape_like(customer)}%'))
    if product_id:
        conditions.append(Order.product_id == product_id)
    if status:
        conditions.append(Order.status == status)
    if order_type:
        conditions.append(Order.order_type == order_type)
    for c in conditions:
        query = query.where(c)
        count_query = count_query.where(c)

    # 总数
    total = (await db.execute(count_query)).scalar() or 0

    # 分页查询
    result = await db.execute(
        query.order_by(Order.order_date.desc())
        .offset((page - 1) * per_page)
        .limit(per_page)
    )
    orders = result.scalars().unique().all()

    orders_data = []
    for o in orders:
        deduct_quantity = sum(so.quantity for so in o.order_stockouts if so.stockin_id is not None) if o.order_stockouts else 0
        orders_data.append({
            'id': o.id,
            'order_no': o.order_no,
            'customer': o.customer,
            'order_date': o.order_date.strftime('%Y-%m-%d %H:%M') if o.order_date else '',
            'product': {
                'id': o.product.id,
                'name': o.product.name,
                'barcode': o.product.barcode or '',
                'image': o.product.image or ''
            } if o.product else None,
            'quantity': o.quantity,
            'deduct_quantity': deduct_quantity,
            'status': o.status,
            'note': o.note or '',
            'order_type': o.order_type,
            'country': o.country or '',
            'is_locked': o.is_locked,
            'locked_by_name': o.locked_by.username if o.locked_by else None,
        })
    return {'items': orders_data, 'total': total, 'page': page, 'per_page': per_page}


async def create_order(db: AsyncSession, product_id: int, quantity: int,
                       customer: str, note: str, current_user: User,
                       order_type: str = 'regular', country: str | None = None) -> dict:
    """
    创建订单

    业务规则（与Flask一致）：
    - 产品必须存在
    - 数量 > 0 且 <= 9999999
    - 客户名称不能为空
    - 创建后增加产品库存
    - 定制订单必须填写国家名称
    """
    if order_type == 'custom' and not country:
        raise ValueError('定制订单必须填写国家名称')

    if quantity <= 0 or quantity > 9999999:
        raise ValueError('订单数量必须在1-9999999之间')

    product = await get_product_for_update(db, product_id)

    order_no = await _generate_order_number(db)

    order = Order(
        order_no=order_no,
        customer=customer,
        order_date=datetime.now(UTC).replace(tzinfo=None),
        product_id=product_id,
        quantity=quantity,
        note=note,
        status='待备货',
        order_type=order_type,
        country=country if order_type == 'custom' else None,
    )
    db.add(order)
    await db.flush()

    product.current_stock += quantity

    log = InventoryLog(
        product_id=product_id,
        change_type='订单',
        change_quantity=quantity,
        related_id=order_no,
        customer=customer,
        note=f'订单：{order_no}'
    )
    db.add(log)

    await db.commit()
    await db.refresh(order)
    await invalidate_related_caches(CacheDomain.ORDER_AND_INVENTORY)
    logger.info(f'订单添加成功：{order_no}，客户：{customer}，产品：{product.name}，数量：{quantity}')

    # 不再自动同步采购中心：订单应先进入"审核订单"队列，由人工审核后再生成采购订单
    # 旧逻辑：await _sync_order_to_purchase_center(order.id)
    # 这会导致有 BOM 的订单直接跳过审核步骤，自动生成采购订单

    # 新订单创建后，立即清除采购中心缓存（在发布事件之前，确保前端刷新时缓存已失效）
    try:
        from fastapi_app.core.purchase_cache import invalidate_purchase_caches
        await invalidate_purchase_caches()
    except Exception:
        logger.warning("采购中心缓存失效失败", exc_info=True)

    # 发布订单创建事件，通知前端实时刷新
    try:
        from fastapi_app.services.notification_service import StockEvent, publish_stock_event
        await publish_stock_event(StockEvent.ORDER_CREATED, {
            'order_id': order.id,
            'order_no': order_no,
            'customer': customer,
            'product_name': product.name,
            'quantity': quantity,
        })
    except Exception:
        logger.warning("订单创建事件发布失败", exc_info=True)

    return order.to_dict()


async def update_order(db: AsyncSession, order_id: int, quantity: int,
                       customer: str, note: str, current_user: User,
                       order_type: str | None = None, country: str | None = None) -> dict:
    order = await db.get(Order, order_id)
    if not order or order.is_deleted:
        raise ValueError('订单不存在')

    await _check_order_lock(db, order_id, order, current_user, '编辑')

    if current_user.is_super:
        return await _update_order_directly(
            db, order, order_id, quantity, customer, note,
            current_user, order_type, country
        )
    else:
        return await _submit_edit_approval(
            db, order, order_id, quantity, customer, note, current_user
        )


async def _update_order_directly(
    db: AsyncSession, order: Order, order_id: int,
    quantity: int, customer: str, note: str,
    current_user: User, order_type: str | None,
    country: str | None,
) -> dict:
    old_quantity = order.quantity
    old_customer = order.customer
    order.customer = customer
    order.quantity = quantity
    order.note = note
    if order_type is not None:
        order.order_type = order_type
    if country is not None:
        order.country = country if order_type != 'regular' else None
    elif order.order_type == 'custom' and not order.country and not country:
        pass

    if quantity != old_quantity:
        product = await get_product_for_update(db, order.product_id)
        product.current_stock += (quantity - old_quantity)
        log = InventoryLog(
            product_id=order.product_id,
            change_type='订单修改',
            change_quantity=quantity - old_quantity,
            related_id=order.order_no,
            note=f'订单修改：{order.order_no}'
        )
        db.add(log)

    try:
        from fastapi_app.services.order_purchase_sync import sync_order_update
        sync_result = await sync_order_update(
            db, order_id,
            customer=customer, old_customer=old_customer,
            quantity=quantity, old_quantity=old_quantity,
        )
        if sync_result:
            logger.info(f'采购中心同步更新：{sync_result}')
    except (ValueError, OSError) as e:
        logger.warning(f'采购中心同步更新失败：{e}')

    await db.commit()
    await invalidate_related_caches(CacheDomain.ORDER_AND_INVENTORY)

    try:
        from fastapi_app.core.purchase_cache import invalidate_purchase_caches
        await invalidate_purchase_caches()
    except Exception:
        logger.warning("采购中心缓存失效失败(update)", exc_info=True)

    logger.info(f'订单编辑成功：{order.order_no}，操作人：{current_user.username}')

    try:
        from fastapi_app.services.notification_service import StockEvent, publish_stock_event
        await publish_stock_event(StockEvent.ORDER_UPDATED, {
            'order_id': order_id,
            'order_no': order.order_no,
            'customer': customer,
            'quantity': quantity,
        })
    except Exception:
        logger.warning("订单更新事件发布失败", exc_info=True)

    return {'success': True, 'message': '订单编辑成功！', 'requires_approval': False}


async def _submit_edit_approval(
    db: AsyncSession, order: Order, order_id: int,
    quantity: int, customer: str, note: str, current_user: User,
) -> dict:
    await _ensure_no_pending_request(db, order_id, current_user, '编辑')

    order.is_locked = True
    order.locked_by_id = current_user.id
    order.lock_time = datetime.now(UTC).replace(tzinfo=None)

    operation_data = {
        'customer': customer,
        'quantity': quantity,
        'note': note,
        'original_customer': order.customer,
        'original_quantity': order.quantity,
        'original_note': order.note or ''
    }

    approval_request = ApprovalRequest(
        order_id=order_id,
        requester_id=current_user.id,
        operation_type=ApprovalRequest.OPERATION_EDIT,
        operation_data=json.dumps(operation_data, ensure_ascii=False),
        status=ApprovalRequest.STATUS_PENDING,
        lock_time=datetime.now(UTC).replace(tzinfo=None)
    )
    db.add(approval_request)
    await db.flush()

    await _create_approval_log_obj(approval_request, ApprovalLog.ACTION_CREATE, current_user, {'operation_data': operation_data})

    await db.commit()
    await invalidate_related_caches(CacheDomain.ORDER_AND_INVENTORY)
    logger.info(f'订单编辑审批请求已提交：{order.order_no}，申请人：{current_user.username}')
    return {'success': True, 'message': '已提交编辑审批请求，请等待管理员审批！', 'requires_approval': True}


async def delete_order(db: AsyncSession, order_id: int, current_user: User) -> dict:
    order = await db.get(Order, order_id, options=[joinedload(Order.product)])
    if not order or order.is_deleted:
        raise ValueError('订单不存在')

    await _check_order_lock(db, order_id, order, current_user, '删除')

    if current_user.is_super:
        return await _delete_order_directly(db, order, order_id, current_user)
    else:
        return await _submit_delete_approval(db, order, order_id, current_user)


async def _delete_order_directly(
    db: AsyncSession, order: Order, order_id: int, current_user: User,
) -> dict:
    product = await get_product_for_update(db, order.product_id)

    result = await db.execute(
        select(StockOut).where(StockOut.order_id == order.id)
    )
    order_stockouts = result.scalars().all()
    total_deducted = sum(so.quantity for so in order_stockouts)

    for stockout in order_stockouts:
        stockout_log = InventoryLog(
            product_id=order.product_id,
            change_type='抵扣回滚',
            change_quantity=stockout.quantity,
            related_id=order.order_no,
            note=f'订单删除回滚抵扣：{order.order_no}，恢复备货ID {stockout.stockin_id if stockout.stockin_id else "未知"} 的 {stockout.quantity} 件'
        )
        db.add(stockout_log)

    product.current_stock -= order.quantity
    if product.current_stock < 0:
        logger.warning(f'库存出现负数：产品{product.name}(ID:{product.id})，当前库存{product.current_stock}')
    if total_deducted > 0:
        product.current_stock += total_deducted

    log = InventoryLog(
        product_id=order.product_id,
        change_type='订单删除',
        change_quantity=-order.quantity,
        related_id=order.order_no,
        note=f'订单删除：{order.order_no}，订单数量：{order.quantity}，抵扣回滚数量：{total_deducted}'
    )
    db.add(log)

    await db.execute(delete(StockOut).where(StockOut.order_id == order.id))
    await db.execute(delete(OrderSyncRecord).where(OrderSyncRecord.source_order_id == order_id))

    result = await db.execute(
        select(ApprovalRequest.id).where(ApprovalRequest.order_id == order_id)
    )
    approval_ids = [row[0] for row in result.all()]
    if approval_ids:
        await db.execute(delete(ApprovalLog).where(ApprovalLog.approval_request_id.in_(approval_ids)))
    await db.execute(delete(ApprovalRequest).where(ApprovalRequest.order_id == order_id))

    deleted_order_no = order.order_no
    db.expire(order)
    await db.refresh(order)
    await db.delete(order)

    try:
        from fastapi_app.services.order_purchase_sync import sync_order_delete
        sync_result = await sync_order_delete(db, order_id)
        if sync_result['deleted_purchase_orders'] > 0 or sync_result['updated_purchase_orders'] > 0:
            logger.info(f'采购中心同步删除：{sync_result}')
    except (ValueError, OSError) as e:
        logger.warning(f'采购中心同步删除失败：{e}')

    await db.commit()
    try:
        await invalidate_related_caches(CacheDomain.ORDER_AND_INVENTORY)
    except (OSError, ValueError) as e:
        logger.warning(f'缓存清除失败：{e}')

    try:
        from fastapi_app.core.purchase_cache import invalidate_purchase_caches
        await invalidate_purchase_caches()
    except Exception:
        logger.warning("采购中心缓存失效失败(delete)", exc_info=True)

    try:
        from fastapi_app.services.notification_service import StockEvent, publish_stock_event
        asyncio.ensure_future(publish_stock_event(StockEvent.ORDER_DELETED, {
            'order_id': order_id,
            'order_no': deleted_order_no,
        }))
    except Exception:
        logger.warning("订单删除事件发布失败", exc_info=True)

    logger.info(f'订单删除成功：{deleted_order_no}，操作人：{current_user.username}，抵扣回滚：{total_deducted}')
    return {'success': True, 'message': f'订单删除成功！抵扣回滚数量：{total_deducted}', 'requires_approval': False}


async def _submit_delete_approval(
    db: AsyncSession, order: Order, order_id: int, current_user: User,
) -> dict:
    await _ensure_no_pending_request(db, order_id, current_user, '删除')

    order.is_locked = True
    order.locked_by_id = current_user.id
    order.lock_time = datetime.now(UTC).replace(tzinfo=None)

    operation_data = {
        'order_no': order.order_no,
        'customer': order.customer,
        'quantity': order.quantity,
        'product_name': order.product.name if order.product else '',
        'note': order.note or ''
    }

    approval_request = ApprovalRequest(
        order_id=order_id,
        requester_id=current_user.id,
        operation_type=ApprovalRequest.OPERATION_DELETE,
        operation_data=json.dumps(operation_data, ensure_ascii=False),
        status=ApprovalRequest.STATUS_PENDING,
        lock_time=datetime.now(UTC).replace(tzinfo=None)
    )
    db.add(approval_request)
    await db.flush()

    await _create_approval_log_obj(approval_request, ApprovalLog.ACTION_CREATE, current_user, {'operation_data': operation_data})

    await db.commit()
    await invalidate_related_caches(CacheDomain.ORDER_AND_INVENTORY)
    logger.info(f'订单删除审批请求已提交：{order.order_no}，申请人：{current_user.username}')
    return {'success': True, 'message': '已提交删除审批请求，请等待管理员审批！', 'requires_approval': True}


async def cancel_approval(db: AsyncSession, approval_id: int, current_user: User) -> None:
    approval_request = await db.get(ApprovalRequest, approval_id)
    if not approval_request:
        raise ValueError('审批请求不存在')

    if approval_request.requester_id != current_user.id and not current_user.is_super:
        raise PermissionDeniedError('您没有权限取消此审批请求')

    if not can_transition(approval_request.status, 'cancel'):
        raise ValueError(f'该审批请求当前状态为"{approval_request.status}"，无法取消')

    order = await db.get(Order, approval_request.order_id)
    if order and not order.is_deleted:
        order.is_locked = False
        order.locked_by_id = None
        order.lock_time = None

    approval_request.status = ApprovalRequest.STATUS_CANCELLED

    await _create_approval_log_obj(approval_request, ApprovalLog.ACTION_CANCEL, current_user, {'reason': '用户主动取消'})

    await db.commit()


async def get_my_approvals(db: AsyncSession, current_user: User) -> list[dict]:
    """获取我的审批请求"""
    result = await db.execute(
        select(ApprovalRequest)
        .options(joinedload(ApprovalRequest.order), joinedload(ApprovalRequest.requester))
        .where(ApprovalRequest.requester_id == current_user.id)
        .order_by(ApprovalRequest.request_time.desc())
    )
    approvals = result.scalars().unique().all()
    return [a.to_dict() for a in approvals]


# ==================== 内部辅助函数 ====================

async def _check_order_lock(db: AsyncSession, order_id: int, order: Order,
                             current_user: User, action: str) -> None:
    if not (order.is_locked and order.locked_by_id != current_user.id):
        return
    result = await db.execute(
        select(ApprovalRequest).options(
            joinedload(ApprovalRequest.requester)
        ).where(
            ApprovalRequest.order_id == order_id,
            ApprovalRequest.status == ApprovalRequest.STATUS_PENDING,
        )
    )
    pending = result.unique().scalar_one_or_none()
    if pending:
        raise ValueError(f'该订单正在等待审批（申请人：{pending.requester.username}），暂时无法{action}！')
    raise ValueError(f'该订单已被其他用户锁定，暂时无法{action}！')


async def _ensure_no_pending_request(db: AsyncSession, order_id: int,
                                      current_user: User, action: str) -> None:
    result = await db.execute(
        select(ApprovalRequest).where(
            ApprovalRequest.order_id == order_id,
            ApprovalRequest.requester_id == current_user.id,
            ApprovalRequest.status == ApprovalRequest.STATUS_PENDING,
        )
    )
    if result.scalar_one_or_none():
        raise ValueError(f'您已提交过该订单的{action}审批请求，请等待管理员审批！')


async def _generate_order_number(db: AsyncSession) -> str:
    from fastapi_app.services.batch_service import generate_order_number
    return await generate_order_number(db)


async def _create_approval_log_obj(approval_request: ApprovalRequest, action: str,
                                    actor: User, details: dict | None = None) -> None:
    from sqlalchemy.orm import object_session

    from fastapi_app.services.approval_service import _create_approval_log
    session = object_session(approval_request)
    if session:
        await _create_approval_log(session, approval_request, action, actor, details)


class _BatchItemError(Exception):
    """批量处理单项业务校验失败，用于触发 savepoint 回滚但不作为真实错误"""


async def batch_create_orders(db: AsyncSession, orders_data: list) -> dict:
    """批量创建订单

    注意：同步至采购中心的操作不在此函数内执行，由调用方在事务提交后统一处理，
    以确保同步线程池中的独立 Session 能读取到已提交的订单数据。
    """
    from fastapi_app.services.batch_service import generate_order_number

    results = []
    created_order_ids = []  # 记录成功创建的订单ID，用于同步采购中心
    for order_data in orders_data:
        try:
            async with db.begin_nested():
                product_id = order_data.get('product_id')
                customer = order_data.get('customer', '')
                quantity = order_data.get('quantity', 0)

                if not all([product_id, customer, quantity]):
                    results.append({
                        'success': False, 'error': '缺少必填字段',
                        'order_no': order_data.get('order_no', '未知')
                    })
                    raise _BatchItemError()

                if int(quantity) <= 0 or int(quantity) > 9999999:
                    results.append({
                        'success': False, 'error': '订单数量必须在1-9999999之间',
                        'order_no': order_data.get('order_no', '未知')
                    })
                    raise _BatchItemError()

                product = await get_product_for_update(db, product_id)

                order_no = await generate_order_number(db)

                order = Order(
                    order_no=order_no,
                    product_id=product_id,
                    customer=customer,
                    quantity=int(quantity),
                    order_date=datetime.now(UTC).replace(tzinfo=None),
                    status='待备货',
                    note=order_data.get('note', ''),
                    order_type=order_data.get('order_type', 'regular'),
                    country=order_data.get('country') if order_data.get('order_type') == 'custom' else None,
                )
                db.add(order)
                await db.flush()

                product.current_stock += int(quantity)

                log = InventoryLog(
                    product_id=product_id,
                    change_type='订单创建',
                    change_quantity=int(quantity),
                    change_date=datetime.now(UTC).replace(tzinfo=None),
                    customer=customer,
                    related_id=str(order.id),
                    note=f'批量创建订单 {order.order_no}',
                )
                db.add(log)

                # 处理抵扣备货
                deduct_stock = bool(order_data.get('deduct_stock'))
                deduct_quantity = int(order_data.get('deduct_quantity', 0) or 0)
                if deduct_stock and deduct_quantity > 0:
                    try:
                        from fastapi_app.services.batch_service import process_order_deduction
                        await process_order_deduction(
                            db, order, product_id, int(quantity),
                            deduct_stock=True,
                            custom_deduct_quantity=deduct_quantity,
                            product=product,
                        )
                    except Exception as ded_err:
                        logger.error(f"订单抵扣处理失败: {ded_err}", exc_info=True)
                        results.append({
                            'success': False, 'error': '抵扣处理失败，请稍后重试',
                            'order_no': order.order_no,
                        })
                        raise _BatchItemError() from ded_err

                results.append({
                    'success': True, 'order_no': order.order_no, 'id': order.id
                })
                created_order_ids.append(order.id)
        except _BatchItemError:
            pass  # 业务校验失败，savepoint 已自动回滚，继续下一项
        except (ValueError, TypeError, OSError) as e:
            # 数据库异常，begin_nested 已自动回滚 savepoint，session 恢复有效状态
            logger.error(f"批量订单单项失败: {e}", exc_info=True)
            results.append({
                'success': False, 'error': str(e) or '订单处理失败，请稍后重试',
                'order_no': order_data.get('order_no', '未知')
            })

    return {'success': True, 'results': results, 'created_order_ids': created_order_ids}
