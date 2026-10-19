"""订单命令（创建/编辑/删除及直接执行路径、编号生成）

自 order_crud.py 拆分（批次1-3），函数原文零改动。"""
# ruff: noqa: F401 - 拆分过渡期沿用完整导入块，待按模块收敛未用导入
import json
import logging
import os
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import delete, func, or_, select, tuple_, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload, selectinload

from fastapi_app.core.cache import CacheDomain, cache_result
from fastapi_app.core.cache_invalidation import InvalidationStrategy, cache_mgr, schedule_post_commit_invalidation
from fastapi_app.core.exception_handler import INFRA_EXCEPTIONS
from fastapi_app.core.exceptions import BusinessError, NotFoundError
from fastapi_app.core.state_machine import can_transition
from fastapi_app.core.validators import validate_not_empty, validate_quantity_range
from fastapi_app.services import escape_like
from fastapi_app.services.enhanced_pagination import (
    OFFSET_THRESHOLD,
    optimized_count,
)
from fastapi_app.services.notification_service import (
    StockEvent,
    dispatch_factory_notifications,
)
from fastapi_app.services.numbering import generate_order_number
from fastapi_app.services.order._common import (
    PermissionDeniedError,
    _safe_invalidate_purchase_cache,
    schedule_post_commit_event,
)
from fastapi_app.services.order_utils import (
    _batch_deduct_quantities,
    assert_no_linked_returns,
    compute_order_status_from_db,
    detach_cancelled_returns_for_order,
    sync_single_item_quantity,
)
from fastapi_app.services.serializers.order_serializer import (
    OrderSerializer,
)
from fastapi_app.shared.order_stock_rollback import rollback_order_stock_by_sku
from fastapi_app.shared.stock_concurrency import get_product_for_update
from fastapi_app.shared_models import (
    ApprovalLog,
    ApprovalRequest,
    AuditLog,
    InventoryLog,
    Notification,
    Order,
    OrderItem,
    OrderOutsourceProcess,
    OrderOutsourceProcessFlow,
    OrderStatusLog,
    OrderSyncRecord,
    OutsourceShipment,
    OutsourceShipmentItem,
    Product,
    PurchasePlanDetail,
    StockIn,
    StockOut,
    SyncRetryQueue,
    User,
)
from fastapi_app.shared_models.order import ORDER_STATUS_PENDING_STOCK

logger = logging.getLogger(__name__)


async def _invalidate_order_domains() -> None:
    """失效订单/库存与报表域缓存（供 post-commit 兜底回调复用）。"""
    await cache_mgr.invalidate(
        InvalidationStrategy.DOMAIN,
        CacheDomain.ORDER_AND_INVENTORY | CacheDomain.REPORT,
    )



from fastapi_app.services.order.approval_flow import (
    _check_order_lock,
    _ensure_no_pending_request,
    _submit_delete_approval,
    _submit_edit_approval,
)


async def create_order(db: AsyncSession, product_id: int, quantity: int,
                       customer: str, note: str, current_user: User) -> dict:
    """
    创建订单

    业务规则：
    - 产品必须存在
    - 数量 > 0 且 <= 9999999
    - 客户名称不能为空
    - 创建订单记录及库存日志（不影响物理库存）
    """
    validate_quantity_range(quantity, "订单数量")
    validate_not_empty(customer, "客户名称")  # 2026-10-17 审计 P2-06：docstring 写了但代码缺失

    product = await get_product_for_update(db, product_id)

    order_no = await generate_order_number(db)

    async with db.begin_nested():
        order = Order(
            order_no=order_no,
            customer=customer,
            order_date=datetime.now(UTC),  # aware UTC：order_date 列为 timestamptz，naive 值会被按本地时区解释致早 8h
            product_id=product_id,
            quantity=quantity,
            note=note,
            status=ORDER_STATUS_PENDING_STOCK,
        )
        db.add(order)
        await db.flush()

        # 写入 OrderItem 明细（与兼容值 product_id/quantity 一致）：与批量创建路径对齐，
        # 保证所有订单都有 SKU 级明细，读取方后续可迁移为遍历 order.items。
        order_item = OrderItem(
            order_id=order.id,
            product_id=product_id,
            product_name=product.name,
            product_barcode=getattr(product, 'barcode', None),
            quantity=quantity,
            note=note,
        )
        db.add(order_item)

        log = InventoryLog(
            product_id=product_id,
            change_type='订单',
            change_quantity=quantity,
            related_id=order_no,
            customer=customer,
            note=f'订单：{order_no}'
        )
        db.add(log)

        await db.flush()
    await db.refresh(order)

    # 返单自动带出外发工序：根据 SKU 预设生成湖北外发工序（失败不影响订单创建）
    from fastapi_app.services.outsource_service import auto_generate_for_order
    await auto_generate_for_order(db, order)

    # 新订单数量计入库存视图（order_agg）与商品首屏 current_stock，
    # 因此必须一并失效 INVENTORY 域，否则下单后 /stock 在 TTL 内仍是旧数据。
    await cache_mgr.invalidate(
        InvalidationStrategy.DOMAIN,
        CacheDomain.ORDER_AND_INVENTORY | CacheDomain.REPORT)
    # dashboard 缓存失效已移至 endpoint 层（事务提交后），此处不再重复
    schedule_post_commit_invalidation(db, _invalidate_order_domains)
    logger.info(f'订单添加成功：{order_no}，客户：{customer}，产品：{product.name}，数量：{quantity}')

    await _safe_invalidate_purchase_cache()

    # 发布订单创建事件，通知前端实时刷新。
    # 必须等提交后再发：客户端收到 order_created 会立刻重取列表，先于提交发出会
    # 读到尚未提交的数据（新订单不在列表里）并缓存该结果，staleTime 内不再回取。
    schedule_post_commit_event(db, StockEvent.ORDER_CREATED, {
            'order_id': order.id,
            'order_no': order_no,
            'customer': customer,
            'product_name': product.name,
            'quantity': quantity,
        })

    # 采购订单自动生成：提交后投递扫描任务（替代采购中心人工「一键审核」）
    from fastapi_app.services.purchase._auto_generate import schedule_auto_generate_purchase_orders
    schedule_auto_generate_purchase_orders(db)

    return order.to_dict()

