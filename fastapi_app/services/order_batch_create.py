"""
订单批量创建

职责：批量创建订单的独立逻辑，含抵扣备货处理。
从 order_service.py 拆分而来，保持函数签名不变。

Task 3（多 SKU 订单聚合）：按 customer 分组，同一客户的多个 SKU 生成
1 个主订单（Order）+ N 个 OrderItem，库存抵扣按 OrderItem 粒度执行。

2026-09-14 重构：`batch_create_orders` 由 219 行拆为 1 个编排函数 + 9 个职责单一函数，
零行为变化（字段口径、校验顺序、异常分支、savepoint 语义均逐条对齐）。

2026-10-02 P1-5 锁顺序：产品行锁改为「每个 customer 分组只锁本组商品」且 SQL 显式
`ORDER BY product.id`（IN 列表同样升序），消除并发批量在商品集合重叠时的交叉死锁
窗口；锁粒度不变（仍为 Product 行级 `FOR UPDATE`）。
"""
import logging
from datetime import UTC, datetime
from typing import NoReturn

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from fastapi_app.core.business_rules import MAX_QUANTITY
from fastapi_app.core.exceptions import InternalError
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


def _resolve_order_date(raw) -> datetime:
    """把用户选择的下单日期（YYYY-MM-DD）解析为 aware UTC 当日零点。

    未提供（空值）时回退当前时刻。order_date 列为 timestamptz，必须写 aware 值，
    否则 asyncpg 会按 Asia/Shanghai 解释导致时刻偏移 8 小时。
    """
    if not raw:
        return datetime.now(UTC)
    try:
        parsed = datetime.strptime(str(raw).strip(), '%Y-%m-%d')
    except (ValueError, TypeError):
        raise ValueError(f'订单时间格式错误，请使用 YYYY-MM-DD 格式：{raw}') from None
    return datetime(parsed.year, parsed.month, parsed.day, tzinfo=UTC)


def _collect_product_ids(orders_data: list) -> list[int]:
    """收集给定条目引用的 product_id（去重升序），供本组一次性加锁查询，避免循环内逐条查询。"""
    product_ids = []
    for order_data in orders_data:
        try:
            pid = int(order_data.get('product_id', 0))
            if pid > 0:
                product_ids.append(pid)
        except (TypeError, ValueError):
            pass  # defensive: 异常静默处理,不影响主流程
    return sorted(set(product_ids))


def _group_by_customer(orders_data: list) -> dict[str, list]:
    """按 customer 分组（dict 保持首次出现顺序）。"""
    grouped: dict[str, list] = {}
    for order_data in orders_data:
        customer = str(order_data.get('customer', '')).strip()
        grouped.setdefault(customer, []).append(order_data)
    return grouped


async def _lock_products(db: AsyncSession, product_ids: list[int]) -> dict[int, Product]:
    """按 id 升序一次性加锁查询本组产品，返回 {product_id: Product}。

    P1-5：显式 ORDER BY Product.id（IN 列表同样升序），使多个并发批量在商品集合重叠
    时按同一顺序获取 Product 行锁，消除「集合相同、获取顺序不同」的交叉死锁窗口；加锁
    范围由调用方限制为当前 customer 分组实际引用的商品，不再把整批商品的行锁贯穿整个
    批量循环。锁粒度不变：仍是 Product 行级 FOR UPDATE（非表锁、非 NOWAIT/SKIP LOCKED）。
    """
    if not product_ids:
        return {}
    ordered_ids = sorted(product_ids)
    lock_result = await db.execute(  # batch-loop: 有意逐行处理,非 N+1
        select(Product)
        .where(Product.id.in_(ordered_ids))
        .order_by(Product.id)
        .with_for_update()
    )
    return {p.id: p for p in lock_result.scalars().all()}


