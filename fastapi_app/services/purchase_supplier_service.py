"""
采购中心 - 供应商管理服务

从 purchase_center_service.py 拆分，包含供应商 CRUD 及信息同步逻辑。
"""
import logging

from sqlalchemy import func
from sqlalchemy.orm import Session

from fastapi_app.shared_models import (
    MaterialRegistration,
    ProductAccessory,
    ProductFabric,
    ProductMaterial,
    ProductPackaging,
    PurchaseOrder,
    PurchaseOrderItem,
    Supplier,
)

logger = logging.getLogger(__name__)


def get_suppliers(db: Session, with_stats: bool = False) -> list:
    suppliers = db.query(Supplier).order_by(Supplier.name).all()
    # Batch-fetch material counts to avoid N+1 when with_stats=True
    material_counts: dict[int, int] = {}
    if with_stats:
        rows = db.query(
            ProductMaterial.supplier_id,
            func.count(ProductMaterial.id)
        ).group_by(ProductMaterial.supplier_id).all()
        material_counts = dict(rows)

    supplier_list = []
    for supplier in suppliers:
        s_dict = {
            'id': supplier.id,
            'name': supplier.name,
            'contact_person': getattr(supplier, 'contact_person', None),
            'phone': getattr(supplier, 'phone', None),
            'address': getattr(supplier, 'address', None),
        }
        if with_stats:
            s_dict['material_count'] = material_counts.get(supplier.id, 0)
        supplier_list.append(s_dict)
    return supplier_list


def create_supplier(db: Session, data: dict) -> dict:
    existing = db.query(Supplier).filter_by(name=data['name']).first()
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
    db.commit()
    return {'id': supplier.id, 'name': supplier.name}


def update_supplier(db: Session, supplier_id: int, data: dict) -> dict:
    supplier = db.get(Supplier, supplier_id)
    if not supplier:
        raise ValueError('供应商不存在')

    new_name = data.get('name', '').strip()
    if not new_name:
        raise ValueError('供应商名称不能为空')

    existing = db.query(Supplier).filter(Supplier.name == new_name, Supplier.id != supplier_id).first()
    if existing:
        raise ValueError('供应商名称已存在')

    old_name = supplier.name

    supplier.name = new_name
    supplier.contact_person = data.get('contact_person', '')
    supplier.phone = data.get('phone', '')
    supplier.address = data.get('address', '')
    supplier.remark = data.get('remark', '')

    # 同步供应商信息到所有关联表
    _sync_supplier_info(db, supplier, old_name)

    db.commit()
    return {'id': supplier.id, 'name': supplier.name}


def _sync_supplier_info(db: Session, supplier, old_name: str):
    """供应商信息变更后，同步所有冗余的供应商字段到关联表

    同步字段: supplier_name, supplier_contact_person, supplier_phone, supplier_address
    目标表: BOM物料表(仅name), 采购订单(全部4字段), 采购订单明细/来料登记(仅name)
    """
    sid = supplier.id
    new_name = supplier.name
    new_contact = supplier.contact_person
    new_phone = supplier.phone
    new_address = supplier.address
    name_changed = old_name != new_name

    # BOM 物料表 — 按 supplier_id 匹配
    for Model in (ProductMaterial, ProductFabric, ProductAccessory, ProductPackaging):
        db.query(Model).filter_by(supplier_id=sid).update({'supplier_name': new_name})
        if name_changed:
            db.query(Model).filter(
                Model.supplier_name == old_name,
                Model.supplier_id.is_(None)
            ).update({'supplier_name': new_name})

    # 采购订单 — 按 supplier_id 匹配，含全部供应商冗余字段
    db.query(PurchaseOrder).filter_by(supplier_id=sid).update({
        'supplier_name': new_name,
        'supplier_contact_person': new_contact,
        'supplier_phone': new_phone,
        'supplier_address': new_address,
    })
    # 同时按 supplier_name 匹配无 supplier_id 的历史数据
    db.query(PurchaseOrder).filter(
        PurchaseOrder.supplier_name == (new_name if not name_changed else old_name),
        PurchaseOrder.supplier_id.is_(None)
    ).update({
        'supplier_name': new_name,
        'supplier_contact_person': new_contact,
        'supplier_phone': new_phone,
        'supplier_address': new_address,
    })

    # 采购订单明细 — 无 supplier_id，按旧 supplier_name 匹配
    if name_changed:
        db.query(PurchaseOrderItem).filter_by(supplier_name=old_name).update({'supplier_name': new_name})

    # 来料登记 — 按 supplier_id 匹配
    db.query(MaterialRegistration).filter_by(supplier_id=sid).update({'supplier_name': new_name})
    if name_changed:
        db.query(MaterialRegistration).filter(
            MaterialRegistration.supplier_name == old_name,
            MaterialRegistration.supplier_id.is_(None)
        ).update({'supplier_name': new_name})


def delete_supplier(db: Session, supplier_id: int) -> dict:
    supplier = db.get(Supplier, supplier_id)
    if not supplier:
        raise ValueError('供应商不存在')

    has_bom = (
        db.query(ProductMaterial).filter_by(supplier_id=supplier_id).first() or
        db.query(ProductFabric).filter_by(supplier_id=supplier_id).first() or
        db.query(ProductAccessory).filter_by(supplier_id=supplier_id).first() or
        db.query(ProductPackaging).filter_by(supplier_id=supplier_id).first()
    )
    has_orders = db.query(PurchaseOrder).filter_by(supplier_id=supplier_id).first()

    if has_bom or has_orders:
        raise ValueError('该供应商已有相关BOM或采购订单数据，无法删除')

    db.delete(supplier)
    db.commit()
    return {'id': supplier_id, 'name': supplier.name}


def get_supplier_materials(db: Session, supplier_id: int) -> list:
    materials = db.query(ProductMaterial).filter(
        ProductMaterial.supplier_id == supplier_id
    ).order_by(ProductMaterial.name).all()

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