async def update_order(db: AsyncSession, order_id: int, quantity: int,
                       customer: str, note: str, current_user: User) -> dict:
    # 第十四轮补：锁序统一为 Product→Order —— 出库创建路径是 P→Order
    #（create_stockout_core 先锁产品，再经 calculate_available_shipment_quantity
    # FOR UPDATE 扫同客户全部 Order）。本函数原为 Order→P（先锁订单行、数量变化时
    # _update_order_directly 内才 get_product_for_update），与出库创建并发会互等行锁死锁。
    # 同 update_deduct_quantity 的做法：先无锁读 product_id 预锁产品；读不到
    #（订单不存在/product_id 空）则跳过预锁，由下方加锁后的既有校验按原口径抛错，语义不变。
    _pre_pid = (await db.execute(
        select(Order.product_id).where(Order.id == order_id)
    )).scalar_one_or_none()
    if _pre_pid is not None:
        await get_product_for_update(db, _pre_pid)

    result = await db.execute(select(Order).where(Order.id == order_id).with_for_update())
    order = result.scalar_one_or_none()
    if not order or order.is_deleted:
        raise ValueError('订单不存在')

    await _check_order_lock(db, order_id, order, current_user, '编辑')

    if current_user.is_super:
        return await _update_order_directly(
            db, order, order_id, quantity, customer, note, current_user
        )
    else:
        return await _submit_edit_approval(
            db, order, order_id, quantity, customer, note, current_user
        )


async def update_order_item(db: AsyncSession, item_id: int, quantity: int | None,
                            note: str | None, current_user: User) -> dict:
    """编辑单个订单明细（SKU）：改数量/备注后重算订单兼容数量与状态。

    报表流水行内编辑（2026-10-13）：item 级直改、不走审批（owner 裁决），
    但仍过 `_check_order_lock`（被他人锁定/审批中的订单不可改）。

    锁序 Product→Order→Item：与 `update_order`（P→O）一致，避免与出库创建
    （create_stockout_core 先锁产品再扫订单）互等行锁死锁。
    """
    head = (await db.execute(
        select(OrderItem.order_id, OrderItem.product_id).where(OrderItem.id == item_id)
    )).one_or_none()
    if head is None:
        raise ValueError('订单明细不存在')
    # 预锁产品（锁序 Product→Order）；product_id 可空（历史数据），空则跳过
    if head.product_id is not None:
        await get_product_for_update(db, head.product_id)
    order = (await db.execute(
        select(Order).where(Order.id == head.order_id).with_for_update()
    )).scalar_one_or_none()
    if not order or order.is_deleted:
        raise ValueError('订单不存在')
    await _check_order_lock(db, order.id, order, current_user, '编辑')
    item = (await db.execute(
        select(OrderItem).where(OrderItem.id == item_id).with_for_update()
    )).scalar_one_or_none()
    if item is None:
        # 无锁读到加锁之间可能被并发删除，不能 scalar_one
        raise ValueError('订单明细不存在')

    old_qty = item.quantity
    if quantity is not None:
        validate_quantity_range(quantity, '订单数量')
        item.quantity = quantity
    if note is not None:
        item.note = note
    # autoflush=False（应用与测试同口径）：必须显式 flush，否则下面的 SUM 读不到本次改动
    await db.flush()

    # 订单级兼容数量 = Σ 明细数量（口径见 order_batch_create._create_order_header）
    total = (await db.execute(
        select(func.coalesce(func.sum(OrderItem.quantity), 0))
        .where(OrderItem.order_id == order.id)
    )).scalar_one()
    order.quantity = int(total)

    if quantity is not None and quantity != old_qty:
        db.add(InventoryLog(
            product_id=item.product_id, change_type='订单修改',
            change_quantity=quantity - old_qty,
            related_id=order.order_no, note=f'订单明细修改：{order.order_no}',
        ))
    await db.flush()

    # order.status 是 (抵扣量, 出货量, 数量) 派生值，数量变了必须重算
    order.status = await compute_order_status_from_db(db, order)
    try:
        await dispatch_factory_notifications(db, order, 'order_updated', None)
    except Exception as notify_err:  # broad-except: 通知失败不影响改单
        logger.warning(
            "工厂通知派发失败 order_no=%s: %s", order.order_no, notify_err, exc_info=True,
        )

    await cache_mgr.invalidate(
        InvalidationStrategy.DOMAIN,
        CacheDomain.ORDER_AND_INVENTORY | CacheDomain.REPORT,
    )
    schedule_post_commit_invalidation(db, _invalidate_order_domains)
    await _safe_invalidate_purchase_cache()
    schedule_post_commit_event(db, StockEvent.ORDER_UPDATED,
                               {'order_id': order.id, 'order_no': order.order_no})
    return {'success': True, 'message': '明细修改成功', 'requires_approval': False}


