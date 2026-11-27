"""
采购订单 CRUD 操作

职责：采购订单的创建、更新、删除、完成、清理等写操作。
从 purchase_order_service.py 拆分而来，保持函数签名不变。
"""
import hashlib
import json
import logging
from collections import defaultdict
from collections.abc import Sequence
from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import delete, or_, select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from fastapi_app.core.business_time import business_today
from fastapi_app.core.exceptions import ConflictError, ItemsVersionConflict
from fastapi_app.core.float_utils import round_qty
from fastapi_app.services.numbering import generate_purchase_order_number
from fastapi_app.services.purchase_order_idempotency import acquire_key_lock, load_replay, save_result
from fastapi_app.services.purchase_order_purge import purge_purchase_order_children
from fastapi_app.services.purchase_order_sku import resync_po_sku_spare
from fastapi_app.services.purchase_utils import (
    calc_spare_quantity,
    magnified_purchase_qty,
    normalize_spare_rate,
    parse_source_order_ids,
    resolve_item_loss_rate,
)
from fastapi_app.shared_models import (
    MaterialRegistration,
    MaterialRegistrationItem,
    ModificationLog,
    Order,
    PurchaseOrder,
    PurchaseOrderItem,
    PurchaseOrderSku,
    PurchaseOrderStatus,
    StockIn,
)

logger = logging.getLogger(__name__)


def _scope_remark(source_role: str | None) -> str:
    """把来源 BOM 作用域转成明细备注；无来源时返回空串（保持旧行为）。"""
    return f'来源BOM：{source_role}' if source_role else ''


async def _create_material_registration(
    db: AsyncSession, order: PurchaseOrder, items: Sequence[PurchaseOrderItem],
) -> MaterialRegistration:
    """创建来料登记及其明细行（由调用方负责最终 flush/commit）。

    明细 = 采购明细 + BOM 中未被采购明细覆盖的物料行（见
    ``services/material_registration/_bom_items.py``），使 /material 与工厂汇总
    一样能显示产品 BOM 的全部物料及其明细级供应商。
    """
    registration = MaterialRegistration(
        purchase_order_id=order.id,
        purchase_order_no=order.order_no,
        supplier_id=order.supplier_id,
        supplier_name=order.supplier_name or '',
        # P1-9（2026-11-17 审计；推送前评审补漏）：这是 MaterialRegistration 的**主**
        # 生产路径（采购单创建 / BOM 同步时自动建来料登记）。原先用 UTC 日界，北京
        # 00:00–08:00 建的单会落到「昨天」，与 _commands / 模型默认值口径相反。
        registration_date=business_today(),
        remark='',
        status='pending',
    )
    db.add(registration)
    await db.flush()

    from fastapi_app.services.material_registration._bom_items import (
        build_registration_items,
    )

    for row in await build_registration_items(db, order, items):
        db.add(MaterialRegistrationItem(
            registration_id=registration.id,
            order_item_id=row['order_item_id'],
            material_code=row['material_code'],
            material_name=row['material_name'],
            specification=row['specification'],
            unit=row['unit'],
            ordered_quantity=row['ordered_quantity'],
            received_quantity=row['received_quantity'],
            material_category=row['material_category'],
            supplier_name=row['supplier_name'],
            remark=row['remark'],
        ))
    return registration