def _validate_one_item(order_data: dict, customer: str, product_map: dict, results: list) -> dict:
    """校验单条订单数据并归一化为 validated item。

    失败时向 results 追加失败结果并抛 _SavepointRollbackSignalError，
    由调用方所在 savepoint 回滚整组（保持重构前的错误文案与判定顺序）。
    """

    def _fail(message: str) -> NoReturn:
        # P2-A2 类型收窄：标明 _fail 恒抛，mypy 据此在调用点收窄 product（运行时零变化）
        results.append({'success': False, 'error': message, 'customer': customer})
        raise _SavepointRollbackSignalError()

    try:
        product_id = int(order_data['product_id'])
    except (TypeError, ValueError, KeyError):
        _fail('无效的产品ID')
    try:
        quantity = int(order_data.get('quantity', 0))
    except (TypeError, ValueError):
        _fail('无效的订单数量')

    if not product_id or not customer or quantity <= 0:
        _fail('缺少必填字段')

    if quantity > MAX_QUANTITY:
        _fail(f'订单数量必须在 1-{MAX_QUANTITY} 之间')

    product = product_map.get(product_id)
    if not product:
        _fail('产品不存在')
    # 工厂校验：product.factory 为空时仅记录警告，不阻断订单创建
    # 旧产品可能尚未回填 factory 字段，强制拦截会导致大量订单无法录入
    if not product.factory:  # type: ignore[union-attr] # _fail 必抛但 mypy 无法据此收窄
        logger.warning(
            "产品 %s (id=%d) 未配置工厂，订单仍会创建但工厂通知可能无法精准派发",
            product.name, product_id,
        )

    return {
        'product_id': product_id,
        'quantity': quantity,
        'product': product,
        'deduct_stock': bool(order_data.get('deduct_stock')),
        'deduct_quantity': int(order_data.get('deduct_quantity', 0) or 0),
        'note': order_data.get('note', ''),
        'order_date': order_data.get('order_date') or '',
    }


def _validate_group_items(items: list, customer: str, product_map: dict, results: list) -> list[dict]:
    """预校验同一客户的一组订单数据；任一条失败即记录并回滚整组。"""
    validated_items: list[dict] = []
    for order_data in items:
        validated_items.append(_validate_one_item(order_data, customer, product_map, results))
    return validated_items


async def _create_order_header(db: AsyncSession, customer: str, validated_items: list) -> Order:
    """创建主订单（1 个 order_no，兼容字段取首个 SKU）。"""
    from fastapi_app.services.numbering import generate_order_number

    first_item = validated_items[0]
    total_quantity = sum(it['quantity'] for it in validated_items)
    order_no = await generate_order_number(db)
    order = Order(
        order_no=order_no,
        product_id=first_item['product_id'],  # NOT NULL 兼容，新代码应读 order.items
        customer=customer,
        quantity=total_quantity,  # 兼容旧代码读取 order.quantity
        order_date=_resolve_order_date(first_item.get('order_date')),  # 用户选择的下单日期；未选时回退当前时刻。aware UTC：order_date 列为 timestamptz（pg_standalone_013），naive 值会被按本地时区解释致早 8h
        status=ORDER_STATUS_PENDING_STOCK,
        note='',  # 主订单级 note 留空，SKU 级 note 在 OrderItem
    )
    db.add(order)
    await db.flush()
    return order


async def _create_order_items(
    db: AsyncSession, order: Order, customer: str, validated_items: list,
) -> list[OrderItem]:
    """为每个 SKU 创建 OrderItem + InventoryLog。"""
    created_items: list[OrderItem] = []
    for it in validated_items:
        product = it['product']
        order_item = OrderItem(
            order_id=order.id,
            product_id=it['product_id'],
            product_name=product.name,
            product_barcode=getattr(product, 'barcode', None),
            quantity=it['quantity'],
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
            change_date=datetime.now(UTC),  # aware UTC：change_date 列为 timestamptz
            customer=customer,
            related_id=str(order.id),
            note=f'批量创建订单 {order.order_no} - SKU {product.name}',
        )
        db.add(log)
    return created_items