async def delete_order_item(db: AsyncSession, item_id: int, current_user: User) -> dict:
    """删除单个订单明细（SKU）。

    - 非末项：删该 item、重算订单兼容数量与状态；item 级直改、不走审批。
    - 末项：等价删整张订单 —— 复用 `delete_order`（含审批/锁定/备份），**透传其返回值**
      （非超管会变成提交审批，订单不立即删除，故不能硬编码成功文案）。
    - 已被备货抵扣（该订单+该产品存在 stockin_id 非空的出货）时拒删。

    锁序 Product→Order→Item：末项分支会进 delete_order（_load_order_for_delete
    以集合升序预锁整单产品并锁 Order 行）；此处同样以**同一套**
    _prelock_order_products 集合升序预锁（含待删明细产品），保证两条路径
    持有的集合与顺序完全一致，避免以 P→O 之外的顺序与出库创建/整单编辑
    /并发整单删除路径互等行锁死锁（2026-10-19 OCR 第二轮 M4）。
    """
    head = (await db.execute(
        select(OrderItem.order_id, OrderItem.product_id).where(OrderItem.id == item_id)
    )).one_or_none()
    if head is None:
        raise ValueError('订单明细不存在')
    # 整单产品全集升序预锁（含本明细产品作为 extra——明细可能尚无出库行、
    # order.product_id 可能已迁移，不在公共函数的 stockout/order 两个来源里）。
    # 非末项分支会因此多锁本单其他 SKU 的产品行（无害：同事务短暂持有），
    # 换来与 delete_order 的锁序完全一致；末项分支进入 delete_order 后
    # _load_order_for_delete 的重锁全部为 no-op。
    await _prelock_order_products(db, head.order_id, head.product_id)
    order = (await db.execute(
        select(Order).where(Order.id == head.order_id).with_for_update()
    )).scalar_one_or_none()
    if not order or order.is_deleted:
        raise ValueError('订单不存在')
    await _check_order_lock(db, order.id, order, current_user, '删除')

    deducted = (await db.execute(
        select(func.coalesce(func.sum(StockOut.quantity - StockOut.returned_quantity), 0))
        .where(StockOut.order_id == order.id,
               StockOut.product_id == head.product_id,
               StockOut.stockin_id.isnot(None))
    )).scalar_one()
    if int(deducted) > 0:
        raise ValueError('该产品在本订单已被备货抵扣，无法删除')

    siblings = (await db.execute(
        select(func.count()).select_from(OrderItem).where(OrderItem.order_id == order.id)
    )).scalar_one()
    if siblings <= 1:
        # 末项删除 = 整单删除：回传 order_id，供端点层在事务提交后补发 ORDER_DELETED。
        # 采购中心订阅该领域事件撤回本订单已自动生成的 pending 采购单；漏发会让
        # 采购单残留在 /purchase（2026-10-13 PO-20261013-23761/23763 事故）。
        result = await delete_order(db, order.id, current_user)
        result['order_id'] = order.id
        return result

    item = (await db.execute(
        select(OrderItem).where(OrderItem.id == item_id).with_for_update()
    )).scalar_one_or_none()
    if item is None:
        raise ValueError('订单明细不存在')
    # 先取值再删：delete+flush 后不再读对象属性
    pid, qty = item.product_id, item.quantity
    await db.delete(item)
    await db.flush()
    # 删掉的正是「订单兼容产品」所指明细时，把兼容值指向剩余的任一明细，避免悬空
    if pid is not None and pid == order.product_id:
        order.product_id = (await db.execute(
            select(OrderItem.product_id).where(OrderItem.order_id == order.id).limit(1)
        )).scalar_one_or_none()
    total = (await db.execute(
        select(func.coalesce(func.sum(OrderItem.quantity), 0))
        .where(OrderItem.order_id == order.id)
    )).scalar_one()
    order.quantity = int(total)
    db.add(InventoryLog(
        product_id=pid, change_type='订单修改',
        change_quantity=-qty,
        related_id=order.order_no, note=f'订单明细删除：{order.order_no}',
    ))
    await db.flush()

    order.status = await compute_order_status_from_db(db, order)
    try:
        await dispatch_factory_notifications(db, order, 'order_updated', None)
    except Exception as notify_err:  # broad-except: 通知失败不影响删单
        logger.warning(
            "工厂通知派发失败 order_no=%s: %s", order.order_no, notify_err, exc_info=True,
        )
    await cache_mgr.invalidate(
        InvalidationStrategy.DOMAIN,
        CacheDomain.ORDER_AND_INVENTORY | CacheDomain.REPORT,
    )
    schedule_post_commit_invalidation(db, _invalidate_order_domains)
    await _safe_invalidate_purchase_cache()
    schedule_post_commit_event(db, StockEvent.ORDER_UPDATED,
                               {'order_id': order.id, 'order_no': order.order_no})
    return {'success': True, 'message': '明细删除成功', 'requires_approval': False}