async def create_purchase_order(
    db: AsyncSession, data: dict, include_summary: bool = False,
    idempotency_key: str = '', actor_id: int | None = None,
) -> dict:
    # P1（2026-10-24）：端点 schema 的字段名是 materials/remark（purchase_center/schemas.py），
    # 而本函数原先只读 items/note，pydantic 忽略多余字段 → POST /purchase-center/orders
    # 恒 400「至少需要一条明细」。两种键名都接受，兼容脚本/旧调用方。
    items = data.get('materials') or data.get('items') or []
    if not items:
        raise ValueError('采购订单至少需要一条明细')

    # M-28（2026-11-21 审计）：手工建单与一键生成共用幂等登记——uq_po_pending_dedup
    # 只盖 source_order_ids 非空的生成单，手工单双击/重试会产生重复 pending 单。
    fingerprint = ''
    if idempotency_key:
        if actor_id is None:
            raise ValueError('使用幂等键时必须提供操作者 ID')
        fingerprint = hashlib.sha256(
            json.dumps(data, sort_keys=True, ensure_ascii=False, default=str).encode('utf-8')
        ).hexdigest()
        await acquire_key_lock(db, actor_id, idempotency_key)
        replay = await load_replay(db, actor_id, idempotency_key, fingerprint)
        if replay is not None:
            return replay

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
        # L-4（2026-11-21 审计）：行金额先按落库精度（Numeric(12,2)）quantize 再合计，
        # 与 _recalc_item_total_price「内存/落库合计同口径」的约定一致
        amount = (unit_price * quantity).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        unit_usage = item_data.get('unit_usage')

        poi = PurchaseOrderItem(
            order_id=order.id,
            material_name=material_name,
            material_code=item_data.get('material_code', ''),
            specification=item_data.get('specification', ''),
            unit=item_data.get('unit', ''),
            unit_price=unit_price,
            quantity=quantity,
            total_price=amount,
            # BOM 单件用量：生成路径（build_expected_items）已产出该值，必须落库——
            # 否则行恒为默认 0，bom_sync 的「用量未变才继承自定义数量」判定失效
            # （0 ≠ 真实用量 → 手工数量会在下次 BOM 保存时被覆盖）。
            unit_usage=unit_usage if unit_usage is not None else 0,
            supplier_name=item_data.get('supplier_name') or supplier_name,
            customer_name=customer_name,
            material_category=item_data.get('category', ''),
            part_name=item_data.get('part_name'),
            # BOM 作用域角色（2026-11-11 口径）：同物料多角色各自成行，键含 role_id
            role_id=item_data.get('role_id'),
            # 来源 BOM 作用域（默认BOM / 各角色）：写进备注，采购员能看出这条需求由谁产生。
            # 无 source_role（如手工单、旧路径）时保持 remark 原样，不产生多余文本。
            remark=item_data.get('remark') or _scope_remark(item_data.get('source_role')),
            # 产品条码（2026-11-16 审计 A-52）：这一列此前全仓零写入，
            # 于是 /orders/completed?barcode= 的 EXISTS 子查询永远不命中。
            # 这里承接调用方给的条码（BOM 生成路径来自 SKU 快照的 product_barcode）；
            # 上游没给时保持 NULL，不伪造。
            barcode=item_data.get('barcode') or item_data.get('product_barcode') or None,
        )
        db.add(poi)
        total_amount += amount

    order.total_amount = total_amount
    await db.flush()

    result = {'order_no': order_no, 'id': order.id, 'total_amount': float(total_amount)}

    if include_summary:
        result['summary'] = await _build_order_summary(db, order)

    if idempotency_key and actor_id is not None:
        # load_replay 只重放 body.get('success') 为真的结果（生成路径的 result 自带
        # success 键）；手工建单的 result 没有——不带键存会永不重放、每次都真建单。
        await save_result(db, actor_id, idempotency_key, fingerprint, {'success': True, **result})
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
    if 'part_name' in item_data:
        item.part_name = item_data.get('part_name')
    if 'role_id' in item_data:
        item.role_id = item_data.get('role_id')
    item.remark = item_data.get('remark') or _scope_remark(item_data.get('source_role'))
    item.supplier_name = order.supplier_name
    item.customer_name = order.customer_name
    return line_total


# 明细「内容」的判定字段：用于 upsert 是否**实际改动**了明细（决定 items_version 递增）。
# 不含 total_price（派生列）与 order_id/product_name/customer_name 之外的派生信息。
_ITEM_SIGNATURE_FIELDS = (
    'material_name', 'material_code', 'specification', 'unit', 'unit_price',
    'quantity', 'material_category', 'part_name', 'remark', 'supplier_name',
    'customer_name', 'role_id',
)


def _item_signature(item: PurchaseOrderItem) -> tuple:
    """明细可变字段快照；None 与 '' 归一（两者在库里/页面上都表示空），Numeric 转 float。"""
    def _norm_value(value):
        if value is None or value == '':
            return None
        if isinstance(value, Decimal):
            return float(value)
        return value

    return tuple(_norm_value(getattr(item, field, None)) for field in _ITEM_SIGNATURE_FIELDS)


