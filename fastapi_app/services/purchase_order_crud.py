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
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from fastapi_app.core.exceptions import ConflictError
from fastapi_app.core.float_utils import round_qty
from fastapi_app.services.numbering import generate_purchase_order_number
from fastapi_app.services.purchase_order_sku import resync_po_sku_spare
from fastapi_app.services.purchase_utils import (
    calc_spare_quantity,
    magnified_purchase_qty,
    normalize_spare_rate,
    resolve_item_loss_rate,
)
from fastapi_app.shared_models import (
    MaterialRegistration,
    MaterialRegistrationItem,
    ModificationLog,
    PurchaseOrder,
    PurchaseOrderItem,
    PurchaseOrderSku,
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


async def create_purchase_order(db: AsyncSession, data: dict, include_summary: bool = False) -> dict:
    # P1（2026-10-24）：端点 schema 的字段名是 materials/remark（purchase_center/schemas.py），
    # 而本函数原先只读 items/note，pydantic 忽略多余字段 → POST /purchase-center/orders
    # 恒 400「至少需要一条明细」。两种键名都接受，兼容脚本/旧调用方。
    items = data.get('materials') or data.get('items') or []
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
        remark=data.get('remark') or data.get('note', ''),
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
        status_value = data['status']
        # P1-16：schema 层已校验，这里兜内部调用方（服务层直通曾让任意字符串入库）。
        if status_value is not None and status_value not in PurchaseOrderStatus.ALL:
            raise ValueError(
                f'非法采购订单状态: {status_value!r}（允许: {", ".join(PurchaseOrderStatus.ALL)}）'
            )
        if status_value is not None:
            order.status = status_value


def _recalc_item_total_price(item: PurchaseOrderItem, order_spare_rate: float | None) -> None:
    """按当前（数量, 损耗率）重算该行金额。

    计价数量 = 落库数量按有效损耗率加放（不取整），与前端「金额」列同口径：
    前端 ``useOrderItemPrices.lineAmount`` 用同一公式，两边必须一起改，否则
    页面上「数量 × 单价 ≠ 金额」，且采购单总金额会低于实际采购额。

    结果按落库列的精度（Numeric(12,2)）**先对齐再写**：PG 落库时把多出的小数位
    按「逢五进位」截到 2 位，内存里若保留 3 位，内存合计与落库合计就会差分
    （对账不平）。``ROUND_HALF_UP`` 与 PG numeric 的取整方向一致 —— Python 默认的
    ``ROUND_HALF_EVEN``（逢五取偶）与 PG 不同，会差 0.01。
    """
    rate = resolve_item_loss_rate(item.loss_rate, order_spare_rate)
    total = (item.unit_price or Decimal('0')) * magnified_purchase_qty(item.quantity, rate)
    item.total_price = total.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)


def _apply_item_fields(item: PurchaseOrderItem, item_data: dict, order: PurchaseOrder) -> Decimal:
    """将 item_data 中的字段写入明细对象，返回本行总价（运行期恒为 Decimal）。"""
    item.material_name = item_data.get('material_name', '')
    item.material_code = item_data.get('material_code', '')
    item.specification = item_data.get('specification', '')
    item.unit = item_data.get('unit', '')
    item.unit_price = Decimal(str(item_data.get('unit_price', 0)))
    item.quantity = Decimal(str(item_data.get('quantity', 0)))
    _recalc_item_total_price(item, order.spare_rate)
    line_total = item.total_price or Decimal('0')
    item.material_category = item_data.get('category', '')
    item.remark = item_data.get('remark') or _scope_remark(item_data.get('source_role'))
    item.supplier_name = order.supplier_name
    item.customer_name = order.customer_name
    return line_total


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

        line_total = _apply_item_fields(item, item_data, order)

        if not item_id:
            db.add(item)
        total_amount += line_total

    to_delete_ids = existing_items - updated_ids
    if to_delete_ids:
        await db.execute(
            delete(PurchaseOrderItem).where(PurchaseOrderItem.id.in_(to_delete_ids))
        )

    order.total_amount = total_amount


