"""
采购中心 - 供应商管理服务

从 purchase_center_service.py 拆分，包含供应商 CRUD 及信息同步逻辑。
"""
import logging

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

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


async def get_suppliers(db: AsyncSession, with_stats: bool = False, page: int = 1, per_page: int = 50, search: str = '') -> dict:
    query = select(Supplier)
    count_query = select(func.count(Supplier.id))

    if search:
        from fastapi_app.services import escape_like
        escaped = escape_like(search)
        like_pattern = f'%{escaped}%'
        query = query.where(Supplier.name.ilike(like_pattern))
        count_query = count_query.where(Supplier.name.ilike(like_pattern))

    total = (await db.execute(count_query)).scalar() or 0

    query = query.order_by(Supplier.name).offset((page - 1) * per_page).limit(per_page)
    result = await db.execute(query)
    suppliers = result.scalars().all()

    material_counts: dict[int, int] = {}
    if with_stats:
        rows_result = await db.execute(
            select(
                ProductMaterial.supplier_id,
                func.count(ProductMaterial.id)
            ).group_by(ProductMaterial.supplier_id)
        )
        material_counts = {row[0]: row[1] for row in rows_result}

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
        if with_stats:
            s_dict['material_count'] = material_counts.get(supplier.id, 0)
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
    await db.commit()
    return {'id': supplier.id, 'name': supplier.name}


async def update_supplier(db: AsyncSession, supplier_id: int, data: dict) -> dict:
    supplier = await db.get(Supplier, supplier_id)
    if not supplier:
        raise ValueError('供应商不存在')

    new_name = data.get('name', '').strip()
    if not new_name:
        raise ValueError('供应商名称不能为空')

    result = await db.execute(
        select(Supplier).where(Supplier.name == new_name, Supplier.id != supplier_id)
    )
    existing = result.scalar_one_or_none()
    if existing:
        raise ValueError('供应商名称已存在')

    old_name = supplier.name

    supplier.name = new_name
    supplier.contact_person = data.get('contact_person', '')
    supplier.phone = data.get('phone', '')
    supplier.address = data.get('address', '')
    supplier.remark = data.get('remark', '')

    await _sync_supplier_info(db, supplier, old_name)

    await db.commit()
    return {'id': supplier.id, 'name': supplier.name}


async def _sync_supplier_info(db: AsyncSession, supplier, old_name: str):
    sid = supplier.id
    new_name = supplier.name
    new_contact = supplier.contact_person
    new_phone = supplier.phone
    new_address = supplier.address
    name_changed = old_name != new_name

    for model_cls in (ProductMaterial, ProductFabric, ProductAccessory):
        await db.execute(
            update(model_cls).where(model_cls.supplier_id == sid).values(supplier_name=new_name)
        )
        if name_changed:
            await db.execute(
                update(model_cls).where(
                    model_cls.supplier_name == old_name,
                    model_cls.supplier_id.is_(None)
                ).values(supplier_name=new_name)
            )

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
    if name_changed:
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

    has_bom = (
        await db.execute(select(ProductMaterial).where(ProductMaterial.supplier_id == supplier_id).limit(1))
    ).scalar_one_or_none() or (
        await db.execute(select(ProductFabric).where(ProductFabric.supplier_id == supplier_id).limit(1))
    ).scalar_one_or_none() or (
        await db.execute(select(ProductAccessory).where(ProductAccessory.supplier_id == supplier_id).limit(1))
    ).scalar_one_or_none()

    has_orders = (
        await db.execute(select(PurchaseOrder).where(PurchaseOrder.supplier_id == supplier_id).limit(1))
    ).scalar_one_or_none()

    if has_bom or has_orders:
        raise ValueError('该供应商已有相关BOM或采购订单数据，无法删除')

    await db.delete(supplier)
    await db.commit()
    return {'id': supplier_id, 'name': supplier.name}


async def get_supplier_materials(db: AsyncSession, supplier_id: int) -> list:
    result = await db.execute(
        select(ProductMaterial).where(
            ProductMaterial.supplier_id == supplier_id
        ).order_by(ProductMaterial.name)
    )
    materials = result.scalars().all()

    return [
        {
            'id': m.id,
            'code': getattr(m, 'code', None),
            'name': m.name if hasattr(m, 'name') else getattr(m, 'cotton_usage', None),
            'specification': getattr(m, 'specification', None),
            'unit': getattr(m, 'unit', None),
            'stock': getattr(m, 'stock', 0),
        }
        for m in materials
    ]