async def _upsert_order_items(
    db: AsyncSession, order: PurchaseOrder, order_id: int, items_data: list
) -> bool:
    """批量预取并 upsert 订单明细（直接修改 order.total_amount）。

    Returns:
        是否**实际改动**了明细（新增行、字段值变化、或删除未提交的行）。
        仅原样重发相同明细时为 False —— 调用方据此决定 items_version 是否递增，
        避免「保存一次就顶掉别人的版本」。
    """
    existing_items_result = await db.execute(
        select(PurchaseOrderItem).where(PurchaseOrderItem.order_id == order_id)
    )
    existing_items = {item.id for item in existing_items_result.scalars().all()}

    total_amount = Decimal('0')
    updated_ids = set()
    changed = False

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

        # 新增行（无 item_id）无论内容如何都是明细变化；已有行逐字段比对，
        # 仅原样重发相同的明细不递增版本。
        before = _item_signature(item) if item_id else None
        line_total = _apply_item_fields(item, item_data, order)
        if before is None or _item_signature(item) != before:
            changed = True

        if not item_id:
            db.add(item)
        total_amount += line_total

    to_delete_ids = existing_items - updated_ids
    if to_delete_ids:
        changed = True
        await db.execute(
            delete(PurchaseOrderItem).where(PurchaseOrderItem.id.in_(to_delete_ids))
        )

    order.total_amount = total_amount
    return changed


async def _update_item_prices(
    db: AsyncSession, order: PurchaseOrder, order_id: int, price_entries: list,
) -> bool:
    """按明细 id 补录单价，并重算行金额与订单总金额。

    一键生成路径把 unit_price 写死 0（BOM 里没有价格来源），而更新请求原本
    不带 items 字段 → 采购单价生成后**没有任何入口**可改，采购单金额恒为 0，
    供应商金额汇总（``SUM(purchase_order.total_amount)``）因此恒为 0。

    只改单价：不动数量/物料，也不删行——与 ``_upsert_order_items`` 的
    「未提交的明细视为删除」语义区分开，避免只补录价格时误删其它行。

    Returns:
        是否有单价**实际变化**（同值重发不算，不递增 items_version）。
    """
    # 先落库：同一次请求里若还带了 items（upsert 新增的明细尚未 flush），
    # 不 flush 就查不到那些新行，订单总金额会漏算。
    await db.flush()

    items_result = await db.execute(
        select(PurchaseOrderItem).where(PurchaseOrderItem.order_id == order_id)
    )
    items = {item.id: item for item in items_result.scalars().all()}

    seen: set[int] = set()
    changed = False
    for entry in price_entries:
        item_id = entry['id']
        # L-3（2026-11-21 审计）：显式 ROUND_HALF_UP——Python 默认 ROUND_HALF_EVEN
        # 与 PG numeric 落库方向不一致（同文件 _recalc_item_total_price 的约定）
        price = Decimal(str(entry['unit_price'])).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        if item_id in seen:
            raise ValueError(f'采购明细 {item_id} 重复提交单价')
        seen.add(item_id)
        if price < 0:
            raise ValueError('单价不能为负数')
        item = items.get(item_id)
        if item is None:
            raise ValueError(f'采购明细 {item_id} 不存在或不属于该采购单')
        if item.unit_price is None or item.unit_price != price:
            changed = True
        item.unit_price = price
        _recalc_item_total_price(item, order.spare_rate)

    order.total_amount = sum(
        (item.total_price or Decimal('0') for item in items.values()), Decimal('0')
    )
    return changed


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

    # 乐观锁（BOM 实时同步）：客户端持有的明细版本过期 → 409。
    # 必须在 _apply_order_field_updates 等任何字段写入之前。
    expected_version = data.get('items_version')
    if expected_version is not None and (order.items_version or 0) != expected_version:
        raise ItemsVersionConflict()

    _apply_order_field_updates(order, data)

    items_changed = False
    items_data = data.get('items')
    if items_data is not None:
        items_changed = await _upsert_order_items(db, order, order_id, items_data)

    prices_changed = False
    price_entries = data.get('item_prices')
    if price_entries:
        prices_changed = await _update_item_prices(db, order, order_id, price_entries)

    # 用户编辑明细同样递增版本（spec 同步算法-7）：BOM 同步的版本保护必须把
    # 手工改数量/价格也视为「明细已变」，否则客户端在打开汇总/详情期间发生的
    # 用户编辑不会被 409 拦住，保存时用旧版本写回已失效的行上。
    if items_changed or prices_changed:
        order.items_version = (order.items_version or 0) + 1

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

    # 返回完整 to_dict（含 items_version）：前端保存单价后要用响应里的新版本
    # 回写本地订单对象，否则同一详情页连续保存的第二次会带过期版本被 409。
    return order.to_dict()