async def _update_order_directly(
    db: AsyncSession, order: Order, order_id: int,
    quantity: int, customer: str, note: str,
    current_user: User,
) -> dict:
    validate_quantity_range(quantity, "订单数量")
    validate_not_empty(customer, "客户名称")
    # TODO(multi-sku-order): 读取/修改 order.quantity 在多 SKU 下语义变更（多 item 改哪个？），待后续 spec 改造为遍历 order.items；当前依赖兼容值。
    old_quantity = order.quantity
    _ = order.customer
    order.customer = customer
    order.quantity = quantity
    order.note = note

    # 明细数量必须跟随订单数量：列表页（贝莱/外包/采购）显示的是 order_item.quantity
    # （_build_beile_order_record 里 record['quantity'] = first_item.quantity），
    # 只改主表会让这些页面永远停在旧数量——实测改 10000→8888 后主表已变、明细仍 10000。
    await sync_single_item_quantity(db, order_id, quantity)

    if quantity != old_quantity:
        # TODO(multi-sku-order): order.product_id 在多 SKU 下为首 item 兼容值，库存调整需按 OrderItem 维度；待后续 spec 改造。
        product_id = order.product_id
        if product_id is None:
            raise ValueError(f'产品ID {product_id} 不存在')
        await get_product_for_update(db, product_id)
        log = InventoryLog(
            product_id=order.product_id,
            change_type='订单修改',
            change_quantity=quantity - old_quantity,
            related_id=order.order_no,
            note=f'订单修改：{order.order_no}'
        )
        db.add(log)

    await db.flush()

    # order.status 是 (抵扣量, 出货量, 数量) 的派生值（见 shared_models/order.py 的
    # compute_status_from_stockouts），数量变了就必须重算 —— 否则订单 100→1000 后
    # 状态仍停在「已备货」而非「部分备货」，状态列与状态筛选一并出错，直到下次
    # 出库/退货/改抵扣事件才被纠正。本模块此前已导入 compute_order_status_from_db
    # 却从未调用，即此处的遗漏。
    order.status = await compute_order_status_from_db(db, order)

    # Task 3.2: 派发工厂通知（order_updated）
    # 仅 flush 不 commit，与 _update_order_directly 事务模型一致；
    # 简单实现：传 changed_items=None，让 dispatch 遍历 order.items（内部 await 查询）。
    # 通知失败不应影响订单修改，捕获异常仅记录日志。
    try:
        await dispatch_factory_notifications(db, order, 'order_updated', None)
    except Exception as notify_err:  # broad-except: 服务层容错，记录异常并返回安全默认值
        logger.warning(
            "工厂通知派发失败 order_no=%s: %s", order.order_no, notify_err,
            exc_info=True,
        )

    await cache_mgr.invalidate(
        InvalidationStrategy.DOMAIN,
        CacheDomain.ORDER_AND_INVENTORY | CacheDomain.REPORT,
    )
    # dashboard 缓存失效已移至 endpoint 层（事务提交后）
    schedule_post_commit_invalidation(db, _invalidate_order_domains)

    await _safe_invalidate_purchase_cache()

    logger.info(f'订单编辑成功：{order.order_no}，操作人：{current_user.username}')

    # 提交后再广播：客户端收到 order_updated 会立刻重取列表，先于提交发出会读到
    # 改数量前的旧数据并缓存该结果，staleTime 内不再回取（表现为页面延迟约 30s）。
    schedule_post_commit_event(db, StockEvent.ORDER_UPDATED, {
        'order_id': order_id,
        'order_no': order.order_no,
        'customer': customer,
        'quantity': quantity,
    })

    return {'success': True, 'message': '订单编辑成功！', 'requires_approval': False}

