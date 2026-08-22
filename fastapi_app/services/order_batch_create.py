"""
订单批量创建

职责：批量创建订单的独立逻辑，含抵扣备货处理。
从 order_service.py 拆分而来，保持函数签名不变。

Task 3（多 SKU 订单聚合）：按 customer 分组，同一客户的多个 SKU 生成
1 个主订单（Order）+ N 个 OrderItem，库存抵扣按 OrderItem 粒度执行。
"""
import logging
from datetime import UTC, datetime

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from fastapi_app.core.business_rules import MAX_QUANTITY
from fastapi_app.services.notification_service import (
    dispatch_beile_unconfirmed_notifications,
    dispatch_factory_notifications,
)
from fastapi_app.services.order_deduction_service import process_order_deduction
from fastapi_app.shared_models import (
    InventoryLog,
    Order,
    OrderItem,
    Product,
)
from fastapi_app.shared_models.order import ORDER_STATUS_PENDING_STOCK

logger = logging.getLogger(__name__)


class _SavepointRollbackSignalError(Exception):
    """批量处理单项业务校验失败，用于触发 savepoint 回滚但不作为真实错误"""


async def batch_create_orders(db: AsyncSession, orders_data: list) -> dict:
    """批量创建订单

    按 customer 聚合：同一客户的多个 SKU 生成 1 个主订单 + N 个 OrderItem。
    注意：同步至采购中心的操作不在此函数内执行，由调用方在事务提交后统一处理，
    以确保同步线程池中的独立 Session 能读取到已提交的订单数据。
    """
    from fastapi_app.services.numbering import generate_order_number

    results = []
    created_order_ids = []

    # 收集所有 product_ids（保留加锁查询优化，避免 N+1）
    product_ids = []
    for order_data in orders_data:
        try:
            pid = int(order_data.get('product_id', 0))
            if pid > 0:
                product_ids.append(pid)
        except (TypeError, ValueError):
            pass  # defensive: 异常静默处理,不影响主流程
    product_ids = sorted(set(product_ids))

    # 按 customer 分组（dict 保持首次出现顺序）
    grouped: dict[str, list] = {}
    for order_data in orders_data:
        customer = str(order_data.get('customer', '')).strip()
        grouped.setdefault(customer, []).append(order_data)

    product_map: dict[int, Product] = {}

    for customer, items in grouped.items():
        try:
            async with db.begin_nested():
                # 加锁查询所有相关 Product（仅首次进入时执行）
                if product_ids and not product_map:
                    lock_result = await db.execute(  # batch-loop: 有意逐行处理,非 N+1
                        select(Product).where(Product.id.in_(product_ids)).with_for_update()
                    )
                    product_map = {p.id: p for p in lock_result.scalars().all()}

                # 预校验所有 item
                validated_items: list[dict] = []
                for order_data in items:
                    try:
                        product_id = int(order_data['product_id'])
                    except (TypeError, ValueError, KeyError):
                        results.append({
                            'success': False, 'error': '无效的产品ID',
                            'customer': customer,
                        })
                        raise _SavepointRollbackSignalError() from None
                    try:
                        quantity = int(order_data.get('quantity', 0))
                    except (TypeError, ValueError):
                        results.append({
                            'success': False, 'error': '无效的订单数量',
                            'customer': customer,
                        })
                        raise _SavepointRollbackSignalError() from None

                    if not product_id or not customer or quantity <= 0:
                        results.append({
                            'success': False, 'error': '缺少必填字段',
                            'customer': customer,
                        })
                        raise _SavepointRollbackSignalError()

                    if quantity > MAX_QUANTITY:
                        results.append({
                            'success': False,
                            'error': f'订单数量必须在 1-{MAX_QUANTITY} 之间',
                            'customer': customer,
                        })
                        raise _SavepointRollbackSignalError()

                    product = product_map.get(product_id)
                    if not product:
                        results.append({
                            'success': False, 'error': '产品不存在',
                            'customer': customer,
                        })
                        raise _SavepointRollbackSignalError()

                    # 工厂校验：product.factory 为空时仅记录警告，不阻断订单创建
                    # 旧产品可能尚未回填 factory 字段，强制拦截会导致大量订单无法录入
                    if not product.factory:
                        logger.warning(
                            "产品 %s (id=%d) 未配置工厂，订单仍会创建但工厂通知可能无法精准派发",
                            product.name, product_id,
                        )

                    order_type = order_data.get('order_type', 'regular')
                    validated_items.append({
                        'product_id': product_id,
                        'quantity': quantity,
                        'product': product,
                        'order_type': order_type,
                        'country': order_data.get('country') if order_type == 'custom' else None,
                        'deduct_stock': bool(order_data.get('deduct_stock')),
                        'deduct_quantity': int(order_data.get('deduct_quantity', 0) or 0),
                        'note': order_data.get('note', ''),
                    })

                # 创建主订单（1 个 order_no）
                first_item = validated_items[0]
                total_quantity = sum(it['quantity'] for it in validated_items)
                order_no = await generate_order_number(db)
                order = Order(
                    order_no=order_no,
                    product_id=first_item['product_id'],  # NOT NULL 兼容，新代码应读 order.items
                    customer=customer,
                    quantity=total_quantity,  # 兼容旧代码读取 order.quantity
                    order_date=datetime.now(UTC).replace(tzinfo=None),  # naive UTC: DB列类型为 TIMESTAMP WITHOUT TIME ZONE
                    status=ORDER_STATUS_PENDING_STOCK,
                    note='',  # 主订单级 note 留空，SKU 级 note 在 OrderItem
                    order_type=first_item['order_type'],
                    country=first_item['country'] if first_item['order_type'] == 'custom' else None,
                )
                db.add(order)
                await db.flush()

                # 为每个 SKU 创建 OrderItem + InventoryLog
                created_items: list[OrderItem] = []
                for it in validated_items:
                    product = it['product']
                    order_item = OrderItem(
                        order_id=order.id,
                        product_id=it['product_id'],
                        product_name=product.name,
                        product_barcode=getattr(product, 'barcode', None),
                        quantity=it['quantity'],
                        order_type=it['order_type'],
                        country=it['country'],
                        deduct_stock=it['deduct_stock'],
                        deduct_quantity=it['deduct_quantity'],
                        note=it['note'],
                    )
                    db.add(order_item)
                    await db.flush()
                    created_items.append(order_item)

                    log = InventoryLog(
                        product_id=it['product_id'],
                        change_type='订单创建',
                        change_quantity=it['quantity'],
                        change_date=datetime.now(UTC).replace(tzinfo=None),  # naive UTC: DB列类型为 TIMESTAMP WITHOUT TIME ZONE
                        customer=customer,
                        related_id=str(order.id),
                        note=f'批量创建订单 {order.order_no} - SKU {product.name}',
                    )
                    db.add(log)

                # 返单自动带出外发工序：按 SKU 预设为订单生成湖北外发工序（失败不影响订单创建）
                try:
                    from fastapi_app.services.outsource_service import auto_generate_for_order
                    await auto_generate_for_order(db, order)
                except Exception as og_err:  # broad-except: 服务层容错，记录异常并返回安全默认值
                    logger.warning(
                        "自动生成外发工序失败 order_no=%s: %s", order.order_no, og_err,
                        exc_info=True,
                    )

                # 处理抵扣备货（按 OrderItem 粒度）
                # 保留原 deduct_quantity > 0 守卫：process_order_deduction 在
                # custom_deduct_quantity<=0 时会回退到按 order_quantity 全量抵扣，
                # 必须显式跳过 deduct_quantity=0 的项以避免误扣库存。
                for _order_item, it in zip(created_items, validated_items, strict=False):
                    if it['deduct_stock'] and it['deduct_quantity'] > 0:
                        try:
                            await process_order_deduction(
                                db, order, it['product_id'], it['quantity'],
                                deduct_stock=True,
                                custom_deduct_quantity=it['deduct_quantity'],
                                product=it['product'],
                            )
                        except (ValueError, TypeError, RuntimeError, OSError) as ded_err:
                            logger.error(f"订单抵扣处理失败: {ded_err}", exc_info=True)
                            results.append({
                                'success': False, 'error': '抵扣处理失败，请稍后重试',
                                'customer': customer,
                            })
                            raise _SavepointRollbackSignalError() from ded_err

                results.append({
                    'success': True,
                    'order_no': order.order_no,
                    'id': order.id,
                    'customer': customer,
                    'items': [
                        {
                            'id': oi.id,
                            'order_id': oi.order_id,
                            'product_id': oi.product_id,
                            'product_name': oi.product_name,
                            'product_barcode': oi.product_barcode,
                            'quantity': oi.quantity,
                            'order_type': oi.order_type,
                            'country': oi.country,
                            'deduct_stock': oi.deduct_stock,
                            'deduct_quantity': oi.deduct_quantity,
                            'note': oi.note,
                        }
                        for oi in created_items
                    ],
                })
                created_order_ids.append(order.id)

                # Task 3.1: 派发工厂通知（new_order）
                # 仅 flush 不 commit，与 batch_create_orders 事务模型一致；
                # 通知失败不应影响订单创建，捕获异常仅记录日志。
                # 湖北订单确认流程去重：含湖北 SKU 的订单跳过通用工厂通知中的
                # 「湖北」工厂——湖北用户由下方 dispatch_beile_unconfirmed_notifications
                # （湖北新订单待确认，可跳转 beile-order 高亮、确认时自动已读）覆盖，
                # 避免同一订单给同一用户派发两条重复通知；其他地区工厂不受影响。
                has_hubei_sku = any(
                    product_map.get(it.product_id) is not None
                    and product_map[it.product_id].factory == '湖北'
                    for it in created_items
                )
                try:
                    await dispatch_factory_notifications(
                        db, order, 'new_order', created_items,
                        skip_factory='湖北' if has_hubei_sku else None,
                    )
                except Exception as notify_err:  # broad-except: 服务层容错，记录异常并返回安全默认值
                    logger.warning(
                        "工厂通知派发失败 order_no=%s: %s", order.order_no, notify_err,
                        exc_info=True,
                    )

                # 湖北新订单未确认提醒（独立确认流程，仅湖北 SKU 派发；失败不影响订单创建）
                try:
                    await dispatch_beile_unconfirmed_notifications(
                        db, order, [(it.product_id, it.quantity) for it in created_items]
                    )
                except Exception as notify_err:  # broad-except: 服务层容错，记录异常并返回安全默认值
                    logger.warning(
                        "湖北未确认提醒派发失败 order_no=%s: %s", order.order_no, notify_err,
                        exc_info=True,
                    )
        except _SavepointRollbackSignalError:
            pass  # 业务校验失败，savepoint 已自动回滚，继续下一组; defensive: 异常静默处理,不影响主流程
        except (ValueError, TypeError, OSError) as e:
            # 数据库异常，begin_nested 已自动回滚 savepoint，session 恢复有效状态
            logger.error(f"批量订单分组失败: {e}", exc_info=True)
            results.append({
                'success': False,
                'error': str(e) or '订单处理失败，请稍后重试',
                'customer': customer,
            })
        except SQLAlchemyError as e:
            # 数据库异常会污染 session（savepoint 仅自动回滚嵌套事务），必须整体回滚并终止批量流程
            logger.error(f"批量创建订单时数据库异常: {e}", exc_info=True)
            await db.rollback()  # manual-tx: try/except 内显式事务控制
            raise HTTPException(status_code=500, detail='批量创建订单时数据库异常') from e

    return {
        'success': True,
        'created_count': len(created_order_ids),
        'results': results,
        'created_order_ids': created_order_ids,
    }