async def _po_source_order_ids(db: AsyncSession, order: PurchaseOrder) -> set[int]:
    """该采购单引用到的**客户订单** id（逐 SKU 快照优先，主表字段兜底）。

    只取 ``source_record_type='order'``：``order.id`` 与 ``stock_in.id`` 会撞号，
    裸 id 匹配会把备货来源误当成客户订单。
    """
    snapshot_ids: set[int] = set()
    try:
        rows = await db.execute(
            select(PurchaseOrderSku.source_order_id).where(
                PurchaseOrderSku.po_id == order.id,
                PurchaseOrderSku.source_record_type == 'order',
            )
        )
        snapshot_ids = {int(x) for x in rows.scalars().all() if x}
    except SQLAlchemyError:
        # 快照表在旧库可能不存在（迁移 047 之前）：退回主表字段即可
        logger.warning('读取采购单 %s 的 SKU 来源失败，退回主表字段', order.id, exc_info=True)

    # 快照带 source_record_type，优先信任；主表字段没有类型信息（order.id 与 stock_in.id 撞号）
    if snapshot_ids:
        return snapshot_ids

    candidates: set[int] = set(parse_source_order_ids(order.source_order_ids))
    single_source = order.source_order_id
    if single_source:
        candidates.add(int(single_source))
    return await _drop_ambiguous_ids(db, candidates)


async def _drop_ambiguous_ids(db: AsyncSession, ids: set[int]) -> set[int]:
    """剔除「同时存在于 stock_in」的 id：该列无法区分客户订单与备货记录，撞号时不采信。"""
    if not ids:
        return set()
    rows = await db.execute(select(StockIn.id).where(StockIn.id.in_(ids)))
    ambiguous = {int(x) for x in rows.scalars().all()}
    if ambiguous:
        logger.warning('采购单来源 id 与备货记录撞号，按歧义丢弃: %s', sorted(ambiguous))
    return set(ids) - ambiguous


async def _orders_still_covered_by_po(db: AsyncSession, order_ids: set[int]) -> set[int]:
    """这些客户订单是否仍被**其它**采购单引用（含已完成单）。"""
    if not order_ids:
        return set()
    covered: set[int] = set()
    try:
        rows = await db.execute(
            select(PurchaseOrderSku.source_order_id).where(
                PurchaseOrderSku.source_record_type == 'order',
                PurchaseOrderSku.source_order_id.in_(order_ids),
            )
        )
        covered.update(int(x) for x in rows.scalars().all() if x)
    except SQLAlchemyError:
        logger.warning('读取 SKU 来源快照失败，仅按主表字段判断覆盖关系', exc_info=True)
    rows = await db.execute(
        select(PurchaseOrder.source_order_id, PurchaseOrder.source_order_ids).where(
            or_(
                PurchaseOrder.source_order_id.in_(order_ids),
                PurchaseOrder.source_order_ids.isnot(None),
            )
        )
    )
    from_main: set[int] = set()
    for single, many in rows.all():
        if single:
            from_main.add(int(single))
        from_main.update(parse_source_order_ids(many))
    # 主表字段无类型信息：与 stock_in 撞号的 id 不采信，避免把无关订单当成「仍被覆盖」
    covered |= await _drop_ambiguous_ids(db, from_main & set(order_ids))
    return covered & set(order_ids)


async def _reset_uncovered_source_orders(db: AsyncSession, order_ids: set[int]) -> int:
    """删除采购单后，把**已无任何采购单覆盖**的来源订单状态重算回真实值。

    生成采购单时会把来源订单直接置为「已备货」；只删单不重算，订单就永远卡在
    「已备货」——既不在待生成列表里，也会被生成前置校验拦住。仍被其它采购单
    覆盖的订单不动（否则会被重复下单）。
    """
    if not order_ids:
        return 0
    covered = await _orders_still_covered_by_po(db, order_ids)
    to_reset = set(order_ids) - covered
    if not to_reset:
        return 0
    from fastapi_app.services.order_utils import compute_order_statuses_batch

    # 锁住相关订单行再判「是否仍被覆盖」→ 回退，避免两个并发删除都以为对方还覆盖着，
    # 结果谁都不回退（订单永久卡在「已备货」且已无单可删）。
    orders = list((await db.execute(
        select(Order)
        .where(Order.id.in_(to_reset), Order.is_deleted.isnot(True))
        .order_by(Order.id)
        .with_for_update()
    )).scalars().all())
    if not orders:
        return 0
    status_map = await compute_order_statuses_batch(db, orders)
    changed = 0
    for order in orders:
        new_status = status_map.get(order.id)
        if new_status and new_status != order.status:
            order.status = new_status
            changed += 1
    await db.flush()
    return changed


