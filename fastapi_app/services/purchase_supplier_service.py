"""
采购中心 - 供应商管理服务

从 purchase_center_service.py 拆分，包含供应商 CRUD 及信息同步逻辑。
"""
import logging

from sqlalchemy import exists, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from fastapi_app.core.sanitizer import escape_like
from fastapi_app.core.validators import validate_not_empty
from fastapi_app.shared_models import (
    MaterialRegistration,
    ProductAccessory,
    ProductFabric,
    ProductMaterial,
    PurchaseOrder,
    PurchaseOrderItem,
    Supplier,
)

logger = logging.getLogger(__name__)


async def get_supplier_for_update(db: AsyncSession, supplier_id: int) -> Supplier | None:
    """按 ID 取供应商行锁（SELECT ... FOR UPDATE），供切换启用状态等写操作防并发覆盖。"""
    result = await db.execute(
        select(Supplier).where(Supplier.id == supplier_id).with_for_update()
    )
    return result.scalar_one_or_none()


async def get_suppliers(db: AsyncSession, page: int = 1, per_page: int = 50, search: str = '') -> dict:
    query = select(Supplier)
    count_query = select(func.count(Supplier.id))

    if search:
        escaped = escape_like(search)
        like_pattern = f'%{escaped}%'
        query = query.where(Supplier.name.ilike(like_pattern))
        count_query = count_query.where(Supplier.name.ilike(like_pattern))

    total = (await db.execute(count_query)).scalar() or 0

    query = query.order_by(Supplier.name).offset((page - 1) * per_page).limit(per_page)
    result = await db.execute(query)
    suppliers = result.scalars().all()

    supplier_list = []
    for supplier in suppliers:
        s_dict = {
            'id': supplier.id,
            'name': supplier.name,
            'contact_person': getattr(supplier, 'contact_person', None),
            'phone': getattr(supplier, 'phone', None),
            'address': getattr(supplier, 'address', None),
            'remark': getattr(supplier, 'remark', None),
            'status': getattr(supplier, 'status', True),
            'created_at': supplier.created_at.strftime('%Y-%m-%d %H:%M') if supplier.created_at else None,
        }
        supplier_list.append(s_dict)
    return {'items': supplier_list, 'total': total, 'page': page, 'per_page': per_page}


async def create_supplier(db: AsyncSession, data: dict) -> dict:
    result = await db.execute(select(Supplier).where(Supplier.name == data['name']))
    existing = result.scalar_one_or_none()
    if existing:
        raise ValueError('供应商已存在')

    supplier = Supplier(
        name=data['name'],
        contact_person=data.get('contact_person', ''),
        phone=data.get('phone', ''),
        address=data.get('address', ''),
        remark=data.get('remark', ''),
    )
    db.add(supplier)
    await db.flush()
    return {'id': supplier.id, 'name': supplier.name}


async def update_supplier(db: AsyncSession, supplier_id: int, data: dict) -> dict:
    supplier = await db.get(Supplier, supplier_id)
    if not supplier:
        raise ValueError('供应商不存在')

    # PATCH 语义：字段未提供（None）时保留旧值，提供空串表示清空
    # name 字段为 NOT NULL+unique，空串非法，故用 `or` 短路视为"未提供"
    new_name = validate_not_empty(data.get('name') or supplier.name, "供应商名称")

    result = await db.execute(
        select(Supplier).where(Supplier.name == new_name, Supplier.id != supplier_id)
    )
    existing = result.scalar_one_or_none()
    if existing:
        raise ValueError('供应商名称已存在')

    # 记录旧值，用于判断关联表是否需要同步
    old_name = supplier.name
    old_contact = supplier.contact_person
    old_phone = supplier.phone
    old_address = supplier.address

    supplier.name = new_name
    if 'contact_person' in data:
        supplier.contact_person = data['contact_person'] or ''
    if 'phone' in data:
        supplier.phone = data['phone'] or ''
    if 'address' in data:
        supplier.address = data['address'] or ''
    if 'remark' in data:
        supplier.remark = data['remark'] or ''

    await _sync_supplier_info(
        db, supplier, old_name, old_contact, old_phone, old_address
    )

    await db.flush()
    return {'id': supplier.id, 'name': supplier.name}


