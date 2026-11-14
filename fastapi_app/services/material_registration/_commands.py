"""物料登记命令域(创建/更新/删除/收货)

从 material_registration_service.py 按职责拆出,行为与原实现完全一致。
"""
import logging
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation

from sqlalchemy import select
from sqlalchemy.orm import joinedload, selectinload

from fastapi_app.shared_models import (
    MaterialRegistration,
    MaterialRegistrationItem,
    PurchaseOrder,
    PurchaseOrderItem,
)

from ._bom_items import _material_key, aggregate_bom_rows

logger = logging.getLogger(__name__)


async def _enrich_items_with_supplier_and_bom(db, po, items_data: list[dict]) -> None:
    """补明细级供应商，并追加 BOM 中未被传入明细覆盖的物料行（原地修改）。"""
    po_items = (await db.execute(
        select(PurchaseOrderItem).where(PurchaseOrderItem.order_id == po.id)
    )).scalars().all()
    by_id = {item.id: item for item in po_items}
    by_key = {
        _material_key(item.material_name, item.specification, item.unit): item
        for item in po_items
    }
    default_supplier = po.supplier_name or ''

    for item_data in items_data:
        if item_data.get('supplier_name'):
            continue
        matched = by_id.get(item_data.get('order_item_id')) or by_key.get(
            _material_key(
                item_data.get('material_name', ''),
                item_data.get('specification', ''),
                item_data.get('unit', ''),
            )
        )
        item_data['supplier_name'] = (
            (matched.supplier_name if matched else '') or default_supplier
        )

    covered = {
        _material_key(d.get('material_name', ''), d.get('specification', ''), d.get('unit', ''))
        for d in items_data
    }
    try:
        bom_rows = await aggregate_bom_rows(db, po)
    except Exception:  # broad-except: BOM 补全失败不能阻断登记创建
        logger.warning('来料登记补全 BOM 行失败 order_id=%s', po.id, exc_info=True)
        return
    for bom in bom_rows:
        if _material_key(
            bom['material_name'], bom['specification'], bom['unit'],
        ) in covered:
            continue
        bom['supplier_name'] = bom['supplier_name'] or default_supplier
        items_data.append(bom)


async def create_registration(db, purchase_order_id: int, user_id: int | None = None,
                              username: str = '未知', remark: str = '',
                              items_data: list[dict] | None = None) -> dict:
    """创建来料登记"""
    po = await db.get(PurchaseOrder, purchase_order_id)
    if not po:
        raise ValueError("采购订单不存在")

    reg = MaterialRegistration(
        purchase_order_id=purchase_order_id,
        purchase_order_no=po.order_no,
        supplier_id=po.supplier_id,
        supplier_name=po.supplier_name,
        registration_date=datetime.now(UTC).replace(tzinfo=None).date(),
        status='pending',
        remark=remark,
        created_by=user_id,
    )
    db.add(reg)
    await db.flush()

    items_data = list(items_data or [])
    await _enrich_items_with_supplier_and_bom(db, po, items_data)
    for item_data in items_data:
        item = MaterialRegistrationItem(
            registration_id=reg.id,
            order_item_id=item_data.get('order_item_id'),
            material_code=item_data.get('material_code', ''),
            material_name=item_data.get('material_name', ''),
            specification=item_data.get('specification', ''),
            unit=item_data.get('unit', ''),
            ordered_quantity=Decimal(str(item_data.get('ordered_quantity', 0))),
            received_quantity=Decimal(str(item_data.get('received_quantity', 0))),
            material_category=item_data.get('material_category', ''),
            supplier_name=item_data.get('supplier_name') or '',
            remark=item_data.get('remark', ''),
        )
        db.add(item)

    await db.flush()
    return {'success': True, 'message': '来料登记创建成功', 'registration': reg.to_dict()}

