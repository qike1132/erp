"""
采购订单 CRUD 操作

职责：采购订单的创建、更新、删除、完成、清理等写操作。
从 purchase_order_service.py 拆分而来，保持函数签名不变。
"""
import json
import logging
from collections import defaultdict
from collections.abc import Sequence
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from fastapi_app.services.numbering import generate_purchase_order_number
from fastapi_app.shared_models import (
    MaterialRegistration,
    MaterialRegistrationItem,
    ModificationLog,
    PurchaseOrder,
    PurchaseOrderItem,
    PurchaseOrderStatus,
)

logger = logging.getLogger(__name__)


def _scope_remark(source_role: str | None) -> str:
    """把来源 BOM 作用域转成明细备注；无来源时返回空串（保持旧行为）。"""
    return f'来源BOM：{source_role}' if source_role else ''


async def _create_material_registration(
    db: AsyncSession, order: PurchaseOrder, items: Sequence[PurchaseOrderItem],
) -> MaterialRegistration:
    """创建来料登记及其明细行（由调用方负责最终 flush/commit）。"""
    registration = MaterialRegistration(
        purchase_order_id=order.id,
        purchase_order_no=order.order_no,
        supplier_id=order.supplier_id,
        supplier_name=order.supplier_name or '',
        registration_date=datetime.now(UTC).replace(tzinfo=None).date(),
        remark='',
        status='pending',
    )
    db.add(registration)
    await db.flush()

    for item in items:
        db.add(MaterialRegistrationItem(
            registration_id=registration.id,
            order_item_id=item.id,
            material_code=item.material_code or '',
            material_name=item.material_name,
            specification=item.specification or '',
            unit=item.unit or '',
            ordered_quantity=item.quantity,
            received_quantity=0,
            material_category=item.material_category or '',
            remark=item.remark or '',
        ))
    return registration


async def create_purchase_order(db: AsyncSession, data: dict, include_summary: bool = False, _auto_commit: bool = True) -> dict:
    items = data.get('items', [])
    if not items:
        raise ValueError('采购订单至少需要一条明细')

    order_no = await generate_purchase_order_number(db)
    supplier_name = items[0].get('supplier_name', '')
    supplier_id = items[0].get('supplier_id')
    customer_name = data.get('customer_name', items[0].get('customer_name', ''))

    order = PurchaseOrder(
        order_no=order_no,
        supplier_name=supplier_name,
        supplier_id=supplier_id,
        customer_name=customer_name,
        status=PurchaseOrderStatus.PENDING,
        remark=data.get('note', ''),
        source_order_ids=data.get('source_order_ids'),
        product_name=data.get('product_name'),
        product_quantity=data.get('product_quantity'),
    )
    db.add(order)
    try:
        async with db.begin_nested():  # savepoint：仅回滚到此处，不破坏外层事务
            await db.flush()
    except IntegrityError as err:
        # uq_po_pending_dedup 冲突需要由端点层做幂等回查，不应本地重试
        if 'uq_po_pending_dedup' in str(getattr(err, 'orig', err)):
            raise
        # 并发时 order_no 可能重复，重新生成编号后再 flush
        order_no = await generate_purchase_order_number(db)
        order.order_no = order_no
        await db.flush()

    total_amount = Decimal('0')
    for item_data in items:
        material_name = item_data.get('material_name', '')
        unit_price = Decimal(str(item_data.get('unit_price', 0)))
        quantity = Decimal(str(item_data.get('quantity', 0)))
        amount = unit_price * quantity

        poi = PurchaseOrderItem(
            order_id=order.id,
            material_name=material_name,
            material_code=item_data.get('material_code', ''),
            specification=item_data.get('specification', ''),
            unit=item_data.get('unit', ''),
            unit_price=unit_price,
            quantity=quantity,
            total_price=amount,
            supplier_name=item_data.get('supplier_name') or supplier_name,
            customer_name=customer_name,
            material_category=item_data.get('category', ''),
            # 来源 BOM 作用域（默认BOM / 各角色）：写进备注，采购员能看出这条需求由谁产生。
            # 无 source_role（如手工单、旧路径）时保持 remark 原样，不产生多余文本。
            remark=item_data.get('remark') or _scope_remark(item_data.get('source_role')),
        )
        db.add(poi)
        total_amount += amount

    order.total_amount = total_amount
    await db.flush()

    result = {'order_no': order_no, 'id': order.id, 'total_amount': float(total_amount)}

    if include_summary:
        result['summary'] = await _build_order_summary(db, order)

    return result