async def delete_purchase_order(db: AsyncSession, order_id: int) -> dict:
    # B1-05（2026-10-24 审计）：删除与 complete 一样先读后写，无行锁时并发
    # 删除/完成同单可同时通过状态校验（update 已于 2026-10-24 接行锁）。
    order = await db.get(PurchaseOrder, order_id, with_for_update=True)
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

    # 记下来源客户订单（删完要判断它们是否还有别的采购单覆盖）
    source_order_ids = await _po_source_order_ids(db, order)

    try:
        # 子表（明细 + 逐 SKU 快照）统一由 purge 显式批量删除：
        # 两者都是 lazy='raise' + delete-orphan，靠 ORM 级联会在 flush 时抛
        # InvalidRequestError；purchase_order_item 的 FK 又是 NO ACTION（A-M19）。
        await purge_purchase_order_children(db, [order_id])

        await db.delete(order)
        await db.flush()
    except IntegrityError as e:
        raise ConflictError(f'采购单{order.order_no}被来料登记等记录引用，无法删除') from e

    # 生成采购单时把来源订单置为「已备货」；删单后没有任何采购单覆盖的订单
    # 必须回退到真实状态，否则永远回不到待生成列表（历史缺陷：删错单只能改库）。
    await _reset_uncovered_source_orders(db, source_order_ids)
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
    # B1-05（2026-10-24 审计）：完成是「读状态→写状态→建来料登记」的先读后写，
    # material_registration.purchase_order_id 无唯一约束——并发/双击重复完成会
    # 重复登记来料（到货判定 SUM 翻倍）。与 update 同款行锁先锁后校验。
    order = await db.get(PurchaseOrder, order_id, with_for_update=True)
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
    # 完成同样改变明细语义（来料登记 ordered_quantity 是完成时快照）：
    # 递增 items_version，让持有旧快照的汇总弹窗保存时 409（E-H1 第二道保险）。
    order.items_version = (getattr(order, 'items_version', 0) or 0) + 1
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

    # B1-05（2026-10-24 审计）：批量完成逐单行锁（FOR UPDATE），语义同单条完成。
    result = await db.execute(
        select(PurchaseOrder).where(PurchaseOrder.id.in_(order_ids)).with_for_update()
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
            # 同单条完成：完成也改变明细语义，递增版本作并发保护第二道保险
            order.items_version = (getattr(order, 'items_version', 0) or 0) + 1
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


def _items_version_lock_stmt(po_ids: list[int]):
    """构造「状态 + 版本」写前校验语句（PG 下 ``FOR UPDATE``）。

    用途：在读取目标采购单的同一语句里对相关 ``purchase_order`` 行加锁，
    使「校验 → 写入」与完成 / BOM 同步的「加锁 → 改状态或递增版本 → 重写明细」
    互斥，关闭比对后、flush 前被并发提交顶掉的 TOCTOU 窗口。锁范围与
    ``bom_sync.sync_purchase_order_items`` 一致（仅单表 PO 行）；``ORDER BY id``
    给多行加锁以确定顺序，降低并发保存互相死锁的可能。
    """
    return (
        select(
            PurchaseOrder.id,
            PurchaseOrder.order_no,
            PurchaseOrder.status,
            PurchaseOrder.items_version,
        )
        .where(PurchaseOrder.id.in_(po_ids))
        .order_by(PurchaseOrder.id)
        .with_for_update()
    )


async def _validate_factory_edit_targets(
    db: AsyncSession, data: list, order_ids: list[int] | None,
    items_versions: dict[int, int] | None, spare_rate: float | None = None,
) -> None:
    """写前锁住本次会写入的采购单，校验状态（pending/confirmed 可改）与客户端版本。

    状态校验**无条件执行**：旧客户端不传 ``items_versions`` 时版本校验整段跳过，
    而「下单完成」会冻结明细语义（来料登记 ``ordered_quantity`` 是完成时快照，
    全仓没有跟随更新语句，收货上限会按旧值永久卡死 —— E-H1，2026-11-27 审计）。
    ``CONFIRMED`` 放行：它是待生产列表的正式口径（``usePurchaseOrders`` 查询
    ``pending,confirmed``），完成路径也接受它（owner 2026-11-27 裁决）。

    **状态只校验真正会被写入的单**（2026-11-27 跨层评审 High）：
    - 编辑项命中的明细所属单（``_apply_item_edit_entries`` 只写这些单）；
    - 仅当 ``spare_rate is not None`` 时才包含 ``order_ids``——该参数在
      ``_write_spare_rate_to_orders`` 里 None 直接 return 0，此时 ``order_ids``
      只是前端回显的选中集合（含已 completed 的历史单），校验它会让「待生产列表
      勾选 A、B → 完成 B → 汇总里改 A 数量」整次保存 409，且前端按同一 id 集合
      重开汇总后永远无法自愈。
    锁与版本校验仍覆盖**全部**涉及单（``order_ids`` ∪ 编辑项所属单），保持既有
    乐观锁语义——版本快照来自同一次汇总请求，包含哪些单就该校验哪些单。

    版本校验只比对 ``items_versions`` 中显式给出的采购单：None / 空 dict
    （旧客户端）不校验；给出但不在本次涉及集合内的单不参与比对（避免无关单
    的版本变化造成假 409）。

    明细归属需先查库（只读），故批量取一次 item_id → order_id；跳过口径与服务层
    主循环一致（无 item_ids、或 quantity/loss_rate 均为 None 的条目不会写任何单，
    也不参与校验）。
    """
    edited_item_ids: set[int] = set()
    for entry in data:
        if not entry.get('item_ids'):
            continue
        if entry.get('quantity') is None and entry.get('loss_rate') is None:
            continue
        edited_item_ids.update(entry['item_ids'])
    edited_po_ids: set[int] = set()
    if edited_item_ids:
        rows = await db.execute(
            select(PurchaseOrderItem.id, PurchaseOrderItem.order_id).where(
                PurchaseOrderItem.id.in_(edited_item_ids)
            )
        )
        edited_po_ids.update(row.order_id for row in rows.all())

    # 锁/版本范围：全部涉及单。状态范围：只有真正会写的单。
    scope_po_ids: set[int] = {oid for oid in (order_ids or []) if oid} | edited_po_ids
    status_po_ids: set[int] = set(edited_po_ids)
    if spare_rate is not None:
        status_po_ids.update(oid for oid in (order_ids or []) if oid)
    if not scope_po_ids:
        return

    result = await db.execute(_items_version_lock_stmt(sorted(scope_po_ids)))
    rows = {row.id: row for row in result.all()}
    for po_id in sorted(scope_po_ids):
        row = rows.get(po_id)
        # 不存在的 id 保持旧行为：静默跳过（写路径零命中，不会产生任何写入）
        if row is None:
            continue
        if po_id in status_po_ids and row.status not in (
            PurchaseOrderStatus.PENDING, PurchaseOrderStatus.CONFIRMED,
        ):
            raise ConflictError(
                f'采购单{row.order_no}状态为{row.status}，'
                f'仅待完成（pending）或已确认待生产（confirmed）的采购单可修改数量/损耗率'
            )
        if items_versions and po_id in items_versions:
            if (row.items_version or 0) != items_versions[po_id]:
                raise ItemsVersionConflict()


def _apply_quantity_edit(
    items: list[PurchaseOrderItem], new_quantity: float, changed_po_ids: set[int],
) -> int:
    """把目标数量落到明细行，返回更新行数；同值行不算变更。"""
    if len(items) == 1:
        target_qty = Decimal(str(new_quantity))
        if items[0].quantity != target_qty:
            changed_po_ids.add(items[0].order_id)
        items[0].quantity = target_qty
        return 1
    original_total = sum(float(it.quantity or 0) for it in items)
    if original_total <= 0:
        per_item = Decimal(str(round_qty(float(new_quantity) / len(items))))
        for it in items:
            if it.quantity != per_item:
                changed_po_ids.add(it.order_id)
            it.quantity = per_item
        return len(items)
    ratio = float(new_quantity) / original_total
    # B1-06（2026-10-24 审计）：逐行 2 位舍入的残差回填最后一行，
    # 否则 Σ分摊 ≠ 用户输入的目标数量（3 行拆 100 得 99.99），
    # 行金额按偏移后的数量重算，对账时出现无解释零头。
    for it in items:
        target_qty = Decimal(str(round_qty(float(it.quantity or 0) * ratio)))
        if it.quantity != target_qty:
            changed_po_ids.add(it.order_id)
        it.quantity = target_qty
    residual = round_qty(
        float(new_quantity) - sum(float(it.quantity or 0) for it in items)
    )
    if residual:
        target_qty = Decimal(str(round_qty(float(items[-1].quantity or 0) + residual)))
        if items[-1].quantity != target_qty:
            changed_po_ids.add(items[-1].order_id)
        items[-1].quantity = target_qty
    return len(items)


def _apply_loss_rate_edit(
    items: list[PurchaseOrderItem], new_loss_rate: float, changed_po_ids: set[int],
) -> None:
    """把损耗率写到明细行（归一化后与库值比对，同值不算变更）。"""
    normalized_loss = normalize_spare_rate(new_loss_rate)
    new_loss = Decimal(str(normalized_loss)) if normalized_loss is not None else None
    for it in items:
        if it.loss_rate != new_loss:
            changed_po_ids.add(it.order_id)
        it.loss_rate = new_loss


async def _apply_item_edit_entries(
    db: AsyncSession, data: list, order_ids: list[int] | None,
    changed_po_ids: set[int], username: str = 'unknown',
) -> tuple[int, list[int], list[PurchaseOrderItem]]:
    """逐条应用数量/损耗率编辑。

    数量**实际变化**时按明细写 ``ModificationLog``（target_type=purchase_item,
    field_name=quantity, 旧值/新值/操作人）——该保存通道此前无任何审计，
    事后只能看到 items_version 变了却查不到是谁改的（2026-11-13 生产反馈）。

    返回 ``(updated, involved_po_ids, touched_items)``；``changed_po_ids`` 收集
    实际发生变更的采购单 id（同值重发不算），供调用方决定是否递增版本。
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
            old_quantities = {it.id: it.quantity for it in items}
            updated += _apply_quantity_edit(items, new_quantity, changed_po_ids)
            for it in items:
                old_quantity = old_quantities.get(it.id)
                if old_quantity == it.quantity:
                    continue
                db.add(ModificationLog(
                    target_type='purchase_item',
                    target_id=it.id,
                    field_name='quantity',
                    old_value=str(old_quantity),
                    new_value=str(it.quantity),
                    modifier_name=username,
                ))
        if new_loss_rate is not None:
            _apply_loss_rate_edit(items, new_loss_rate, changed_po_ids)
            updated += 1
    return updated, involved_po_ids, touched_items


async def _bump_items_versions(
    db: AsyncSession, changed_po_ids: set[int],
) -> dict[int, int]:
    """对实际变更的采购单各 +1 ``items_version``，返回 ``{po_id: 新版本}``。

    与 BOM 同步同序加锁（ORDER BY id + FOR UPDATE），避免与同步/其他保存互锁。
    键为采购单 id（JSON 序列化后字符串键）；只回传实际递增过的单。
    """
    if not changed_po_ids:
        return {}
    orders_result = await db.execute(
        select(PurchaseOrder)
        .where(PurchaseOrder.id.in_(sorted(changed_po_ids)))
        .order_by(PurchaseOrder.id)
        .with_for_update()
    )
    version_map = {o.id: o for o in orders_result.scalars().all()}
    result: dict[int, int] = {}
    for po_id in sorted(changed_po_ids):
        order = version_map.get(po_id)
        if order is None:
            continue
        # getattr 兜轻量 mock（SimpleNamespace 无该字段）：真实 ORM 列默认 0/None。
        order.items_version = (getattr(order, 'items_version', 0) or 0) + 1
        result[po_id] = order.items_version
    return result


async def save_factory_summary_edits(
    db: AsyncSession, data: list, username: str = 'unknown',
    spare_rate: float | None = None, order_ids: list[int] | None = None,
    items_versions: dict[int, int] | None = None,
) -> dict:
    """应用工厂汇总编辑，并按损耗率覆盖写所涉采购单的备品。

    - `data`：编辑项列表，**可为空**（用户仅交互了损耗率、无任何布料改动）。
    - `order_ids`：本次汇总涉及的采购单 ID，用于在无编辑项时定位写入目标。
    - `spare_rate` 非 None 时，对「被编辑明细所属采购单 ∪ order_ids」覆盖写率与备品。
    - `items_versions`：客户端持有的（采购单 ID → 明细版本）快照；非空时在
      **任何写入之前**逐单比对，过期即抛 ``ItemsVersionConflict``（409）。
    - **会被写入的采购单**若状态不是 pending/confirmed 则整体拒绝（409，
      ``ConflictError``）：完成后明细语义已按来料登记快照冻结，改数量/损耗率会让
      收货上限永久对不上（E-H1）。该守卫在任何写入之前执行，且不依赖
      ``items_versions``（旧客户端同样拦）。状态校验范围严格等于写入范围——
      ``spare_rate is None`` 时 ``order_ids`` 不写入，故也不参与状态校验
      （2026-11-27 跨层评审 High：否则前端回显的已完成单会拖死同选的其他单）。

    返回值额外带 ``items_versions``（本次实际递增过版本的采购单 → 新版本）：
    客户端保存成功后用它前移本地版本快照，避免同一弹窗内连续保存第二次带旧版本 409。
    """
    await _validate_factory_edit_targets(
        db, data, order_ids, items_versions, spare_rate)

    # 实际发生明细变更的采购单（数量/损耗率写前比对，同值重发不算）。
    changed_po_ids: set[int] = set()
    updated, involved_po_ids, touched_items = await _apply_item_edit_entries(
        db, data, order_ids, changed_po_ids, username,
    )

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

    # 用户编辑也递增 items_version（spec 同步算法-7）：
    # - 数量/损耗率实际变化 → 涉及单各 +1（每个单只加一次，用集合去重）；
    # - spare_rate 覆盖写 → 所有涉及单 +1（订单级率是明细有效损耗率的回退源，
    #   该单全部明细的计价数量与金额都被改了，与「行被改写」同性质）。
    if spare_rate is not None:
        changed_po_ids.update(oid for oid in involved_po_ids if oid)
    items_versions_out = await _bump_items_versions(db, changed_po_ids)

    await db.flush()
    return {'updated_count': updated, 'spare_updated_count': spare_written,
            'items_versions': items_versions_out}


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


def _json_contains_trusted(jsonb_col, sid: int):
    """JSON 数组兜底的单 id 匹配条件（M-4，2026-11-21 审计）。

    id 同存于 order 与 stockin 两表时视为歧义不采信——存量无 SKU 快照的
    pending 单把备货 id 存进了数组，删同号客户订单时会误删备货来源单
    （与 c 路径裸 id 兜底的歧义守卫同口径）。判定内联进同一查询，
    不增加 execute 次数。sqlalchemy 操作符在函数内导入（与 cleanup 内
    既有局部导入同风格，避免模块级循环依赖）。
    """
    from sqlalchemy import and_, exists, literal, not_

    ambiguous = and_(
        exists(select(literal('1')).select_from(Order).where(Order.id == sid)),
        exists(select(literal('1')).select_from(StockIn).where(StockIn.id == sid)),
    )
    return and_(jsonb_col.contains([sid]), not_(ambiguous))


async def cleanup_orphan_pending_purchase_orders(
    db: AsyncSession, order_ids: list[int] | None = None,
    stockin_ids: list[int] | None = None,
    exclude_ids: list[int] | None = None,
) -> int:
    """清理关联指定客户订单 / 备货记录的 pending 采购订单。

    同时处理 source_order_id（单列）与 source_order_ids（JSON 数组）；返回删除数。

    P0（2026-10-24）：来源 id 必须带类型匹配——`order.id` 与 `stockin.id` 是两套
    自增序列必然撞号，无类型数组会误删。匹配全部下推到 SQL（不新增 round-trip）：
    a. purchase_order_sku 的 (source_record_type, source_order_id) —— 权威；
    b/c. 老数据兜底，且单列与数组路径均不采信「同存于 order 与 stockin 两表」的
    歧义 id（宁可漏删不可错删，见 _json_contains_trusted）。
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

    # b) JSON 数组兜底，歧义守卫见 _json_contains_trusted（M-4）。
    jsonb_col = sa_cast(PurchaseOrder.source_order_ids, PG_JSONB)
    contain_conds = [_json_contains_trusted(jsonb_col, sid)
                     for sid in sorted({int(i) for i in source_ids})]
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
    targets = [po for po in result.scalars().all() if po.id not in _exclude]
    deleted = 0
    if targets:
        # 兜底清理走的也是「先显式删子表、再删主表」：items 是 NO ACTION 外键，
        # 只删主表在真库上会 FK 409；依赖 ORM 级联又会因 lazy='raise' 抛
        # InvalidRequestError（A-M19）。
        await purge_purchase_order_children(db, [po.id for po in targets])
        for po in targets:
            await db.delete(po)
            deleted += 1
    if deleted:
        logger.info(
            'cleanup_orphan_pending_purchase_orders: 清理 %d 个 pending 采购单 (source_ids=%s)',
            deleted, source_ids,
        )
        # L-5（2026-11-21 审计）：兜底删单与 delete_purchase_order 同责——删后把已无
        # 任何采购单覆盖的来源客户订单状态重算回真实值；只传 order ids（stockin id
        # 与 order id 撞号，不可混入 _reset_uncovered_source_orders）
        await _reset_uncovered_source_orders(db, {int(i) for i in (order_ids or [])})
    return deleted