_DELETE_BATCH_SIZE = 500
_ORDER_BACKUP_SUBDIR = 'order_deletions'


def _order_columns(model_cls) -> list[str]:
    """返回模型表列名（快照序列化使用）。"""
    return [column.name for column in model_cls.__table__.columns]


def _serialize_model_row(row, model_cls) -> dict:
    return {name: getattr(row, name, None) for name in _order_columns(model_cls)}


def _serialize_model_rows(rows, model_cls) -> list[dict]:
    return [_serialize_model_row(row, model_cls) for row in rows]


async def _fetch_model_rows(db: AsyncSession, model_cls, condition) -> list:
    result = await db.execute(select(model_cls).where(condition))
    return list(result.scalars().all())


async def _fetch_by_ids(db: AsyncSession, model_cls, column, ids: list[int]) -> list:
    """按外键 IN 分批取回关联行（空 ids 直接返回，避免无谓查询）。"""
    rows: list = []
    for start in range(0, len(ids), _DELETE_BATCH_SIZE):
        batch = ids[start:start + _DELETE_BATCH_SIZE]
        if batch:
            rows.extend(await _fetch_model_rows(db, model_cls, column.in_(batch)))
    return rows


async def _delete_in_batches(
    db: AsyncSession, model_cls, ids: list[int], column=None,
) -> None:
    """分批删除，避免大量关联记录触发超大 IN 列表或单条逐删。

    ``column`` 缺省按主键 id 删除；传外键列名可按关联键批量删除。
    """
    target = model_cls.id if column is None else column
    for start in range(0, len(ids), _DELETE_BATCH_SIZE):
        batch = ids[start:start + _DELETE_BATCH_SIZE]
        if batch:
            await db.execute(
                delete(model_cls).where(target.in_(batch))
            )  # batch-loop: 分批 IN 删除，非逐行查询


def _order_backup_enabled() -> bool:
    """测试环境不写真实文件，避免污染仓库；生产/开发环境开启删除前备份。"""
    return os.getenv('APP_ENV', '').strip().lower() not in {'test', 'pytest'}


def _order_backup_directory() -> Path:
    from fastapi_app.services.backup._constants import BACKUP_DIR, PROJECT_ROOT
    return PROJECT_ROOT / BACKUP_DIR / _ORDER_BACKUP_SUBDIR


def _write_order_deletion_backup(snapshot: dict) -> str | None:
    """将删除前的订单及关联流程快照写入 JSON 文件，供误删恢复使用。"""
    if not _order_backup_enabled():
        return None
    backup_dir = _order_backup_directory()
    try:
        backup_dir.mkdir(parents=True, exist_ok=True)
        order_no = str(snapshot.get('order_no') or snapshot.get('order_id') or '')
        safe_no = ''.join(ch for ch in order_no if ch.isalnum() or ch in ('-', '_'))
        timestamp = datetime.now(UTC).strftime('%Y%m%d%H%M%S%f')
        path = backup_dir / f'order_{snapshot.get("order_id")}_{safe_no}_{timestamp}.json'
        path.write_text(
            json.dumps(snapshot, ensure_ascii=False, indent=2, default=str),
            encoding='utf-8',
        )
        return str(path)
    except OSError as exc:
        logger.exception('订单删除前备份写入失败')
        raise OSError('订单删除前备份失败，已中止删除操作') from exc


async def _prelock_order_products(
    db: AsyncSession, order_id: int, *extra_pids: int | None,
) -> None:
    """整单产品全集升序预锁（delete_order / delete_order_item 共用锁序）。

    集合 = 无锁读 ``order.product_id`` ∪ 该订单全部出库行 distinct
    ``product_id`` ∪ ``extra_pids``（调用方已知的额外产品，如待删明细的
    product_id——明细可能尚无出库行、order.product_id 可能已迁移，不在
    前两个来源里），过滤 None 后按 id 升序逐行 get_product_for_update。
    订单不存在则前两个来源为空、仅锁 extra（「订单不存在」由调用方按
    原口径抛错，同 update_order 的做法）。

    2026-10-19 OCR 第二轮 M4：delete_order_item 原先只预锁「明细产品+
    兼容产品」两行再锁 Order 行，末项分支进 delete_order 后若全集里存在
    比已持行更小的 id（订单删过明细、stockin_id IS NULL 的 stock_out 挂
    更小 id 产品时可达），会「持大等小」，与并发 delete_order「先拿小
    id 再等大 id」互等死锁。两路径改为共用本函数后持有的集合与顺序
    完全一致，末项分支进入 _load_order_for_delete 的重锁全部为 no-op，
    锁序全程单调。delete_order_item 非末项分支会因此多锁本单其他 SKU
    的产品行（无害：同事务短暂持有），换来两条路径锁序统一。
    """
    order_pid = (await db.execute(
        select(Order.product_id).where(Order.id == order_id)
    )).scalar_one_or_none()
    stockout_pids = (await db.execute(
        select(StockOut.product_id).where(StockOut.order_id == order_id).distinct()
    )).scalars().all()
    for pid in sorted({p for p in (order_pid, *stockout_pids, *extra_pids) if p is not None}):
        await get_product_for_update(db, pid)