async def update_registration(db, reg_id: int, status: str | None = None,
                              remark: str | None = None, items: list[dict] | None = None) -> dict:
    """更新来料登记。

    评审 H5：旧实现只做无锁 ``db.get`` 后直接赋值 ``received_quantity``——任意超收/
    负收都能写库，且与 ``receive_material`` 的 FOR UPDATE 不是同一互斥区间，
    并发时后提交的旧绝对值会覆盖先完成的新值。现在：
    1. 先锁登记行（串行化同一登记下的编辑/收货）；
    2. 明细行按 id 升序一次性 ``FOR UPDATE``（单条 SQL，非逐行），
       再在加锁后的值上校验 ``0 <= 数量 <= 采购数量``；
    3. 与收货链共用同一数量边界，避免两套口径。
    """
    # 先锁登记行：同一登记的所有编辑请求在此串行化。此处只取 id，避免
    # joinedload + FOR UPDATE 触到外连接不可加锁（PostgreSQL 限制）。
    locked = await db.execute(
        select(MaterialRegistration.id)
        .where(MaterialRegistration.id == reg_id)
        .with_for_update()
    )
    if locked.scalar_one_or_none() is None:
        raise ValueError("来料登记不存在")

    result = await db.execute(
        select(MaterialRegistration)
        .options(
            selectinload(MaterialRegistration.items),
            joinedload(MaterialRegistration.purchase_order),
        )
        .where(MaterialRegistration.id == reg_id)
    )
    reg = result.unique().scalar_one_or_none()
    if not reg:
        raise ValueError("来料登记不存在")

    if status is not None:
        reg.status = status
    if remark is not None:
        reg.remark = remark

    if items is not None:
        # 明细行一次性按 id 升序加锁（避免循环内逐条 SELECT 的 N+1，也避免
        # 两个请求以不同顺序加锁而死锁）。未提交 id 的明细不参与更新。
        target_ids = [int(d['id']) for d in items if d.get('id')]
        locked_items: dict[int, MaterialRegistrationItem] = {}
        if target_ids:
            locked_rows = await db.execute(
                select(MaterialRegistrationItem)
                .where(MaterialRegistrationItem.id.in_(target_ids))
                .order_by(MaterialRegistrationItem.id)
                .with_for_update()
            )
            locked_items = {row.id: row for row in locked_rows.scalars().all()}

        for item_data in items:
            item_id = item_data.get('id')
            if not item_id:
                continue
            item = locked_items.get(int(item_id))
            if not item or item.registration_id != reg_id:
                continue
            if 'received_quantity' in item_data:
                raw_qty = item_data['received_quantity']
                try:
                    new_qty = Decimal(str(raw_qty))
                except (InvalidOperation, ValueError) as exc:
                    raise ValueError("收货数量必须为数字") from exc
                if new_qty < 0:
                    raise ValueError("收货数量不能为负数")
                if new_qty > (item.ordered_quantity or Decimal('0')):
                    raise ValueError("收货数量不能超过采购数量")
                # 校验用 Decimal（精确比较），落库前转回 float：模型把这两列声明为
                # Mapped[float]，实际列类型是 Numeric(12,2)，PostgreSQL 入库时按 2 位小数取值
                item.received_quantity = float(new_qty)
            if 'remark' in item_data:
                item.remark = item_data['remark']

    # 自动更新状态
    reg.update_status()

    return {'success': True, 'message': '更新成功', 'registration': reg.to_dict()}

async def delete_registration(db, reg_id: int) -> dict:
    """删除来料登记"""
    reg = await db.get(MaterialRegistration, reg_id)
    if not reg:
        raise ValueError("来料登记不存在")
    await db.delete(reg)
    await db.flush()
    return {'success': True, 'message': '删除成功'}

async def receive_material(db, item_id: int, received_quantity: float,
                           remark: str | None = None) -> dict:
    """物料收货登记

    使用 SELECT ... FOR UPDATE 悲观锁，防止并发收货导致 received_quantity 丢失更新。
    purchase_order 改用 selectinload 单独加载，避免 FOR UPDATE 锁定采购订单表。
    """
    result = await db.execute(
        select(MaterialRegistrationItem)
        .options(
            selectinload(MaterialRegistrationItem.registration).selectinload(MaterialRegistration.items),
            selectinload(MaterialRegistrationItem.registration).selectinload(MaterialRegistration.purchase_order),
        )
        .where(MaterialRegistrationItem.id == item_id)
        .with_for_update()
    )
    item = result.unique().scalar_one_or_none()
    if not item:
        raise ValueError("物料明细不存在")

    if received_quantity <= 0:
        raise ValueError("收货数量必须大于0")

    old_qty = item.received_quantity or Decimal('0')
    new_qty = old_qty + Decimal(str(received_quantity))
    if new_qty > (item.ordered_quantity or Decimal('0')):
        raise ValueError("收货数量不能超过采购数量")
    item.received_quantity = new_qty
    if remark:
        item.remark = remark

    # 更新状态
    reg = item.registration
    reg.update_status()
    await db.flush()

    logger.info("收货登记成功 item_id=%s, %s→%s (+%s), 状态=%s",
                item_id, old_qty, item.received_quantity, received_quantity, reg.status)

    return {
        'success': True, 'message': '收货登记成功',
        'registration': reg.to_dict(),
    }