async def _auto_generate_outsource(db: AsyncSession, order: Order) -> None:
    """返单自动带出外发工序（失败不影响订单创建）。"""
    try:
        from fastapi_app.services.outsource_service import auto_generate_for_order
        await auto_generate_for_order(db, order)
    except Exception as og_err:  # broad-except: 服务层容错，记录异常并返回安全默认值
        logger.warning(
            "自动生成外发工序失败 order_no=%s: %s", order.order_no, og_err,
            exc_info=True,
        )


async def _apply_deductions(
    db: AsyncSession, order: Order, created_items: list, validated_items: list,
    customer: str, results: list,
) -> None:
    """处理抵扣备货（按 OrderItem 粒度）。

    保留原 deduct_quantity > 0 守卫：process_order_deduction 在
    custom_deduct_quantity<=0 时会回退到按 order_quantity 全量抵扣，
    必须显式跳过 deduct_quantity=0 的项以避免误扣库存。
    """
    for _order_item, it in zip(created_items, validated_items, strict=False):
        if not (it['deduct_stock'] and it['deduct_quantity'] > 0):
            continue
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


def _build_success_result(order: Order, customer: str, created_items: list) -> dict:
    """组装单个客户的成功结果（含全部 SKU 明细）。"""
    return {
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
                'deduct_stock': oi.deduct_stock,
                'deduct_quantity': oi.deduct_quantity,
                'note': oi.note,
            }
            for oi in created_items
        ],
    }


async def _dispatch_notifications(
    db: AsyncSession, order: Order, created_items: list, product_map: dict,
) -> None:
    """派发工厂通知与湖北未确认提醒（两者失败均不影响订单创建）。

    仅 flush 不 commit，与 batch_create_orders 事务模型一致。

    湖北订单确认流程去重：含湖北 SKU 的订单跳过通用工厂通知中的「湖北」工厂 ——
    湖北用户由 dispatch_beile_unconfirmed_notifications（湖北新订单待确认，可跳转
    beile-order 高亮、确认时自动已读）覆盖，避免同一订单给同一用户派发两条重复
    通知；其他地区工厂不受影响。
    """
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


async def batch_create_orders(db: AsyncSession, orders_data: list) -> dict:
    """批量创建订单

    按 customer 聚合：同一客户的多个 SKU 生成 1 个主订单 + N 个 OrderItem。
    注意：同步至采购中心的操作不在此函数内执行，由调用方在事务提交后统一处理，
    以确保同步线程池中的独立 Session 能读取到已提交的订单数据。
    """
    results: list[dict] = []
    created_order_ids: list[int] = []

    # 按 customer 分组（dict 保持首次出现顺序）
    grouped = _group_by_customer(orders_data)

    # 一次性按 id 升序锁定本批涉及的全部商品（P1-5 修正）。
    # 曾改成「逐分组各自加锁」以缩小锁范围，但那会重新打开跨组死锁：分组顺序取决于请求里
    # customer 的首次出现顺序，T1 按 [A(p1), B(p2)]、T2 按 [B(p2), A(p1)] 处理时双方各持
    # 一把、互等对方。对分组排序也无法消除这种交叉（分组构成逐请求不同）——只有「单条语句
    # 按全局升序取锁」才能让所有并发批次的取锁顺序一致。锁粒度不变：Product 行级 FOR UPDATE。
    product_map: dict[int, Product] = await _lock_products(db, _collect_product_ids(orders_data))

    for customer, items in grouped.items():
        try:
            async with db.begin_nested():
                validated_items = _validate_group_items(items, customer, product_map, results)
                order = await _create_order_header(db, customer, validated_items)
                created_items = await _create_order_items(db, order, customer, validated_items)
                await _auto_generate_outsource(db, order)
                await _apply_deductions(db, order, created_items, validated_items, customer, results)
                results.append(_build_success_result(order, customer, created_items))
                created_order_ids.append(order.id)
                await _dispatch_notifications(db, order, created_items, product_map)
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
            raise InternalError('批量创建订单时数据库异常') from e

    return {
        'success': True,
        'created_count': len(created_order_ids),
        'results': results,
        'created_order_ids': created_order_ids,
    }