async def _load_order_for_delete(db: AsyncSession, order_id: int) -> Order | None:
    """按 delete_order 的锁序加载订单：先升序预锁全部涉及 Product，再锁 Order 行。

    2026-10-18 OCR 评审 P2-07 收尾：上一版用 `db.get(Order, ...)` 无锁读订单 ——
    ① Order 行本身从未加锁，与并发删除构成更新丢失窗口；
    ② `db.get` 走身份映射，本事务先前无锁加载过的 Order 会直接拿到旧对象。

    锁序与 update_order 同构（P→O）：先锁产品行，再 `with_for_update(of=Order)`
    锁订单行。`of=Order` 限定只锁 order 行 —— joinedload 展开的 product 行已由
    上面的产品锁覆盖（同事务重锁无害），不限定则锁范围会带上 join 出来的行，
    并依赖「PG 是否允许 outer join 上裸 FOR UPDATE」这一易变细节。

    2026-10-19 OCR Medium 修复：预锁范围从 order.product_id 单行扩为
    「order.product_id ∪ 该订单全部出库行的 product_id」并**按 id 升序**逐行
    取锁——删除回滚（rollback_order_stock_by_sku）内部同样按升序锁这些行，
    若只预锁 order.product_id 单行，当它不是回滚集合的最小 id 时，两条并发
    删除会以「持 P(order.product_id) 等集合内更小 id 行」互等，构成 AB-BA
    死锁窗口（OCR 例：单 X 的 order.product_id=5、出库 {3,5}；单 Y 的
    order.product_id=3、出库 {3,5}）。集合升序预锁后，回滚内部的重锁全部
    为 no-op，锁序全程单调。

    2026-10-19 OCR 第二轮 M4：预锁段抽为公共 ``_prelock_order_products``，
    与 ``delete_order_item`` 共用同一集合与顺序（该函数原先只预锁两行，
    与本函数的全集锁序构成新的 AB-BA 窗口，详见其 docstring）。

    读不到 product_id（订单不存在）则集合为空、跳过预锁，由调用方按原口径
    抛「订单不存在」——同 update_order 的做法。
    """
    await _prelock_order_products(db, order_id)

    return (await db.execute(
        select(Order)
        .options(joinedload(Order.product))
        .where(Order.id == order_id)
        .with_for_update(of=Order)
    )).scalar_one_or_none()


async def delete_order(db: AsyncSession, order_id: int, current_user: User) -> dict:
    order = await _load_order_for_delete(db, order_id)
    if not order or order.is_deleted:
        raise ValueError('订单不存在')

    await _check_order_lock(db, order_id, order, current_user, '删除')

    # 有退货记录的订单不可删除（迁移 072 RESTRICT 的应用层前置）：
    # 删除会级联物理删 stock_out，撞 RESTRICT 外键；此处前置拒绝并说明原因，
    # 避免退化成正删/审批两条路径都报含糊 409。置于分支前，非超管不会创建注定失败的审批。
    await assert_no_linked_returns(db, order_id)

    if current_user.is_super:
        return await _delete_order_directly(db, order, order_id, current_user)
    else:
        return await _submit_delete_approval(db, order, order_id, current_user)

async def _collect_order_deletion_graph(db: AsyncSession, order: Order, order_id: int) -> dict:
    """收集删除订单需要备份与清理的全部关联行（分批 IN，避免循环单查）。"""
    processes = await _fetch_model_rows(
        db, OrderOutsourceProcess, OrderOutsourceProcess.order_id == order.id,
    )
    process_ids = [p.id for p in processes]
    approvals = await _fetch_model_rows(
        db, ApprovalRequest, ApprovalRequest.order_id == order_id,
    )
    approval_ids = [ar.id for ar in approvals]
    return {
        'processes': processes,
        'process_ids': process_ids,
        'approvals': approvals,
        'approval_ids': approval_ids,
        'flows': await _fetch_by_ids(
            db, OrderOutsourceProcessFlow, OrderOutsourceProcessFlow.process_id, process_ids,
        ),
        'approval_logs': await _fetch_by_ids(
            db, ApprovalLog, ApprovalLog.approval_request_id, approval_ids,
        ),
        'shipment_items': await _fetch_by_ids(
            db, OutsourceShipmentItem, OutsourceShipmentItem.process_id, process_ids,
        ),
        'stockouts': await _fetch_model_rows(db, StockOut, StockOut.order_id == order.id),
        'order_items': await _fetch_model_rows(db, OrderItem, OrderItem.order_id == order.id),
        'sync_records': await _fetch_model_rows(
            db, OrderSyncRecord, OrderSyncRecord.source_order_id == order_id,
        ),
        'retry_records': await _fetch_model_rows(
            db, SyncRetryQueue, SyncRetryQueue.source_order_id == order_id,
        ),
        'status_logs': await _fetch_model_rows(
            db, OrderStatusLog, OrderStatusLog.order_no == order.order_no,
        ),
        'shipments': await _fetch_model_rows(
            db, OutsourceShipment, OutsourceShipment.order_id == order_id,
        ),
        # 该订单同步产生的采购计划明细（分号边界防前缀误伤），供备份与级联清理
        'shipment_plan_details': await _fetch_model_rows(
            db, PurchasePlanDetail,
            or_(
                PurchasePlanDetail.remark == f'来源订单:{order.order_no}',
                PurchasePlanDetail.remark.like(f'来源订单:{escape_like(order.order_no)}；%'),
            ),
        ),
    }