async def _update_item_prices(
    db: AsyncSession, order: PurchaseOrder, order_id: int, price_entries: list,
) -> None:
    """按明细 id 补录单价，并重算行金额与订单总金额。

    一键生成路径把 unit_price 写死 0（BOM 里没有价格来源），而更新请求原本
    不带 items 字段 → 采购单价生成后**没有任何入口**可改，采购单金额恒为 0，
    供应商金额汇总（``SUM(purchase_order.total_amount)``）因此恒为 0。

    只改单价：不动数量/物料，也不删行——与 ``_upsert_order_items`` 的
    「未提交的明细视为删除」语义区分开，避免只补录价格时误删其它行。
    """
    # 先落库：同一次请求里若还带了 items（upsert 新增的明细尚未 flush），
    # 不 flush 就查不到那些新行，订单总金额会漏算。
    await db.flush()

    items_result = await db.execute(
        select(PurchaseOrderItem).where(PurchaseOrderItem.order_id == order_id)
    )
    items = {item.id: item for item in items_result.scalars().all()}

    seen: set[int] = set()
    for entry in price_entries:
        item_id = entry['id']
        price = Decimal(str(entry['unit_price'])).quantize(Decimal('0.01'))
        if item_id in seen:
            raise ValueError(f'采购明细 {item_id} 重复提交单价')
        seen.add(item_id)
        if price < 0:
            raise ValueError('单价不能为负数')
        item = items.get(item_id)
        if item is None:
            raise ValueError(f'采购明细 {item_id} 不存在或不属于该采购单')
        item.unit_price = price
        _recalc_item_total_price(item, order.spare_rate)

    order.total_amount = sum(
        (item.total_price or Decimal('0') for item in items.values()), Decimal('0')
    )


async def update_purchase_order(db: AsyncSession, order_id: int, data: dict, username: str = 'unknown') -> dict:
    # 行锁（2026-10-24）。不加锁时的丢更新：
    #   A 改明细1单价、B 改明细2单价，两人几乎同时进来
    #   → 各自 SELECT 到「1=0, 2=0」的快照 → A 算出总额 100、B 算出总额 200
    #   → 两次 UPDATE purchase_order.total_amount，后提交者覆盖前者
    #   → 最终明细合计 300，订单总额 200；DB 没有「总额 = Σ明细」约束，差额永久存在。
    # 锁住订单行后，B 会等 A 提交，重新读到的快照已含 A 的改动，总额自然对得上。
    # 实现用 Session.get(with_for_update=True) 而不是另起一条 select(...).with_for_update()：
    # 语义相同（都发 SELECT ... FOR UPDATE），但调用形状与原先的 db.get 完全一致，
    # 不会给「按 db.execute 调用次数编排」的既有 mock 用例多插一次查询。
    order = await db.get(PurchaseOrder, order_id, with_for_update=True)
    if not order:
        raise ValueError('采购订单不存在')

    _apply_order_field_updates(order, data)

    items_data = data.get('items')
    if items_data is not None:
        await _upsert_order_items(db, order, order_id, items_data)

    price_entries = data.get('item_prices')
    if price_entries:
        await _update_item_prices(db, order, order_id, price_entries)

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

    # 来料登记 FK 为 NO ACTION 且订单号列 NOT NULL：有登记时删除必抛 IntegrityError（500）。
    # 必须在删明细之前拦截，否则明细删除先被 MaterialRegistrationItem 的 FK 挡住。
    has_registration = (await db.execute(
        select(MaterialRegistration.id)
        .where(MaterialRegistration.purchase_order_id == order_id)
        .limit(1)
    )).scalar_one_or_none()
    if has_registration is not None:
        raise ConflictError(f'采购单{order.order_no}存在来料登记，无法删除')

    try:
        # 批量删除明细（单条 DELETE ... WHERE 语句），替代逐条 db.delete 的 N+1；
        # order.items 关系为 lazy='raise'，不做集合赋空，后续 delete(order)+flush 不再访问该集合
        await db.execute(
            delete(PurchaseOrderItem).where(PurchaseOrderItem.order_id == order_id)
        )
        # 逐 SKU 数量快照（方案 C）同样以单条 DELETE 显式清理：
        # order.skus 关系为 lazy='raise'，显式删除可避免依赖 ORM 级联时对集合的惰性加载，
        # 且在未开启外键约束的 SQLite（测试）下也能保证无残留孤儿行。
        await db.execute(
            delete(PurchaseOrderSku).where(PurchaseOrderSku.po_id == order_id)
        )

        await db.delete(order)
        await db.flush()
    except IntegrityError as e:
        raise ConflictError(f'采购单{order.order_no}被来料登记等记录引用，无法删除') from e
    return {'id': order_id, 'order_no': order.order_no}