def _apply_order_field_updates(order: PurchaseOrder, data: dict) -> None:
    """根据 data 字典更新订单的可变字段。"""
    if 'customer_name' in data:
        order.customer_name = data['customer_name']
    if 'supplier_name' in data:
        order.supplier_name = data['supplier_name']
    if 'note' in data:
        order.remark = data['note']
    if 'status' in data:
        order.status = data['status']


def _apply_item_fields(item: PurchaseOrderItem, item_data: dict, order: PurchaseOrder) -> None:
    """将 item_data 中的字段写入明细对象。"""
    item.material_name = item_data.get('material_name', '')
    item.material_code = item_data.get('material_code', '')
    item.specification = item_data.get('specification', '')
    item.unit = item_data.get('unit', '')
    item.unit_price = Decimal(str(item_data.get('unit_price', 0)))
    item.quantity = Decimal(str(item_data.get('quantity', 0)))
    item.total_price = item.unit_price * item.quantity
    item.material_category = item_data.get('category', '')
    item.remark = item_data.get('remark') or _scope_remark(item_data.get('source_role'))
    item.supplier_name = order.supplier_name
    item.customer_name = order.customer_name


async def _upsert_order_items(
    db: AsyncSession, order: PurchaseOrder, order_id: int, items_data: list
) -> None:
    """批量预取并 upsert 订单明细，返回 None（直接修改 order.total_amount）。"""
    existing_items_result = await db.execute(
        select(PurchaseOrderItem).where(PurchaseOrderItem.order_id == order_id)
    )
    existing_items = {item.id for item in existing_items_result.scalars().all()}

    total_amount = Decimal('0')
    updated_ids = set()

    # 批量预取待更新的明细，避免循环内逐条 db.get 产生 N+1 查询
    item_ids_to_fetch = [d.get('id') for d in items_data if d.get('id')]
    fetched_items_map = {}
    if item_ids_to_fetch:
        fetched_result = await db.execute(
            select(PurchaseOrderItem).where(PurchaseOrderItem.id.in_(item_ids_to_fetch))
        )
        fetched_items_map = {i.id: i for i in fetched_result.scalars().all()}

    for item_data in items_data:
        item_id = item_data.get('id')
        if item_id:
            item = fetched_items_map.get(item_id)
            # 批量预取缺失或跨订单的 id：回退到逐条查询，保持原 db.get 语义
            if item is None or item.order_id != order_id:
                item = await db.get(PurchaseOrderItem, item_id)
            if item is not None and item.order_id == order_id:
                updated_ids.add(item_id)
            else:
                # 关键修复：item 不存在或属于其他订单时置 None，防止后续 _apply_item_fields
                # 误写入其他订单的明细对象，导致跨订单数据篡改和 total_amount 计算错误。
                item = None
        else:
            item = PurchaseOrderItem(order_id=order_id)

        if item is None:
            # id 无效（已被删除、不存在，或属于其他订单）：跳过，避免跨订单写入
            continue

        _apply_item_fields(item, item_data, order)

        if not item_id:
            db.add(item)
        total_amount += item.total_price

    to_delete_ids = existing_items - updated_ids
    if to_delete_ids:
        await db.execute(
            delete(PurchaseOrderItem).where(PurchaseOrderItem.id.in_(to_delete_ids))
        )

    order.total_amount = total_amount


async def update_purchase_order(db: AsyncSession, order_id: int, data: dict, username: str = 'unknown') -> dict:
    order = await db.get(PurchaseOrder, order_id)
    if not order:
        raise ValueError('采购订单不存在')

    _apply_order_field_updates(order, data)

    items_data = data.get('items')
    if items_data is not None:
        await _upsert_order_items(db, order, order_id, items_data)

    await db.flush()

    db.add(ModificationLog(
        target_type='purchase_order',
        target_id=order_id,
        field_name='update',
        old_value=f'订单{order.order_no}已更新',
        new_value=json.dumps({
            'status': order.status,
            'total_amount': float(order.total_amount or 0),
        }, ensure_ascii=False),
        modifier_name=username,
    ))

    return {'id': order.id, 'order_no': order.order_no, 'status': order.status}