def _order_deletion_flow_count(graph: dict) -> int:
    """备份快照记录的「关联流程」条数（与历史口径一致）。"""
    return (
        len(graph['processes'])
        + len(graph['flows'])
        + len(graph['approvals'])
        + len(graph['approval_logs'])
        + len(graph['status_logs'])
        + len(graph['retry_records'])
    )


def _order_deletion_backup_payload(
    order: Order, order_id: int, current_user: User, graph: dict, flow_count: int,
) -> dict:
    """构造删除前备份快照（字段与历史实现一致，含误删恢复所需全部关联行）。"""
    return {
        'schema_version': 1,
        'deleted_at': datetime.now(UTC).isoformat(),
        'operator': {
            'id': current_user.id,
            'username': current_user.username,
        },
        'order_id': order_id,
        'order_no': order.order_no,
        'flow_count': flow_count,
        'order': _serialize_model_row(order, Order),
        'order_items': _serialize_model_rows(graph['order_items'], OrderItem),
        'stockouts': _serialize_model_rows(graph['stockouts'], StockOut),
        'outsource_processes': _serialize_model_rows(graph['processes'], OrderOutsourceProcess),
        'outsource_process_flows': _serialize_model_rows(graph['flows'], OrderOutsourceProcessFlow),
        'approval_requests': _serialize_model_rows(graph['approvals'], ApprovalRequest),
        'approval_logs': _serialize_model_rows(graph['approval_logs'], ApprovalLog),
        'order_sync_records': _serialize_model_rows(graph['sync_records'], OrderSyncRecord),
        'sync_retry_queue': _serialize_model_rows(graph['retry_records'], SyncRetryQueue),
        'order_status_logs': _serialize_model_rows(graph['status_logs'], OrderStatusLog),
        'outsource_shipments': _serialize_model_rows(graph['shipments'], OutsourceShipment),
        'outsource_shipment_items': _serialize_model_rows(graph['shipment_items'], OutsourceShipmentItem),
        'shipment_plan_details': _serialize_model_rows(graph['shipment_plan_details'], PurchasePlanDetail),
    }



async def _purge_outsource_processes(db: AsyncSession, process_ids: list[int]) -> None:
    """解绑出货明细、删除工序流转与工序本身（分批 IN，避免超大 IN 列表）。"""
    if not process_ids:
        return
    for start in range(0, len(process_ids), _DELETE_BATCH_SIZE):
        batch = process_ids[start:start + _DELETE_BATCH_SIZE]
        await db.execute(
            update(OutsourceShipmentItem)
            .where(OutsourceShipmentItem.process_id.in_(batch))
            .values(process_id=None)
        )  # batch-loop: 分批 IN 解绑，非逐行查询
    for start in range(0, len(process_ids), _DELETE_BATCH_SIZE):
        batch = process_ids[start:start + _DELETE_BATCH_SIZE]
        await db.execute(
            delete(OrderOutsourceProcessFlow)
            .where(OrderOutsourceProcessFlow.process_id.in_(batch))
        )  # batch-loop: 分批 IN 删除，非逐行查询
    await _delete_in_batches(db, OrderOutsourceProcess, process_ids)