def _apply_spare_rate(order: PurchaseOrder, spare_rate: float | None) -> None:
    """按损耗率覆盖写采购单备品：率归一化后写回，备品按该单产品数量重算。

    仅在 `spare_rate` 非 None 时调用（None 语义为「不覆盖已存值」，见 PRD Q1）。
    """
    order.spare_rate = normalize_spare_rate(spare_rate)
    order.spare_quantity = calc_spare_quantity(order.product_quantity, order.spare_rate)


async def _write_spare_rate_to_orders(
    db: AsyncSession, order_ids: list[int], spare_rate: float | None,
) -> int:
    """批量取回涉及的采购单并覆盖写损耗率 / 备品。

    单次 ``WHERE id IN (...)`` 取回，避免循环内逐单查询（N+1）。
    返回被写入的采购单数量；`spare_rate` 为 None 时直接跳过（不覆盖）。
    """
    if spare_rate is None:
        return 0
    unique_ids = [oid for oid in dict.fromkeys(order_ids) if oid]
    if not unique_ids:
        return 0
    result = await db.execute(select(PurchaseOrder).where(PurchaseOrder.id.in_(unique_ids)))
    written = 0
    applied_ids: list[int] = []
    for order in result.scalars().all():
        _apply_spare_rate(order, spare_rate)
        applied_ids.append(order.id)
        written += 1
    # 逐 SKU 快照的备品按新率同步重算（保持逐 SKU 行与主表备品口径一致）
    await resync_po_sku_spare(db, applied_ids, spare_rate)
    return written


async def complete_purchase_order(
    db: AsyncSession, order_id: int, username: str = 'unknown', spare_rate: float | None = None,
) -> dict:
    order = await db.get(PurchaseOrder, order_id)
    if not order:
        raise ValueError('采购订单不存在')
    if order.status not in (PurchaseOrderStatus.PENDING, PurchaseOrderStatus.CONFIRMED):
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
    # 携带损耗率则覆盖写备品；None 时保留该单已存值（PRD Q1）
    if spare_rate is not None:
        _apply_spare_rate(order, spare_rate)
        # 逐 SKU 快照的备品按新率同步重算（保持逐 SKU 行与主表备品口径一致）
        await resync_po_sku_spare(db, [order.id], spare_rate)
        # 订单级损耗率是明细有效损耗率的回退源 → 该单行金额与总金额同步重算，
        # 否则「完成时改了损耗率、金额却还是旧口径」。
        await _recalc_orders_amount(db, {order.id})
    await db.flush()
    return {'id': order.id, 'order_no': order.order_no, 'status': 'completed'}


async def batch_complete_purchase_orders(
    db: AsyncSession, order_ids: list, username: str = 'unknown', spare_rate: float | None = None,
) -> dict:
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
    resync_ids: list[int] = []
    now = datetime.now(UTC).replace(tzinfo=None)

    for oid in order_ids:
        try:
            order = orders.get(oid)
            if not order:
                errors.append(f'订单{oid}不存在')
                continue
            if order.status not in (PurchaseOrderStatus.PENDING, PurchaseOrderStatus.CONFIRMED):
                errors.append(f'订单{order.order_no}状态不允许完成')
                continue

            items = items_by_order.get(oid, [])

            await _create_material_registration(db, order, items)

            order.status = PurchaseOrderStatus.COMPLETED
            order.completed_at = now
            # 携带损耗率则对该单覆盖写备品（沿用批量取回的 orders，无新增逐单查询）
            if spare_rate is not None:
                _apply_spare_rate(order, spare_rate)
                resync_ids.append(order.id)
            completed += 1
        except (ValueError, TypeError) as e:
            errors.append(f'订单处理失败: {e!s}')

    # 逐 SKU 快照的备品按新率批量同步重算（一次查询，无 N+1）
    if resync_ids:
        await resync_po_sku_spare(db, resync_ids, spare_rate)
        # 订单级损耗率变了 → 这些单的行金额与总金额同步重算（口径同单张完成）
        await _recalc_orders_amount(db, set(resync_ids))

    await db.flush()
    return {'completed': completed, 'errors': errors}