async def delete_purchase_order(db: AsyncSession, order_id: int) -> dict:
    order = await db.get(PurchaseOrder, order_id)
    if not order:
        raise ValueError('采购订单不存在')

    # 批量删除明细（单条 DELETE ... WHERE 语句），替代逐条 db.delete 的 N+1；
    # order.items 关系为 lazy='raise'，不做集合赋空，后续 delete(order)+flush 不再访问该集合
    await db.execute(
        delete(PurchaseOrderItem).where(PurchaseOrderItem.order_id == order_id)
    )

    await db.delete(order)
    await db.flush()
    return {'id': order_id, 'order_no': order.order_no}


async def complete_purchase_order(db: AsyncSession, order_id: int, username: str = 'unknown') -> dict:
    order = await db.get(PurchaseOrder, order_id)
    if not order:
        raise ValueError('采购订单不存在')
    if order.status not in ('pending', 'confirmed'):
        raise ValueError(f'订单{order.order_no}状态不允许完成')

    items_result = await db.execute(
        select(PurchaseOrderItem).where(PurchaseOrderItem.order_id == order_id)
    )
    items = items_result.scalars().all()

    now = datetime.now(UTC).replace(tzinfo=None)

    await _create_material_registration(db, order, items)

    for item in items:
        db.add(ModificationLog(
            target_type='purchase_item',
            target_id=item.id,
            field_name='completion',
            old_value=f'{item.material_name}(待完成)',
            new_value=json.dumps({
                'ordered_qty': str(float(item.quantity or 0)),
                'received_qty': '0',
            }, ensure_ascii=False),
            modifier_name=username,
        ))

    order.status = PurchaseOrderStatus.COMPLETED
    order.completed_at = now
    await db.flush()
    return {'id': order.id, 'order_no': order.order_no, 'status': 'completed'}


async def batch_complete_purchase_orders(db: AsyncSession, order_ids: list, username: str = 'unknown') -> dict:
    """
    批量完成采购订单并登记来料。

    优化：一次查询获取所有订单，避免 N+1。
    """
    if not order_ids:
        raise ValueError('请选择要完成的订单')

    result = await db.execute(
        select(PurchaseOrder).where(PurchaseOrder.id.in_(order_ids))
    )
    orders = {o.id: o for o in result.scalars().all()}

    # 批量查询所有订单项，避免 N+1
    all_items_result = await db.execute(
        select(PurchaseOrderItem).where(PurchaseOrderItem.order_id.in_(order_ids))
    )
    items_by_order: dict[int, list] = {}
    for item in all_items_result.scalars().all():
        items_by_order.setdefault(item.order_id, []).append(item)

    completed = 0
    errors = []
    now = datetime.now(UTC).replace(tzinfo=None)

    for oid in order_ids:
        try:
            order = orders.get(oid)
            if not order:
                errors.append(f'订单{oid}不存在')
                continue
            if order.status not in ('pending', 'confirmed'):
                errors.append(f'订单{order.order_no}状态不允许完成')
                continue

            items = items_by_order.get(oid, [])

            await _create_material_registration(db, order, items)

            order.status = PurchaseOrderStatus.COMPLETED
            order.completed_at = now
            completed += 1
        except (ValueError, TypeError) as e:
            errors.append(f'订单处理失败: {e!s}')

    await db.flush()
    return {'completed': completed, 'errors': errors}