async def _purge_order_related_rows(
    db: AsyncSession, order: Order, order_id: int, graph: dict,
) -> dict:
    """删除/解绑订单的全部关联记录（出库、同步、审批、工序、状态日志、明细）。

    返回出货计划级联清理结果（供删除消息透出）。
    """
    # 先解除已取消退货对外键的引用（否则 RESTRICT 外键挡住下面的 stock_out 删除）；
    # active 退货已在 delete_order 入口的 assert_no_linked_returns 处被拒。
    await detach_cancelled_returns_for_order(db, order.id)
    await db.execute(delete(StockOut).where(StockOut.order_id == order.id))
    await db.execute(delete(OrderSyncRecord).where(OrderSyncRecord.source_order_id == order_id))
    await db.execute(delete(SyncRetryQueue).where(SyncRetryQueue.source_order_id == order_id))
    await _delete_in_batches(db, ApprovalLog, graph['approval_ids'], ApprovalLog.approval_request_id)
    await db.execute(delete(ApprovalRequest).where(ApprovalRequest.order_id == order_id))
    await _purge_outsource_processes(db, graph['process_ids'])
    await db.execute(update(OutsourceShipment).where(OutsourceShipment.order_id == order_id).values(order_id=None))
    await db.execute(delete(OrderStatusLog).where(OrderStatusLog.order_no == order.order_no))
    await db.execute(delete(OrderItem).where(OrderItem.order_id == order.id))
    # 级联清理该订单同步产生的采购计划明细（2026-10-06 删除联动）：
    # 否则订单删了、月历上的计划明细残留，与"订单与计划同生共死"的创建语义不对称
    from fastapi_app.services.shipment_plan_sync import purge_shipment_plan_details_for_order
    return await purge_shipment_plan_details_for_order(db, order.order_no)


async def _delete_order_directly(
    db: AsyncSession, order: Order, order_id: int, current_user: User,
) -> dict:
    # 2026-10-19 OCR Medium 收敛：本函数不再预锁 order.product_id 单行——该锁
    # 与共享回滚的升序锁序构成 AB-BA 死锁窗口，且其返回值自 P0-1 起只是死参数。
    # 产品行锁全部由唯一调用链 delete_order → _load_order_for_delete 以
    # 「集合升序预锁」承担（见该函数 docstring）；rollback_order_stock_by_sku
    # 内部的重锁为 no-op。注意：Order 行的锁由 delete_order 入口负责；单独调
    # 本函数不等于锁全链路。
    graph = await _collect_order_deletion_graph(db, order, order_id)
    order_stockouts = graph['stockouts']
    flow_count = _order_deletion_flow_count(graph)


    backup_path = _write_order_deletion_backup(
        _order_deletion_backup_payload(order, order_id, current_user, graph, flow_count),
    )

    # 2026-10-19 OCR 第三轮 M3：接收**实际回滚量**（正组求和、跳过缺失产品后的
    # 落账值），下方日志与用户消息改用之——total_deducted 只是「全部出库行净量
    # 之和」，含负组/缺失 SKU 组时与实际回滚量发散（审批路径 _handle_delete_approval
    # 在任务 #27 已同样修过，此处对齐口径）。
    total_rolled_back = await rollback_order_stock_by_sku(db, order, order_stockouts)

    plan_purge = await _purge_order_related_rows(db, order, order_id, graph)

    db.add(AuditLog(
        user_id=current_user.id,
        username=current_user.username,
        action='DELETE',
        resource_type='order',
        resource_id=order.order_no,
        detail=json.dumps({
            'order_id': order_id,
            'order_no': order.order_no,
            'flow_count': flow_count,
            'backup_path': backup_path,
        }, ensure_ascii=False),
        status_code=200,
    ))

    deleted_order_no = order.order_no
    order.is_deleted = True
    order.deleted_at = datetime.now(UTC).replace(tzinfo=None)  # naive UTC: DB列类型为 TIMESTAMP WITHOUT TIME ZONE
    order.deleted_by_id = current_user.id

    await db.flush()
    try:
        # 删除后订单不再计入库存视图（order_agg 过滤 is_deleted），
        # 必须一并失效 INVENTORY 域，否则 /stock 在 TTL 内仍显示已删订单的数量。
        await cache_mgr.invalidate(
            InvalidationStrategy.DOMAIN,
            CacheDomain.ORDER_AND_INVENTORY | CacheDomain.REPORT)
        # dashboard 缓存失效已移至 endpoint 层（事务提交后）
    except INFRA_EXCEPTIONS as e:
        logger.warning('缓存清除失败: %s', e)

    schedule_post_commit_invalidation(db, _invalidate_order_domains)

    await _safe_invalidate_purchase_cache()

    # 提交后再广播（见端点说明）：先发事件会让客户端重取到删除前的旧数据并缓存
    schedule_post_commit_event(db, StockEvent.ORDER_DELETED, {
        'order_id': order_id,
        'order_no': deleted_order_no,
    })

    logger.info(
        '订单删除成功：%s，操作人：%s，抵扣回滚：%s，级联流程清理：%s，出货计划明细清理：%s，备份：%s',
        deleted_order_no, current_user.username, total_rolled_back, flow_count,
        plan_purge.get('detail_deleted', 0) if plan_purge else 0, backup_path,
    )
    message = f'订单删除成功！已级联清理 {flow_count} 条关联流程记录，抵扣回滚数量：{total_rolled_back}'
    if plan_purge and plan_purge.get('detail_deleted'):
        message += f"，同步移除出货计划明细 {plan_purge['detail_deleted']} 条"
    return {
        'success': True,
        'message': message,
        'requires_approval': False,
    }