async def save_factory_summary_edits(
    db: AsyncSession, data: list, username: str = 'unknown',
    spare_rate: float | None = None, order_ids: list[int] | None = None,
) -> dict:
    """应用工厂汇总编辑，并按损耗率覆盖写所涉采购单的备品。

    - `data`：编辑项列表，**可为空**（用户仅交互了损耗率、无任何布料改动）。
    - `order_ids`：本次汇总涉及的采购单 ID，用于在无编辑项时定位写入目标。
    - `spare_rate` 非 None 时，对「被编辑明细所属采购单 ∪ order_ids」覆盖写率与备品。
    """
    updated = 0
    involved_po_ids: list[int] = list(order_ids or [])
    touched_items: list[PurchaseOrderItem] = []
    for entry in data:
        item_ids = entry.get('item_ids', [])
        new_quantity = entry.get('quantity')
        new_loss_rate = entry.get('loss_rate')
        if not item_ids or (new_quantity is None and new_loss_rate is None):
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

        involved_po_ids.extend(it.order_id for it in items)
        touched_items.extend(items)

        if new_quantity is not None:
            if len(items) == 1:
                items[0].quantity = Decimal(str(new_quantity))
                updated += 1
            else:
                original_total = sum(float(it.quantity or 0) for it in items)
                if original_total > 0:
                    ratio = float(new_quantity) / original_total
                    for it in items:
                        it.quantity = Decimal(str(round_qty(float(it.quantity or 0) * ratio)))
                        updated += 1
                else:
                    per_item = Decimal(str(round_qty(float(new_quantity) / len(items))))
                    for it in items:
                        it.quantity = per_item
                        updated += 1

        if new_loss_rate is not None:
            normalized_loss = normalize_spare_rate(new_loss_rate)
            for it in items:
                it.loss_rate = Decimal(str(normalized_loss)) if normalized_loss is not None else None
            updated += 1

    # 编辑应用完毕后，再批量覆盖写所涉采购单的损耗率 / 备品（一次查询，无 N+1）
    spare_written = await _write_spare_rate_to_orders(db, involved_po_ids, spare_rate)

    # 数量与损耗率都会改变**计价数量**（落库数量按损耗率加放），
    # 因此行金额与采购单总金额必须在编辑后重算，否则停留在旧口径。
    #
    # 重算范围 = 被编辑明细所属采购单 ∪ 本次覆盖写损耗率的采购单：
    # **订单级损耗率**同样是明细有效损耗率的来源（逐行 loss_rate 为空时回退到它），
    # 只改订单级损耗率而不重算，该单的行金额就还是旧口径；
    # 而「只改损耗率、没改任何布料」时 touched_items 为空，光看它会一个单都不重算。
    recalc_order_ids = {it.order_id for it in touched_items if it.order_id}
    if spare_rate is not None:
        recalc_order_ids.update(oid for oid in involved_po_ids if oid)
    await _recalc_orders_amount(db, recalc_order_ids)

    await db.flush()
    return {'updated_count': updated, 'spare_updated_count': spare_written}


