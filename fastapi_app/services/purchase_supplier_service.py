"""
采购中心 - 供应商管理服务

从 purchase_center_service.py 拆分，包含供应商 CRUD 及信息同步逻辑。
"""
import logging
from datetime import UTC, datetime

from sqlalchemy import exists, func, insert, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from fastapi_app.core.business_time import fmt_business
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
            'created_at': fmt_business(supplier.created_at) or None,
        }
        supplier_list.append(s_dict)
    return {'items': supplier_list, 'total': total, 'page': page, 'per_page': per_page}


# 供应商名称列长度上限（shared_models/supplier.py：String(100)）
_SUPPLIER_NAME_MAX_LEN = 100


async def list_supplier_options(db: AsyncSession) -> list[dict]:
    """供应商下拉选项（id + 名称），按名称排序。

    供 BOM 配置等选择器使用：刻意**不做缓存**，保证「实时」反映最新供应商表。
    不过滤 status（与 catalog store 走 /suppliers/list 的口径一致，停用供应商仍可选择沿用）。
    """
    result = await db.execute(select(Supplier.id, Supplier.name).order_by(Supplier.name))
    return [{'id': sid, 'name': name} for sid, name in result.all()]


async def resolve_bom_suppliers(db: AsyncSession, names) -> dict[str, int]:
    """把 BOM 物料引用的供应商名解析为 supplier.id 映射，缺失的按名建卡。

    - trim + 去重 + 忽略空名；
    - 名称超过 ``_SUPPLIER_NAME_MAX_LEN`` 直接抛 ValueError（调用端点经 db_transaction
      的默认映射转 400，不会以「有 supplier_name 却无 supplier_id」的半成品状态落库）；
    - 已存在（含停用）一律复用，绝不重复建；
    - 建卡用 savepoint（begin_nested）兜底并发：两个请求同时建同名时，后者撞唯一约束
      只回滚该 savepoint 并回查，不污染外层 BOM 保存事务。

    Args:
        db: 异步会话（调用方须处于同一事务内）。
        names: 供应商名称可迭代对象（含 None / 空白，自动忽略）。

    Returns:
        dict[str, int]: 规整后的名称 -> supplier.id。

    Raises:
        ValueError: 存在超过长度上限的名称。
    """
    cleaned = {(n or '').strip() for n in names}
    cleaned.discard('')
    if not cleaned:
        return {}

    oversized = [n for n in cleaned if len(n) > _SUPPLIER_NAME_MAX_LEN]
    if oversized:
        raise ValueError(f'供应商名称过长（超过{_SUPPLIER_NAME_MAX_LEN}字符）：{oversized[0][:30]}')

    existing = (
        await db.execute(select(Supplier.id, Supplier.name).where(Supplier.name.in_(cleaned)))
    ).all()
    mapping: dict[str, int] = {name: sid for sid, name in existing}

    missing = cleaned - set(mapping)
    if missing:
        now = datetime.now(UTC)
        for name in sorted(missing):
            try:
                async with db.begin_nested():
                    await db.execute(insert(Supplier).values(
                        name=name, status=True, created_at=now, updated_at=now,
                    ))
            except IntegrityError:
                # 并发请求抢先建同名 → 回查即可（savepoint 已回滚，外层事务不受影响）
                pass
        re_rows = (
            await db.execute(select(Supplier.id, Supplier.name).where(Supplier.name.in_(missing)))
        ).all()
        mapping.update({name: sid for sid, name in re_rows})
    return mapping


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
    old_name: str, old_contact: str | None, old_phone: str | None, old_address: str | None,
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

    # 单次查询检查所有关联表，避免 5 次串行往返（Z02-R7：补来料登记引用）
    exists_check = await db.execute(
        select(
            exists().where(ProductMaterial.supplier_id == supplier_id),
            exists().where(ProductFabric.supplier_id == supplier_id),
            exists().where(ProductAccessory.supplier_id == supplier_id),
            exists().where(PurchaseOrder.supplier_id == supplier_id),
            exists().where(MaterialRegistration.supplier_id == supplier_id),
        )
    )
    has_material, has_fabric, has_accessory, has_order, has_registration = exists_check.one()

    if has_material or has_fabric or has_accessory or has_order or has_registration:
        raise ValueError('该供应商已有相关BOM、采购订单或来料登记数据，无法删除')

    await db.delete(supplier)
    await db.flush()
    return {'id': supplier_id, 'name': supplier.name}