async def _sync_supplier_info(
    db: AsyncSession, supplier,
    old_name: str, old_contact: str, old_phone: str, old_address: str,
):
    """同步供应商信息到关联表（冗余字段）。

    仅在相关字段实际变更时执行 UPDATE，避免无意义的全表更新。
    - 物料表（ProductMaterial/Fabric/Accessory）、PurchaseOrderItem、MaterialRegistration
      仅冗余 supplier_name，只在 name 变更时同步
    - PurchaseOrder 冗余 name/contact/phone/address，任一变更时同步
    """
    sid = supplier.id
    new_name = supplier.name
    new_contact = supplier.contact_person
    new_phone = supplier.phone
    new_address = supplier.address

    name_changed = old_name != new_name
    contact_changed = old_contact != new_contact
    phone_changed = old_phone != new_phone
    address_changed = old_address != new_address

    # 全部未变时无需任何同步
    if not (name_changed or contact_changed or phone_changed or address_changed):
        return

    # 物料表只存 supplier_name，仅名称变更时同步
    if name_changed:
        for model_cls in (ProductMaterial, ProductFabric, ProductAccessory):
            await db.execute(  # batch-loop: 有意逐行处理,非 N+1
                update(model_cls).where(model_cls.supplier_id == sid).values(supplier_name=new_name)
            )
            await db.execute(  # batch-loop: 有意逐行处理,非 N+1
                update(model_cls).where(
                    model_cls.supplier_name == old_name,
                    model_cls.supplier_id.is_(None)
                ).values(supplier_name=new_name)
            )

    # PurchaseOrder 冗余了 name/contact/phone/address
    await db.execute(
        update(PurchaseOrder).where(PurchaseOrder.supplier_id == sid).values(
            supplier_name=new_name,
            supplier_contact_person=new_contact,
            supplier_phone=new_phone,
            supplier_address=new_address,
        )
    )
    if name_changed:
        await db.execute(
            update(PurchaseOrder).where(
                PurchaseOrder.supplier_name == old_name,
                PurchaseOrder.supplier_id.is_(None)
            ).values(
                supplier_name=new_name,
                supplier_contact_person=new_contact,
                supplier_phone=new_phone,
                supplier_address=new_address,
            )
        )

    if name_changed:
        await db.execute(
            update(PurchaseOrderItem).where(
                PurchaseOrderItem.supplier_name == old_name
            ).values(supplier_name=new_name)
        )

        await db.execute(
            update(MaterialRegistration).where(
                MaterialRegistration.supplier_id == sid
            ).values(supplier_name=new_name)
        )
        await db.execute(
            update(MaterialRegistration).where(
                MaterialRegistration.supplier_name == old_name,
                MaterialRegistration.supplier_id.is_(None)
            ).values(supplier_name=new_name)
        )


async def delete_supplier(db: AsyncSession, supplier_id: int) -> dict:
    supplier = await db.get(Supplier, supplier_id)
    if not supplier:
        raise ValueError('供应商不存在')

    # 单次查询检查所有关联表，避免 4 次串行往返
    exists_check = await db.execute(
        select(
            exists().where(ProductMaterial.supplier_id == supplier_id),
            exists().where(ProductFabric.supplier_id == supplier_id),
            exists().where(ProductAccessory.supplier_id == supplier_id),
            exists().where(PurchaseOrder.supplier_id == supplier_id),
        )
    )
    has_material, has_fabric, has_accessory, has_order = exists_check.one()

    if has_material or has_fabric or has_accessory or has_order:
        raise ValueError('该供应商已有相关BOM或采购订单数据，无法删除')

    await db.delete(supplier)
    await db.flush()
    return {'id': supplier_id, 'name': supplier.name}