async def save_factory_summary_edits(
    db: AsyncSession, data: list, username: str = 'unknown',
) -> dict:
    updated = 0
    for entry in data:
        item_ids = entry.get('item_ids', [])
        new_quantity = entry.get('quantity')
        if not item_ids or new_quantity is None:
            continue

        items = []
        if item_ids:
            # 批量预取明细，避免循环内逐条 db.get 产生 N+1 查询
            fetched_result = await db.execute(  # batch-loop: 有意逐行处理,非 N+1
                select(PurchaseOrderItem).where(PurchaseOrderItem.id.in_(item_ids))
            )
            fetched_map = {i.id: i for i in fetched_result.scalars().all()}
            items = [fetched_map[iid] for iid in item_ids if iid in fetched_map]

        if not items:
            continue

        if len(items) == 1:
            items[0].quantity = Decimal(str(new_quantity))
            items[0].total_price = (items[0].unit_price or 0) * items[0].quantity
            updated += 1
        else:
            original_total = sum(float(it.quantity or 0) for it in items)
            if original_total > 0:
                ratio = float(new_quantity) / original_total
                for it in items:
                    it.quantity = Decimal(str(round(float(it.quantity or 0) * ratio, 2)))
                    it.total_price = (it.unit_price or 0) * it.quantity
                    updated += 1
            else:
                per_item = Decimal(str(round(float(new_quantity) / len(items), 2)))
                for it in items:
                    it.quantity = per_item
                    it.total_price = (it.unit_price or 0) * it.quantity
                    updated += 1

    await db.flush()
    return {'updated_count': updated}


async def _build_order_summary(db: AsyncSession, order) -> dict:
    """构建订单汇总信息"""
    total_items = 0
    total_quantity = 0
    categories: dict[str, int] = defaultdict(int)

    items_result = await db.execute(
        select(PurchaseOrderItem).where(PurchaseOrderItem.order_id == order.id)
    )
    for item in items_result.scalars().all():
        total_items += 1
        total_quantity += int(item.quantity or 0)
        cat = item.material_category or 'other'
        categories[cat] += 1

    return {
        'order_no': order.order_no,
        'total_items': total_items,
        'total_quantity': total_quantity,
        'categories': dict(categories),
        'total_amount': float(order.total_amount or 0),
    }


async def cleanup_orphan_pending_purchase_orders(
    db: AsyncSession, order_ids: list[int] | None = None,
    stockin_ids: list[int] | None = None,
    exclude_ids: list[int] | None = None,
) -> int:
    """清理关联指定客户订单 / 备货记录的 pending 采购订单。

    同时处理 source_order_id（单 ID 列）和 source_order_ids（JSON 数组）两个字段。
    返回被删除的采购订单数量，供调用方判断是否触发了清理。

    修复点：
    - 接受 order_ids + stockin_ids 两个来源，确保"一键审核"对两类来源都能去重
    - 仅依赖 JSON 解析后的命中列表，不再使用未消费的 all_ids 变量
    - 移除原先同时处理 customer / source_order_id 时的语义混淆
    """
    source_ids: list[int] = []
    if order_ids:
        source_ids.extend(order_ids)
    if stockin_ids:
        source_ids.extend(stockin_ids)
    if not source_ids:
        return 0

    _exclude = set(exclude_ids or [])

    # 1) 找出所有 source_order_ids JSON 数组中包含目标 ID 的 PurchaseOrder.id
    result2 = await db.execute(
        select(PurchaseOrder.id, PurchaseOrder.source_order_ids).where(
            PurchaseOrder.source_order_ids.isnot(None),
            PurchaseOrder.status == PurchaseOrderStatus.PENDING,
        )
    )
    json_match_ids: list[int] = []
    for row in result2.all():
        try:
            ids = json.loads(row.source_order_ids)
        except (ValueError, TypeError):
            logger.warning('PurchaseOrder %s has invalid source_order_ids: %s', row.id, row.source_order_ids)
            continue
        if any(i in source_ids for i in ids):
            json_match_ids.append(row.id)

    # 2) 合并匹配：source_order_id 列直接命中 + JSON 数组命中
    result = await db.execute(
        select(PurchaseOrder).where(
            PurchaseOrder.status == PurchaseOrderStatus.PENDING,
            (
                PurchaseOrder.source_order_id.in_(source_ids)
            ) | (
                PurchaseOrder.id.in_(json_match_ids)
            ),
        )
    )
    deleted = 0
    for po in result.scalars().all():
        if po.id in _exclude:
            continue
        await db.delete(po)
        deleted += 1
    if deleted:
        logger.info(
            'cleanup_orphan_pending_purchase_orders: 清理 %d 个 pending 采购单 (source_ids=%s)',
            deleted, source_ids,
        )
    return deleted