async def _recalc_orders_amount(db: AsyncSession, order_ids: set[int]) -> None:
    """重算所涉采购单**全部**明细的行金额与该单总金额。

    计价数量口径与前端「金额」列一致（见 :func:`_recalc_item_total_price`）：
    数量改大、逐行损耗率改高、或**订单级损耗率**被覆盖，都会让行金额变化，
    采购单总金额必须同步，否则「明细金额之和 ≠ 采购单金额」，供应商金额汇总随之失真。

    必须重算该单的**全部**明细，而不只是被编辑的那几行：一行按新率、另一行按旧率，
    同一张单里就混着两种口径，合计既不是旧口径也不是新口径。

    Args:
        db: 数据库会话。
        order_ids: 需要重算的采购单 ID 集合。
    """
    if not order_ids:
        return

    orders_result = await db.execute(
        select(PurchaseOrder).where(PurchaseOrder.id.in_(order_ids))
    )
    order_map = {o.id: o for o in orders_result.scalars().all()}

    # 一次查询取回这些单的全部明细，避免逐单 N+1
    all_items_result = await db.execute(
        select(PurchaseOrderItem).where(PurchaseOrderItem.order_id.in_(order_ids))
    )
    totals: dict[int, Decimal] = defaultdict(lambda: Decimal('0'))
    for it in all_items_result.scalars().all():
        order = order_map.get(it.order_id)
        _recalc_item_total_price(it, order.spare_rate if order else None)
        totals[it.order_id] += (it.total_price or Decimal('0'))
    for order_id, total in totals.items():
        order = order_map.get(order_id)
        if order is not None:
            order.total_amount = total


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

    P0（2026-10-24）：来源 id 必须带类型匹配。`order.id` 与 `stockin.id` 是两套自增
    序列、必然撞号；原先两类 id 合并成无类型数组去命中 source_order_id(s)，删订单 N
    会连带删掉「由备货 N 生成」的 pending 单（含已录单价与全部明细）。

    匹配全部下推到 SQL（不新增 round-trip，便于既有 mock 测试与性能）：
      a. purchase_order_sku 的 (source_record_type, source_order_id) —— 权威；
      b. source_order_ids JSON 数组 —— 老数据兜底；
      c. source_order_id 单列 —— 老数据兜底，但**仅当该 id 不同时存在于 order 与
         stockin 两表**（否则裸 id 无法判类型，宁可漏删不可错删）。
    """
    source_ids: list[int] = []
    if order_ids:
        source_ids.extend(order_ids)
    if stockin_ids:
        source_ids.extend(stockin_ids)
    if not source_ids:
        return 0

    _exclude = set(exclude_ids or [])

    from sqlalchemy import and_, exists, literal, not_, or_
    from sqlalchemy import cast as sa_cast
    from sqlalchemy.dialects.postgresql import JSONB as PG_JSONB

    from fastapi_app.shared_models import Order, StockIn

    # a) 类型感知匹配（子查询，不额外查一次库）
    typed_pairs: list[tuple[str, int]] = []
    typed_pairs.extend(('order', int(i)) for i in (order_ids or []))
    typed_pairs.extend(('stockin', int(i)) for i in (stockin_ids or []))
    typed_match = PurchaseOrder.id.in_(
        select(PurchaseOrderSku.po_id).where(
            or_(*[
                and_(
                    PurchaseOrderSku.source_record_type == rtype,
                    PurchaseOrderSku.source_order_id == rid,
                )
                for rtype, rid in typed_pairs
            ])
        )
    ) if typed_pairs else None

    # b) JSON 数组兜底（先取候选 id，沿用既有查询）
    jsonb_col = sa_cast(PurchaseOrder.source_order_ids, PG_JSONB)
    contain_conds = [jsonb_col.contains([sid]) for sid in sorted({int(i) for i in source_ids})]
    result2 = await db.execute(
        select(PurchaseOrder.id).where(
            PurchaseOrder.source_order_ids.isnot(None),
            PurchaseOrder.status == PurchaseOrderStatus.PENDING,
            or_(*contain_conds),
        )
    )
    json_match_ids = [row[0] for row in result2.all()]

    # c) 裸 id 兜底：id 同时存在于 order 与 stockin 时视为歧义，不采信
    id_in_both_tables = and_(
        exists(select(literal('1')).select_from(Order).where(Order.id == PurchaseOrder.source_order_id)),
        exists(select(literal('1')).select_from(StockIn).where(StockIn.id == PurchaseOrder.source_order_id)),
    )
    legacy_match = and_(
        PurchaseOrder.source_order_id.in_(sorted({int(i) for i in source_ids})),
        not_(id_in_both_tables),
    )

    conditions = [PurchaseOrder.status == PurchaseOrderStatus.PENDING, legacy_match]
    if json_match_ids:
        conditions.append(PurchaseOrder.id.in_(json_match_ids))
    if typed_match is not None:
        conditions.append(typed_match)
    result = await db.execute(select(PurchaseOrder).where(or_(*conditions[1:]), conditions[0]))
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
