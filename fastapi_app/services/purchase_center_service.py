"""
采购中心服务层 - 业务逻辑

从 Flask app/routes/purchase_center.py 迁移，功能完全一致。
使用同步数据库会话 (SyncSession)，与现有 purchase_center endpoint 一致。
"""

import json
import logging
import math
import re
from datetime import datetime, timedelta, date
from decimal import Decimal
from typing import Optional

from sqlalchemy import or_, and_, func, text
from sqlalchemy.orm import Session, joinedload, selectinload

from fastapi_app.shared_models import (
    Product, Order, Customer,
    PurchaseOrder, PurchaseOrderItem,
    ProductMaterial, ProductFabric, ProductAccessory, ProductPackaging,
    Supplier, ModificationLog, SavedQuery, OrderStatusLog,
    MaterialRegistration, MaterialRegistrationItem,
    MATERIAL_CATEGORIES,
)
from fastapi_app.services import escape_like

logger = logging.getLogger(__name__)


def _product_has_bom(product) -> bool:
    """判断产品是否配置了BOM（任意一类物料有数据即视为有BOM）"""
    has_filling = (
        product.material is not None and
        getattr(product.material, 'cotton_usage', Decimal('0')) > 0
    )
    has_fabric = hasattr(product, 'fabrics') and len(product.fabrics) > 0
    has_accessory = hasattr(product, 'accessories') and len(product.accessories) > 0
    has_packaging = hasattr(product, 'packagings') and len(product.packagings) > 0
    return has_filling or has_fabric or has_accessory or has_packaging


# ============================================================
# 产品/BOM API
# ============================================================

def get_products(db: Session, *, page: int = 1, per_page: int = 50,
                 search: str = '', has_bom: str = 'all', category: str = '',
                 sort_by: str = 'name', sort_order: str = 'asc') -> dict:
    query = db.query(Product)

    if search:
        query = query.filter(
            or_(
                Product.name.ilike(f'%{escape_like(search)}%'),
                Product.barcode.ilike(f'%{escape_like(search)}%')
            )
        )

    if has_bom == 'true':
        query = query.filter(Product.material.has())
    elif has_bom == 'false':
        query = query.filter(~Product.material.has())

    if category:
        if category == 'filling':
            query = query.filter(Product.material.has())
        elif category == 'fabric':
            query = query.filter(Product.fabrics.any())
        elif category == 'accessory':
            query = query.filter(Product.accessories.any())
        elif category == 'packaging':
            query = query.filter(Product.packagings.any())

    sort_map = {
        'name': Product.name,
        'barcode': Product.barcode,
        'create_time': Product.create_time,
    }
    sort_col = sort_map.get(sort_by, Product.name)
    if sort_order == 'desc':
        sort_col = sort_col.desc()
    query = query.order_by(sort_col)

    total = query.count()
    products = query.offset((page - 1) * per_page).limit(per_page).all()

    result = []
    for p in products:
        has_bom_flag = p.has_bom()
        bom_info = {}
        if has_bom_flag:
            all_mats = p.get_all_materials()
            bom_info = {
                'filling_count': len([m for m in all_mats if m.get('category') == 'filling']),
                'fabric_count': len([m for m in all_mats if m.get('category') == 'fabric']),
                'accessory_count': len([m for m in all_mats if m.get('category') == 'accessory']),
                'packaging_count': len([m for m in all_mats if m.get('category') == 'packaging']),
            }
        result.append({
            'id': p.id,
            'name': p.name,
            'barcode': p.barcode,
            'price': float(p.price) if p.price else 0,
            'has_bom': has_bom_flag,
            'bom_info': bom_info,
            'current_stock': p.current_stock,
        })

    return {
        'products': result,
        'total': total,
        'pages': (total + per_page - 1) // per_page if per_page > 0 else 0,
        'current_page': page,
    }


def get_products_batch_bom(db: Session, product_ids_str: str) -> dict:
    if not product_ids_str:
        return {'products': {}}

    try:
        pid_list = [int(x) for x in product_ids_str.split(',') if x.strip().isdigit()]
    except ValueError:
        return {'products': {}}

    products = db.query(Product).filter(Product.id.in_(pid_list)).all()
    result = {}
    for p in products:
        if p.has_bom():
            all_mats = p.get_all_materials()
            result[str(p.id)] = {
                'name': p.name,
                'barcode': p.barcode,
                'materials': all_mats,
            }
    return {'products': result}


def get_search_suggestions(db: Session, keyword: str) -> list:
    if not keyword or len(keyword) < 1:
        return []

    products = db.query(Product).filter(
        or_(
            Product.name.ilike(f'%{escape_like(keyword)}%'),
            Product.barcode.ilike(f'%{escape_like(keyword)}%')
        )
    ).limit(10).all()

    return [
        {'id': p.id, 'name': p.name, 'barcode': p.barcode, 'price': float(p.price) if p.price else 0, 'has_bom': p.has_bom()}
        for p in products
    ]


def get_products_statistics(db: Session) -> dict:
    total = db.query(Product).count()
    has_bom = db.query(Product).filter(Product.material.has()).count()
    return {
        'total': total,
        'has_bom': has_bom,
        'no_bom': total - has_bom,
    }


def get_product_bom(db: Session, product_id: int) -> dict:
    product = db.get(Product, product_id)
    if not product:
        return None
    all_materials = product.get_all_materials() if product.has_bom() else []
    return {
        'id': product.id,
        'name': product.name,
        'barcode': product.barcode,
        'materials': all_materials,
    }


def save_product_bom(db: Session, product_id: int, data: dict, username: str) -> str:
    product = db.get(Product, product_id)
    if not product:
        raise ValueError('产品不存在')

    filling_data = data.get('filling')
    if filling_data:
        if product.material:
            old_data = {
                'cotton_usage': float(product.material.cotton_usage) if product.material.cotton_usage else 0,
                'supplier_name': product.material.supplier_name,
            }
            product.material.cotton_usage = Decimal(str(filling_data.get('cotton_usage', 0)))
            product.material.supplier_id = filling_data.get('supplier_id')
            product.material.supplier_name = filling_data.get('supplier_name', '')
            product.material.specification = filling_data.get('specification', '')
            product.material.remark = filling_data.get('remark', '')
            new_data = {
                'cotton_usage': float(product.material.cotton_usage),
                'supplier_name': product.material.supplier_name,
            }
            if old_data != new_data:
                mod = ModificationLog(
                    target_type='material', target_id=product.material.id,
                    field_name='filling_data',
                    old_value=json.dumps(old_data, ensure_ascii=False),
                    new_value=json.dumps(new_data, ensure_ascii=False),
                    modifier_name=username,
                )
                db.add(mod)
        else:
            mat = ProductMaterial(
                product_id=product_id,
                cotton_usage=Decimal(str(filling_data.get('cotton_usage', 0))),
                supplier_id=filling_data.get('supplier_id'),
                supplier_name=filling_data.get('supplier_name', ''),
                specification=filling_data.get('specification', ''),
                remark=filling_data.get('remark', ''),
            )
            db.add(mat)

    fabrics_data = data.get('fabrics', [])
    for fab_data in fabrics_data:
        if fab_data.get('id'):
            fab = db.get(ProductFabric, fab_data['id'])
            if fab and fab.product_id == product_id:
                old_val = fab.fabric_name
                fab.fabric_name = fab_data.get('fabric_name', '')
                fab.quantity = Decimal(str(fab_data.get('quantity', 0)))
                fab.supplier_id = fab_data.get('supplier_id')
                fab.supplier_name = fab_data.get('supplier_name', '')
                fab.specification = fab_data.get('specification', '')
                fab.remark = fab_data.get('remark', '')
                if old_val != fab.fabric_name:
                    db.add(ModificationLog(
                        target_type='material', target_id=fab.id,
                        field_name='fabric_name', old_value=old_val,
                        new_value=fab.fabric_name, modifier_name=username,
                    ))
        else:
            db.add(ProductFabric(
                product_id=product_id,
                fabric_name=fab_data.get('fabric_name', ''),
                quantity=Decimal(str(fab_data.get('quantity', 0))),
                supplier_id=fab_data.get('supplier_id'),
                supplier_name=fab_data.get('supplier_name', ''),
                specification=fab_data.get('specification', ''),
                remark=fab_data.get('remark', ''),
            ))

    accessories_data = data.get('accessories', [])
    for acc_data in accessories_data:
        if acc_data.get('id'):
            acc = db.get(ProductAccessory, acc_data['id'])
            if acc and acc.product_id == product_id:
                old_val = acc.accessory_name
                acc.accessory_name = acc_data.get('accessory_name', '')
                acc.quantity = Decimal(str(acc_data.get('quantity', 1)))
                acc.supplier_id = acc_data.get('supplier_id')
                acc.supplier_name = acc_data.get('supplier_name', '')
                acc.specification = acc_data.get('specification', '')
                acc.remark = acc_data.get('remark', '')
                if old_val != acc.accessory_name:
                    db.add(ModificationLog(
                        target_type='material', target_id=acc.id,
                        field_name='accessory_name', old_value=old_val,
                        new_value=acc.accessory_name, modifier_name=username,
                    ))
        else:
            db.add(ProductAccessory(
                product_id=product_id,
                accessory_name=acc_data.get('accessory_name', ''),
                quantity=Decimal(str(acc_data.get('quantity', 1))),
                supplier_id=acc_data.get('supplier_id'),
                supplier_name=acc_data.get('supplier_name', ''),
                specification=acc_data.get('specification', ''),
                material_category=acc_data.get('material_category', 'accessory'),
                remark=acc_data.get('remark', ''),
            ))

    packagings_data = data.get('packagings', [])
    for pkg_data in packagings_data:
        if pkg_data.get('id'):
            pkg = db.get(ProductPackaging, pkg_data['id'])
            if pkg and pkg.product_id == product_id:
                old_val = pkg.packaging_name
                pkg.packaging_name = pkg_data.get('packaging_name', '')
                pkg.quantity = Decimal(str(pkg_data.get('quantity', 1)))
                pkg.supplier_id = pkg_data.get('supplier_id')
                pkg.supplier_name = pkg_data.get('supplier_name', '')
                pkg.specification = pkg_data.get('specification', '')
                pkg.remark = pkg_data.get('remark', '')
                if old_val != pkg.packaging_name:
                    db.add(ModificationLog(
                        target_type='material', target_id=pkg.id,
                        field_name='packaging_name', old_value=old_val,
                        new_value=pkg.packaging_name, modifier_name=username,
                    ))
        else:
            db.add(ProductPackaging(
                product_id=product_id,
                packaging_name=pkg_data.get('packaging_name', ''),
                quantity=Decimal(str(pkg_data.get('quantity', 1))),
                supplier_id=pkg_data.get('supplier_id'),
                supplier_name=pkg_data.get('supplier_name', ''),
                specification=pkg_data.get('specification', ''),
                remark=pkg_data.get('remark', ''),
            ))

    db.commit()
    return 'BOM数据保存成功'


# ============================================================
# 物料计算
# ============================================================

def calculate_material(db: Session, orders_data: list) -> dict:
    result_by_category = {
        'filling': [], 'fabric': [], 'accessory': [], 'packaging': [],
    }
    aggregated = {}

    for order_item in orders_data:
        product_id = order_item.get('product_id')
        quantity = order_item.get('quantity', 0)
        if not product_id or quantity <= 0:
            continue

        product = db.get(Product, product_id)
        if not product or not product.has_bom():
            continue

        all_materials = product.get_all_materials()
        for mat in all_materials:
            unit_usage = float(mat.get('unit_usage', 0))
            total_usage = quantity * unit_usage

            agg_key = f"{mat.get('material_code', '')}_{mat.get('material_name', '')}_{mat.get('supplier_name', '')}"
            if agg_key in aggregated:
                aggregated[agg_key]['total_quantity'] += total_usage
                aggregated[agg_key]['order_items'].append({
                    'product_name': product.name, 'quantity': quantity, 'unit_usage': unit_usage,
                })
            else:
                aggregated[agg_key] = {
                    'material_code': mat.get('material_code', ''),
                    'material_name': mat.get('material_name', ''),
                    'specification': mat.get('specification', ''),
                    'unit': mat.get('unit', ''),
                    'supplier_id': mat.get('supplier_id'),
                    'supplier_name': mat.get('supplier_name', ''),
                    'category': mat.get('category', ''),
                    'unit_usage': unit_usage,
                    'total_quantity': total_usage,
                    'order_items': [{
                        'product_name': product.name, 'quantity': quantity, 'unit_usage': unit_usage,
                    }],
                }

    for agg_data in aggregated.values():
        cat = agg_data['category']
        if cat in result_by_category:
            result_by_category[cat].append(agg_data)

    for cat in result_by_category:
        result_by_category[cat].sort(key=lambda x: x.get('total_quantity', 0), reverse=True)

    return {
        'result': result_by_category,
        'total_categories': {cat: len(items) for cat, items in result_by_category.items()},
    }


# ============================================================
# 供应商 API
# ============================================================

def get_suppliers(db: Session, with_stats: bool = False) -> list:
    suppliers = db.query(Supplier).order_by(Supplier.name).all()
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
            material_count = db.query(ProductMaterial).filter(
                ProductMaterial.supplier_id == supplier.id
            ).count()
            s_dict['material_count'] = material_count
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
    from fastapi_app.shared_models import MaterialRegistration
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


# ============================================================
# 客户管理 API (采购中心接入)
# ============================================================

def get_customers(db: Session, *, page: int = 1, per_page: int = 20,
                  status: str = 'all', keyword: str = '',
                  sort_by: str = 'name', sort_order: str = 'asc') -> dict:
    query = db.query(Customer)

    if status == 'active':
        query = query.filter(Customer.status == True)
    elif status == 'inactive':
        query = query.filter(Customer.status == False)

    if keyword:
        query = query.filter(
            or_(
                Customer.name.ilike(f'%{escape_like(keyword)}%'),
                Customer.customer_code.ilike(f'%{escape_like(keyword)}%'),
                Customer.contact.ilike(f'%{escape_like(keyword)}%'),
                Customer.phone.ilike(f'%{escape_like(keyword)}%'),
            )
        )

    sort_map = {
        'name': Customer.name,
        'create_time': Customer.create_time,
        'update_time': Customer.update_time,
    }
    sort_col = sort_map.get(sort_by, Customer.name)
    if sort_order == 'desc':
        sort_col = sort_col.desc()
    query = query.order_by(sort_col)

    total = query.count()
    customers = query.offset((page - 1) * per_page).limit(per_page).all()

    return {
        'customers': [c.to_dict() for c in customers],
        'total': total,
        'pages': (total + per_page - 1) // per_page if per_page > 0 else 0,
        'current_page': page,
        'per_page': per_page,
    }


def get_customer_detail(db: Session, customer_id: int) -> Optional[dict]:
    customer = db.get(Customer, customer_id)
    if not customer:
        return None
    return customer.to_dict()


def batch_get_customers(db: Session, ids: list) -> list:
    if not ids:
        return []
    valid_ids = [int(x) for x in ids if str(x).isdigit()]
    if not valid_ids:
        return []
    customers = db.query(Customer).filter(Customer.id.in_(valid_ids)).all()
    return [c.to_dict() for c in customers]


def get_customers_statistics(db: Session) -> dict:
    total = db.query(Customer).count()
    active = db.query(Customer).filter(Customer.status == True).count()
    recent_time = datetime.now() - timedelta(days=7)
    recent_updated = db.query(Customer).filter(
        Customer.update_time >= recent_time
    ).count()
    return {
        'total': total,
        'active': active,
        'inactive': total - active,
        'recent_updated': recent_updated,
    }


# ============================================================
# 采购订单 API
# ============================================================

def _generate_order_no(db: Session, prefix: str) -> str:
    # 查找当天所有匹配前缀的订单号，用正则提取最大序号，避免异常格式订单号导致崩溃
    pattern = re.compile(rf'^{re.escape(prefix)}(\d+)')
    orders = db.query(PurchaseOrder.order_no).filter(
        PurchaseOrder.order_no.like(f"{prefix}%")
    ).all()

    max_num = 0
    for (order_no,) in orders:
        match = pattern.match(order_no)
        if match:
            num = int(match.group(1))
            max_num = max(max_num, num)

    return f"{prefix}{max_num + 1:04d}"


def create_purchase_order(db: Session, data: dict, user_id: int, username: str) -> dict:
    materials = data.get('materials', [])
    customer_id = data.get('customer_id')
    customer_name = data.get('customer_name', '')
    customer_code = data.get('customer_code', '')
    remark = data.get('remark', '')
    unprocessed_order_id = data.get('unprocessed_order_id')

    if not materials:
        raise ValueError('物料列表不能为空')

    # 从源订单获取产品名称和数量
    source_product_name = None
    source_quantity = None
    if unprocessed_order_id:
        source_order = db.get(Order, unprocessed_order_id)
        if source_order:
            if source_order.product:
                source_product_name = source_order.product.name
            source_quantity = source_order.quantity

    # 按供应商分组
    supplier_groups = {}
    for mat in materials:
        sid = mat.get('supplier_id') or 0
        sname = mat.get('supplier_name', '未指定供应商')
        group_key = (sid, sname) if sid == 0 else sid
        if group_key not in supplier_groups:
            supplier_groups[group_key] = {
                'supplier_id': sid,
                'supplier_name': sname,
                'items': [],
            }
        supplier_groups[group_key]['items'].append(mat)

    created_orders = []
    today = datetime.now()
    prefix = f"BF{today.strftime('%Y%m%d')}"

    for sid, group in supplier_groups.items():
        order_no = _generate_order_no(db, prefix)

        order = PurchaseOrder(
            order_no=order_no,
            supplier_id=group['supplier_id'] or None,
            supplier_name=group['supplier_name'],
            customer_id=customer_id,
            customer_name=customer_name,
            customer_code=customer_code,
            order_date=today.date(),
            status='pending',
            remark=remark,
            source_order_id=unprocessed_order_id,
            created_by=user_id,
            product_name=source_product_name,
            product_quantity=source_quantity,
        )
        db.add(order)
        db.flush()

        for mat_data in group['items']:
            item = PurchaseOrderItem(
                order_id=order.id,
                material_code=mat_data.get('material_code', ''),
                material_name=mat_data.get('material_name', ''),
                specification=mat_data.get('specification', ''),
                unit=mat_data.get('unit', ''),
                quantity=Decimal(str(mat_data.get('total_quantity', 0))),
                unit_usage=Decimal(str(mat_data.get('unit_usage', 0))),
                material_category=mat_data.get('category', ''),
                supplier_name=mat_data.get('supplier_name', '') or group.get('supplier_name', ''),
                remark=mat_data.get('remark', ''),
            )
            db.add(item)

        created_orders.append(order.to_dict())

    db.commit()

    # 更新源订单状态
    if unprocessed_order_id:
        try:
            order_obj = db.get(Order, unprocessed_order_id)
            if order_obj:
                order_obj.status = '部分备货'
                db.commit()
        except Exception as e:
            logger.warning(f"更新未处理订单状态失败: {e}")

    return {
        'orders': created_orders,
        'message': f'成功创建 {len(created_orders)} 张采购订单',
    }


def one_click_generate_order(db: Session, order_ids: list, user_id: int, username: str) -> dict:
    generated_orders = []
    errors = []

    for order_id in order_ids:
        try:
            order = db.get(Order, order_id)
            if not order:
                errors.append(f'订单ID {order_id} 不存在')
                continue

            product = order.product
            if not product:
                errors.append(f'订单 {order.order_no} 的产品不存在')
                continue

            if not product.has_bom():
                errors.append(f'订单 {order.order_no} 的产品缺少BOM配置')
                continue

            all_materials = product.get_all_materials()
            if not all_materials:
                errors.append(f'订单 {order.order_no} 的产品无物料配置')
                continue

            # 计算物料用量
            order_items = []
            for mat in all_materials:
                unit_usage = Decimal(str(mat.get('quantity', 0)))
                total_quantity = Decimal(str(order.quantity)) * unit_usage
                order_items.append({
                    'material_code': mat.get('material_code', ''),
                    'material_name': mat.get('material_name', ''),
                    'specification': mat.get('specification', ''),
                    'quantity': total_quantity,
                    'unit': mat.get('unit', ''),
                    'unit_usage': float(unit_usage),
                    'material_category': mat.get('material_category', ''),
                    'supplier_id': mat.get('supplier_id'),
                    'supplier_name': mat.get('supplier_name', ''),
                })

            # 按供应商分组（仅按 supplier_id 分组；无 supplier_id 的物料合并为一组）
            supplier_groups = {}
            for item in order_items:
                sid = item.get('supplier_id') or 0
                sname = item.get('supplier_name', '未指定供应商')
                # 未关联正式供应商(supplier_id为空)的物料统一归入同一组，避免按文本名称拆分
                group_key = sid if sid else 0
                if group_key not in supplier_groups:
                    supplier_groups[group_key] = {
                        'supplier_id': sid,
                        'supplier_name': sname if sid else '未指定供应商',
                        'items': [],
                    }
                supplier_groups[group_key]['items'].append(item)

            today = datetime.now()
            prefix = f"BF{today.strftime('%Y%m%d')}"

            for idx, (group_key, group) in enumerate(supplier_groups.items()):
                order_no = _generate_order_no(db, prefix)

                po = PurchaseOrder(
                    order_no=order_no if len(supplier_groups) == 1 else f"{order_no}-{idx + 1}",
                    supplier_id=group['supplier_id'] or None,
                    supplier_name=group['supplier_name'],
                    customer_name=order.customer,
                    order_date=today.date(),
                    status='pending',
                    source_order_id=order.id,
                    remark=f'一键生成 - {order.order_no}',
                    created_by=user_id,
                    product_name=product.name if product else None,
                    product_quantity=order.quantity,
                )
                db.add(po)
                db.flush()

                for item_data in group['items']:
                    db.add(PurchaseOrderItem(
                        order_id=po.id,
                        material_code=item_data['material_code'],
                        material_name=item_data['material_name'],
                        specification=item_data['specification'],
                        quantity=item_data['quantity'],
                        unit=item_data['unit'],
                        unit_usage=item_data['unit_usage'],
                        material_category=item_data['material_category'],
                        supplier_name=item_data.get('supplier_name', '') or group.get('supplier_name', ''),
                    ))

                generated_orders.append(po.to_dict())

            order.status = '已备货'

        except Exception as e:
            errors.append(f'处理订单ID {order_id} 时出错: {str(e)}')
            logger.exception(f"一键生成订单失败 (订单ID: {order_id}): {str(e)}")

    db.commit()

    result = {
        'generated_count': len(generated_orders),
        'orders': generated_orders,
        'message': f'成功生成 {len(generated_orders)} 张采购订单',
    }
    if errors:
        result['warnings'] = errors
    return result


def get_purchase_orders(db: Session, *, page: int = 1, per_page: int = 20,
                        status: str = '', customer: str = '', product_name: str = '',
                        start_date: str = '', end_date: str = '',
                        order_no: str = '', supplier: str = '') -> dict:
    query = db.query(PurchaseOrder).options(selectinload(PurchaseOrder.items))

    if not status:
        query = query.filter(PurchaseOrder.status != '已完成')
    if status:
        query = query.filter(PurchaseOrder.status == status)
    if customer:
        query = query.filter(PurchaseOrder.customer_name.ilike(f'%{escape_like(customer)}%'))
    if start_date:
        try:
            sd = datetime.strptime(start_date, '%Y-%m-%d').date()
            query = query.filter(PurchaseOrder.order_date >= sd)
        except ValueError:
            pass
    if end_date:
        try:
            ed = datetime.strptime(end_date, '%Y-%m-%d').date()
            query = query.filter(PurchaseOrder.order_date <= ed)
        except ValueError:
            pass
    if order_no:
        query = query.filter(PurchaseOrder.order_no.ilike(f'%{escape_like(order_no)}%'))
    if supplier:
        query = query.filter(PurchaseOrder.supplier_name.ilike(f'%{escape_like(supplier)}%'))
    if product_name:
        query = query.filter(
            PurchaseOrder.items.any(PurchaseOrderItem.material_name.ilike(f'%{escape_like(product_name)}%'))
        )

    query = query.order_by(PurchaseOrder.create_time.desc())
    total = query.count()
    orders = query.offset((page - 1) * per_page).limit(per_page).all()

    return {
        'orders': [o.to_dict() for o in orders],
        'total': total,
        'pages': (total + per_page - 1) // per_page if per_page > 0 else 0,
        'current_page': page,
    }


def get_purchase_order(db: Session, order_id: int) -> Optional[dict]:
    order = db.get(PurchaseOrder, order_id)
    if not order:
        return None
    return order.to_dict()


def update_purchase_order(db: Session, order_id: int, data: dict, username: str) -> Optional[dict]:
    order = db.get(PurchaseOrder, order_id)
    if not order:
        return None

    modifiable_fields = ['status', 'remark', 'supplier_name', 'customer_name']
    for field in modifiable_fields:
        if field in data:
            old_val = getattr(order, field)
            new_val = data[field]
            if str(old_val) != str(new_val):
                db.add(ModificationLog(
                    target_type='purchase_order', target_id=order_id,
                    field_name=field, old_value=str(old_val), new_value=str(new_val),
                    modifier_name=username, modify_reason=data.get('modify_reason', ''),
                ))
                setattr(order, field, new_val)

    order.update_time = datetime.now()
    db.commit()
    return order.to_dict()


def delete_purchase_order(db: Session, order_id: int) -> Optional[str]:
    order = db.get(PurchaseOrder, order_id)
    if not order:
        return None

    source_order_id = order.source_order_id
    db.delete(order)
    db.commit()

    if source_order_id:
        try:
            order_obj = db.get(Order, source_order_id)
            if order_obj and order_obj.status in ['部分备货', '已备货']:
                order_obj.status = '待备货'
                db.commit()
        except Exception as e:
            logger.warning(f"回滚订单状态失败: {e}")

    return '订单已删除'


def _sync_order_to_material_registration(db: Session, order, user_id=None):
    """将已完成的采购订单同步至来料登记系统"""
    existing = db.query(MaterialRegistration).filter_by(purchase_order_id=order.id).first()
    if existing:
        logger.info(f"采购订单{order.order_no}已存在来料登记记录，跳过同步")
        return existing

    registration = MaterialRegistration(
        purchase_order_id=order.id,
        purchase_order_no=order.order_no,
        supplier_id=order.supplier_id,
        supplier_name=order.supplier_name,
        registration_date=datetime.now().date(),
        status='pending',
        remark='由采购订单自动同步创建',
        created_by=user_id,
    )
    db.add(registration)
    db.flush()

    order_items = db.query(PurchaseOrderItem).filter_by(order_id=order.id).all()
    for oi in order_items:
        db.add(MaterialRegistrationItem(
            registration_id=registration.id,
            order_item_id=oi.id,
            material_code=oi.material_code or '',
            material_name=oi.material_name,
            specification=oi.specification or '',
            unit=oi.unit or '',
            ordered_quantity=oi.quantity or 0,
            received_quantity=0,
            material_category=oi.material_category or '',
            remark='',
        ))

    logger.info(f"采购订单{order.order_no}已同步至来料登记，共{len(order_items)}项物料")
    return registration


def complete_purchase_order(db: Session, order_id: int, user_id: int, username: str) -> dict:
    order = db.get(PurchaseOrder, order_id)
    if not order:
        raise ValueError('订单不存在')

    order.status = '已完成'
    order.completed_at = datetime.now()
    order.completed_by = username

    _sync_order_to_material_registration(db, order, user_id)
    db.commit()
    return {'message': '订单已完成下单，已自动同步至来料登记'}


def batch_complete_purchase_orders(db: Session, ids: list, user_id: int, username: str) -> dict:
    completed_count = 0
    synced_count = 0

    for oid in ids:
        order = db.get(PurchaseOrder, oid)
        if order:
            order.status = '已完成'
            order.completed_at = datetime.now()
            order.completed_by = username
            completed_count += 1
            try:
                _sync_order_to_material_registration(db, order, user_id)
                synced_count += 1
            except Exception as e:
                logger.warning(f"订单{order.order_no}同步来料登记失败: {e}")

    db.commit()
    msg = f'成功完成 {completed_count} 个订单'
    if synced_count > 0:
        msg += f'，{synced_count} 个已同步至来料登记'
    return {
        'completed_count': completed_count,
        'synced_count': synced_count,
        'message': msg,
    }


def get_completed_purchase_orders(db: Session, *, page: int = 1, per_page: int = 20,
                                   order_no: str = '', customer_name: str = '',
                                   product_name: str = '', supplier_name: str = '',
                                   barcode: str = '', material_name: str = '',
                                   start_date: str = '',
                                   end_date: str = '') -> dict:
    query = db.query(PurchaseOrder).filter(PurchaseOrder.status == '已完成').options(selectinload(PurchaseOrder.items))

    if order_no:
        query = query.filter(PurchaseOrder.order_no.ilike(f'%{escape_like(order_no)}%'))
    if customer_name:
        query = query.filter(PurchaseOrder.customer_name.ilike(f'%{escape_like(customer_name)}%'))
    if product_name:
        query = query.filter(
            or_(
                PurchaseOrder.product_name.ilike(f'%{escape_like(product_name)}%'),
                PurchaseOrder.items.any(PurchaseOrderItem.material_name.ilike(f'%{escape_like(product_name)}%'))
            )
        )
    if supplier_name:
        query = query.filter(PurchaseOrder.supplier_name.ilike(f'%{escape_like(supplier_name)}%'))
    if barcode:
        # 通过69码查找对应产品，再匹配采购订单的产品名称
        barcode_products = db.query(Product.name).filter(Product.barcode.ilike(f'%{escape_like(barcode)}%')).all()
        barcode_product_names = [p.name for p in barcode_products]
        if barcode_product_names:
            conditions = [PurchaseOrder.product_name.ilike(f'%{name}%') for name in barcode_product_names]
            query = query.filter(or_(*conditions))
        else:
            # 没有匹配的产品，返回空结果
            query = query.filter(PurchaseOrder.id == -1)
    if start_date:
        try:
            sd = datetime.strptime(start_date, '%Y-%m-%d').date()
            query = query.filter(PurchaseOrder.order_date >= sd)
        except ValueError:
            pass
    if end_date:
        try:
            ed = datetime.strptime(end_date, '%Y-%m-%d').date()
            query = query.filter(PurchaseOrder.order_date <= ed)
        except ValueError:
            pass
    if material_name:
        query = query.filter(
            PurchaseOrder.items.any(PurchaseOrderItem.material_name.ilike(f'%{escape_like(material_name)}%'))
        )

    query = query.order_by(PurchaseOrder.completed_at.desc())
    total = query.count()
    orders = query.offset((page - 1) * per_page).limit(per_page).all()

    result = []
    for order in orders:
        order_dict = order.to_dict()
        order_dict['completed_at'] = order.completed_at.strftime('%Y-%m-%d %H:%M') if order.completed_at else None
        result.append(order_dict)

    return {
        'orders': result,
        'total': total,
        'page': page,
        'per_page': per_page,
        'total_pages': (total + per_page - 1) // per_page if per_page > 0 else 0,
    }


def export_completed_orders(db: Session, data: dict) -> str:
    """导出已完成订单为 HTML"""
    query = db.query(PurchaseOrder).filter(PurchaseOrder.status == '已完成')

    if data.get('order_no'):
        query = query.filter(PurchaseOrder.order_no.like(f'%{escape_like(data["order_no"])}%'))
    if data.get('customer_name'):
        query = query.filter(PurchaseOrder.customer_name.like(f'%{escape_like(data["customer_name"])}%'))
    if data.get('product_name'):
        query = query.filter(PurchaseOrder.product_name.like(f'%{escape_like(data["product_name"])}%'))
    if data.get('start_date'):
        query = query.filter(PurchaseOrder.order_date >= data['start_date'])
    if data.get('end_date'):
        query = query.filter(PurchaseOrder.order_date <= data['end_date'])

    orders = query.order_by(PurchaseOrder.completed_at.desc()).all()

    html_parts = [
        '<!DOCTYPE html><html><head><meta charset="utf-8"><title>下单查询汇总</title>',
        '<style>@page{margin:0in}body{font-family:宋体;margin:0;padding:0}',
        '.header{text-align:center;margin-bottom:10px}.header h1{margin:0;color:#333;font-size:24pt;font-weight:bold}',
        'table{width:100%;border-collapse:collapse;table-layout:fixed}',
        'th,td{border:1.0pt solid #000000;padding:1px;text-align:center;vertical-align:middle;font-size:10.5pt}',
        'th{background:#E6E6E6;font-weight:bold}</style></head><body>',
        '<div class="header"><h1>下单查询汇总</h1></div><table>',
        '<thead><tr><th>下单时间</th><th>订单号</th><th>客户名称</th><th>产品名称</th><th>订单数量</th><th>完成时间</th></tr></thead><tbody>',
    ]

    for order in orders:
        html_parts.append(f'<tr>')
        html_parts.append(f'<td>{order.order_date or "-"}</td>')
        html_parts.append(f'<td>{order.order_no}</td>')
        html_parts.append(f'<td>{order.customer_name or "-"}</td>')
        html_parts.append(f'<td>{order.product_name or "-"}</td>')
        html_parts.append(f'<td>{order.quantity or 0}</td>')
        html_parts.append(f'<td>{order.completed_at.strftime("%Y-%m-%d %H:%M") if order.completed_at else "-"}</td>')
        html_parts.append(f'</tr>')

    html_parts.append('</tbody></table></body></html>')
    return ''.join(html_parts)


# ============================================================
# 未处理订单 API
# ============================================================

def get_unprocessed_orders(db: Session, *, customer: str = '',
                           page: int = 1, per_page: int = 50) -> dict:
    query = db.query(Order).options(joinedload(Order.product))
    query = query.filter(Order.status == '待备货')

    if customer:
        query = query.filter(Order.customer.ilike(f'%{escape_like(customer)}%'))

    query = query.order_by(Order.order_date.desc())
    total = query.count()
    orders = query.offset((page - 1) * per_page).limit(per_page).all()

    # 预加载BOM数据，避免 N+1 查询
    product_ids = [o.product.id for o in orders if o.product]
    bom_product_ids = set()
    if product_ids:
        for Model in (ProductMaterial, ProductFabric, ProductAccessory, ProductPackaging):
            rows = db.query(Model.product_id).filter(Model.product_id.in_(product_ids)).distinct().all()
            bom_product_ids.update(r[0] for r in rows)

    orders_data = []
    no_bom_count = 0
    for o in orders:
        has_bom = o.product and o.product.id in bom_product_ids
        if not has_bom:
            no_bom_count += 1
            continue
        orders_data.append({
            'id': o.id,
            'source_order_id': o.id,
            'order_no': o.order_no,
            'customer': o.customer,
            'product_id': o.product_id,
            'product_name': o.product.name if o.product else '未知产品',
            'quantity': o.quantity,
            'order_date': o.order_date.strftime('%Y-%m-%d %H:%M:%S') if o.order_date else None,
            'sync_time': o.order_date.strftime('%Y-%m-%d %H:%M:%S') if o.order_date else None,
            'status': 'unprocessed',
            'processed_by_name': None,
            'process_time': None,
            'process_remark': o.note,
            'purchase_order_id': None,
            'has_bom': has_bom,
        })

    latest_order = db.query(Order).order_by(Order.order_date.desc()).first()
    latest_sync_time = latest_order.order_date.isoformat() if latest_order and latest_order.order_date else None

    return {
        'orders': orders_data,
        'total': total - no_bom_count,
        'latest_sync_time': latest_sync_time,
    }


# ============================================================
# 修改历史 & 保存查询 & 状态日志
# ============================================================

def get_modification_logs(db: Session, *, target_type: str = '', target_id: int = 0,
                          page: int = 1, per_page: int = 20) -> dict:
    query = db.query(ModificationLog)
    if target_type:
        query = query.filter(ModificationLog.target_type == target_type)
    if target_id:
        query = query.filter(ModificationLog.target_id == target_id)
    query = query.order_by(ModificationLog.modify_time.desc())
    total = query.count()
    logs = query.offset((page - 1) * per_page).limit(per_page).all()
    return {
        'logs': [log.to_dict() for log in logs],
        'total': total,
    }


def get_saved_queries(db: Session, query_type: str = 'purchase_order', user_id: int = 1) -> list:
    queries = db.query(SavedQuery).filter_by(
        query_type=query_type, creator_id=user_id,
    ).order_by(SavedQuery.create_time.desc()).all()
    return [q.to_dict() for q in queries]


def save_query(db: Session, data: dict, user_id: int, username: str) -> dict:
    sq = SavedQuery(
        name=data['name'],
        query_type=data.get('query_type', 'purchase_order'),
        conditions=json.dumps(data['conditions'], ensure_ascii=False),
        creator_id=user_id,
        creator_name=username,
    )
    db.add(sq)
    db.commit()
    return sq.to_dict()


def delete_saved_query(db: Session, query_id: int) -> Optional[str]:
    sq = db.get(SavedQuery, query_id)
    if not sq:
        return None
    db.delete(sq)
    db.commit()
    return '已删除'


def use_saved_query(db: Session, query_id: int) -> Optional[dict]:
    sq = db.get(SavedQuery, query_id)
    if not sq:
        return None
    sq.use_count += 1
    sq.last_use_time = datetime.now()
    db.commit()
    return sq.to_dict()


def get_status_logs(db: Session, *, target_type: str = '', target_id: int = 0,
                    order_no: str = '', page: int = 1, per_page: int = 20) -> dict:
    query = db.query(OrderStatusLog)
    if target_type:
        query = query.filter(OrderStatusLog.target_type == target_type)
    if target_id:
        query = query.filter(OrderStatusLog.target_id == target_id)
    if order_no:
        query = query.filter(OrderStatusLog.order_no.ilike(f'%{escape_like(order_no)}%'))
    query = query.order_by(OrderStatusLog.action_time.desc())
    total = query.count()
    logs = query.offset((page - 1) * per_page).limit(per_page).all()
    return {
        'logs': [log.to_dict() for log in logs],
        'total': total,
    }


# ============================================================
# 供应商汇总 (供 endpoint 层调用)
# ============================================================

def query_supplier_groups(db: Session, order_ids: list) -> list:
    """按供应商维度查询并分组采购订单物料"""
    orders = db.query(PurchaseOrder).filter(PurchaseOrder.id.in_(order_ids)).all()
    items = db.query(PurchaseOrderItem).filter(PurchaseOrderItem.order_id.in_(order_ids)).all()
    order_map = {o.id: o for o in orders}

    supplier_groups = {}
    # 收集每个供应商名称对应的冗余字段（用于回退）
    supplier_redundant_info = {}
    for item in items:
        order = order_map.get(item.order_id)
        if not order:
            continue

        supplier_name = item.supplier_name or order.supplier_name or '未指定供应商'
        if supplier_name not in supplier_groups:
            supplier_groups[supplier_name] = {
                'supplier_name': supplier_name,
                'items': [],
                'orders': set(),
            }
            # 记录首次遇到的冗余供应商信息，用于回退
            supplier_redundant_info[supplier_name] = {
                'contact_person': order.supplier_contact_person,
                'phone': order.supplier_phone,
                'address': order.supplier_address,
            }

        item_key = (item.material_name, item.specification or '', item.unit or '')
        found = False
        for existing_item in supplier_groups[supplier_name]['items']:
            if (existing_item['material_name'], existing_item['specification'], existing_item['unit']) == item_key:
                existing_item['quantity'] += Decimal(str(item.quantity))
                existing_item['order_count'] += 1
                found = True
                break

        if not found:
            supplier_groups[supplier_name]['items'].append({
                'material_name': item.material_name,
                'specification': item.specification or '',
                'unit': item.unit or '',
                'quantity': Decimal(str(item.quantity)),
                'material_category': item.material_category or '',
                'order_count': 1,
            })

        supplier_groups[supplier_name]['orders'].add(order.order_no)

    # 查询 Supplier 表获取完整供应商信息，冗余字段作为回退
    supplier_names = [name for name in supplier_groups if name != '未指定供应商']
    if supplier_names:
        supplier_records = db.query(Supplier).filter(Supplier.name.in_(supplier_names)).all()
        supplier_record_map = {s.name: s for s in supplier_records}
    else:
        supplier_record_map = {}

    for supplier_name in supplier_groups:
        supplier_groups[supplier_name]['orders'] = sorted(list(supplier_groups[supplier_name]['orders']))
        supplier_groups[supplier_name]['order_count'] = len(supplier_groups[supplier_name]['orders'])

        # 填充供应商详细信息：优先从 Supplier 表取，回退到 PurchaseOrder 冗余字段
        record = supplier_record_map.get(supplier_name)
        redundant = supplier_redundant_info.get(supplier_name, {})
        if record:
            supplier_groups[supplier_name]['contact_person'] = record.contact_person or ''
            supplier_groups[supplier_name]['phone'] = record.phone or ''
            supplier_groups[supplier_name]['address'] = record.address or ''
        else:
            supplier_groups[supplier_name]['contact_person'] = (redundant.get('contact_person') or '')
            supplier_groups[supplier_name]['phone'] = (redundant.get('phone') or '')
            supplier_groups[supplier_name]['address'] = (redundant.get('address') or '')
            if supplier_name != '未指定供应商':
                logger.warning(f"供应商'{supplier_name}'在Supplier表中未找到，使用订单冗余数据回退")

    result = sorted(supplier_groups.values(), key=lambda x: x['supplier_name'])

    # 将 Decimal 转为 float 以便 JSON 序列化
    for supplier in result:
        for item in supplier['items']:
            item['quantity'] = float(item['quantity'])

    return result


def get_factory_order_summary(db: Session, order_ids: list) -> dict:
    """获取工厂内部采购订单汇总"""
    orders = db.query(PurchaseOrder).filter(PurchaseOrder.id.in_(order_ids)).all()

    # 自动关联同源订单
    source_order_ids = list(set([o.source_order_id for o in orders if o.source_order_id]))
    if source_order_ids:
        related_orders = db.query(PurchaseOrder).filter(
            PurchaseOrder.source_order_id.in_(source_order_ids)
        ).all()
        related_order_ids = set(o.id for o in related_orders)
        all_order_ids = list(set(order_ids) | related_order_ids)
    else:
        all_order_ids = list(order_ids)

    if len(all_order_ids) != len(order_ids):
        orders = db.query(PurchaseOrder).filter(PurchaseOrder.id.in_(all_order_ids)).all()

    items = db.query(PurchaseOrderItem).filter(PurchaseOrderItem.order_id.in_(all_order_ids)).all()
    order_map = {o.id: o for o in orders}

    source_ids = [o.source_order_id for o in orders if o.source_order_id]
    source_orders = db.query(Order).filter(Order.id.in_(source_ids)).all() if source_ids else []
    source_order_map = {o.id: o for o in source_orders}

    grouped_data = {}
    order_count_map = {}

    for item in items:
        order = order_map.get(item.order_id)
        if not order:
            continue

        source_order = source_order_map.get(order.source_order_id) if order.source_order_id else None
        product_name = order.product_name
        if not product_name and source_order and source_order.product:
            product_name = source_order.product.name
        elif not product_name:
            product_name = order.customer_name or '未指定产品'

        product_qty = order.product_quantity
        if not product_qty and source_order:
            product_qty = source_order.quantity

        customer_name = source_order.customer if source_order else (order.customer_name or '未指定客户')
        supplier_name = item.supplier_name or order.supplier_name or '未指定供应商'
        fabric_name = item.material_name or '未指定布料'
        fabric_spec = item.specification or ''
        fabric_qty = item.quantity or 0

        customer_product_key = (customer_name, product_name)
        supplier_key = supplier_name

        if customer_product_key not in grouped_data:
            grouped_data[customer_product_key] = {}
            order_count_map[customer_product_key] = {'order_count': 0, 'total_fabric_qty': 0, 'product_quantity': product_qty}

        if supplier_key not in grouped_data[customer_product_key]:
            grouped_data[customer_product_key][supplier_key] = {}

        fabric_key = (fabric_name, fabric_spec, item.unit or '')
        if fabric_key not in grouped_data[customer_product_key][supplier_key]:
            grouped_data[customer_product_key][supplier_key][fabric_key] = {
                'item_id': item.id,
                'item_ids': [item.id],
                'fabric_name': fabric_name,
                'specification': fabric_spec,
                'quantity': fabric_qty,
                'unit': item.unit or '',
                'original_quantities': {str(item.id): float(fabric_qty) if fabric_qty else 0},
            }
        else:
            existing = grouped_data[customer_product_key][supplier_key][fabric_key]
            existing['item_ids'].append(item.id)
            existing['quantity'] = (float(existing['quantity']) if existing['quantity'] else 0) + (float(fabric_qty) if fabric_qty else 0)
            existing['original_quantities'][str(item.id)] = float(fabric_qty) if fabric_qty else 0

        order_count_map[customer_product_key]['total_fabric_qty'] += fabric_qty

    for order in orders:
        source_order = source_order_map.get(order.source_order_id) if order.source_order_id else None
        product_name = order.product_name
        if not product_name and source_order and source_order.product:
            product_name = source_order.product.name
        elif not product_name:
            product_name = order.customer_name or '未指定产品'
        customer_name = source_order.customer if source_order else (order.customer_name or '未指定客户')
        cp_key = (customer_name, product_name)
        if cp_key in order_count_map:
            order_count_map[cp_key]['order_count'] += 1

    result_list = []
    for (customer_name, product_name), supplier_dict in grouped_data.items():
        order_info = order_count_map[(customer_name, product_name)]
        suppliers_list = []
        for supplier_name, fabric_dict in supplier_dict.items():
            fabrics_list = list(fabric_dict.values())
            for f in fabrics_list:
                f['quantity'] = round(f['quantity'], 2)
            suppliers_list.append({
                'supplier_name': supplier_name,
                'fabrics': fabrics_list,
            })
        result_list.append({
            'customer_name': customer_name,
            'product_name': product_name,
            'order_quantity': order_info['order_count'],
            'product_quantity': order_info['product_quantity'],
            'suppliers': suppliers_list,
            'total_fabric_qty': order_info['total_fabric_qty'],
        })

    return {
        'groups': result_list,
        'order_count': len(orders),
    }


def save_factory_summary_edits(db: Session, edits: list) -> dict:
    updated_count = 0
    errors = []

    for edit in edits:
        item_id = edit.get('item_id')
        new_quantity = edit.get('quantity')

        if not item_id:
            errors.append('缺少item_id')
            continue
        if new_quantity is None:
            errors.append(f'item_id {item_id}: 缺少数量')
            continue

        try:
            new_qty = float(new_quantity)
            if new_qty < 0:
                errors.append(f'item_id {item_id}: 数量不能为负数')
                continue
            if new_qty > 99999999:
                errors.append(f'item_id {item_id}: 数量超出范围')
                continue
        except (ValueError, TypeError):
            errors.append(f'item_id {item_id}: 无效的数量值')
            continue

        item = db.get(PurchaseOrderItem, item_id)
        if not item:
            errors.append(f'item_id {item_id}: 找不到对应的订单明细')
            continue

        item.quantity = new_qty
        updated_count += 1

    db.commit()
    return {
        'updated_count': updated_count,
        'warnings': errors if errors else None,
        'message': f'成功保存 {updated_count} 条修改' + (f'，但有{len(errors)}条警告' if errors else ''),
    }


def get_supplier_order_summary(db: Session, order_ids: list) -> dict:
    """获取供应商采购订单汇总 - 按物料维度汇总"""
    orders = db.query(PurchaseOrder).filter(PurchaseOrder.id.in_(order_ids)).all()
    items = db.query(PurchaseOrderItem).filter(PurchaseOrderItem.order_id.in_(order_ids)).all()
    order_map = {o.id: o for o in orders}

    material_summary = {}
    for item in items:
        order = order_map.get(item.order_id)
        key = (item.material_name, item.specification or '', item.unit or '',
               item.supplier_name or (order.supplier_name if order else '') or '未指定')
        if key not in material_summary:
            material_summary[key] = {
                'material_name': item.material_name,
                'specification': item.specification,
                'unit': item.unit,
                'supplier_name': item.supplier_name or (order.supplier_name if order else '') or '未指定',
                'category': item.material_category,
                'total_quantity': Decimal('0'),
                'orders': [],
            }
        material_summary[key]['total_quantity'] += Decimal(str(item.quantity))
        material_summary[key]['orders'].append({
            'order_no': order.order_no if order else '-',
            'product_name': order.customer_name if order else '-',
            'quantity': item.quantity,
        })

    materials_list = sorted(material_summary.values(), key=lambda x: x['material_name'])

    # 将 Decimal 转为 float 以便 JSON 序列化
    for m in materials_list:
        m['total_quantity'] = float(m['total_quantity'])

    return {
        'materials': materials_list,
        'order_count': len(orders),
        'material_count': len(materials_list),
    }


def get_completed_order_suggestions(db: Session, field: str, keyword: str, limit: int = 10) -> list:
    """获取下单查询的智能联想建议"""
    if not field or not keyword or len(keyword) < 1:
        return []

    suggestions = []
    try:
        if field == 'order_no':
            orders = db.query(PurchaseOrder).filter(
                and_(
                    PurchaseOrder.status == '已完成',
                    PurchaseOrder.order_no.ilike(f'%{escape_like(keyword)}%')
                )
            ).limit(limit).all()
            suggestions = [{'value': o.order_no} for o in orders]
        elif field == 'customer_name':
            customers = db.query(PurchaseOrder).filter(
                and_(
                    PurchaseOrder.status == '已完成',
                    PurchaseOrder.customer_name.isnot(None),
                    PurchaseOrder.customer_name != '',
                    PurchaseOrder.customer_name.ilike(f'%{escape_like(keyword)}%')
                )
            ).distinct(PurchaseOrder.customer_name).limit(limit).all()
            suggestions = [{'value': c.customer_name} for c in customers if c.customer_name]
        elif field == 'product_name':
            products = db.query(PurchaseOrder).filter(
                and_(
                    PurchaseOrder.status == '已完成',
                    PurchaseOrder.product_name.isnot(None),
                    PurchaseOrder.product_name != '',
                    PurchaseOrder.product_name.ilike(f'%{escape_like(keyword)}%')
                )
            ).distinct(PurchaseOrder.product_name).limit(limit).all()
            suggestions = [{'value': p.product_name} for p in products if p.product_name]
        elif field == 'supplier_name':
            suppliers = db.query(PurchaseOrder).filter(
                and_(
                    PurchaseOrder.status == '已完成',
                    PurchaseOrder.supplier_name.isnot(None),
                    PurchaseOrder.supplier_name != '',
                    PurchaseOrder.supplier_name.ilike(f'%{escape_like(keyword)}%')
                )
            ).distinct(PurchaseOrder.supplier_name).limit(limit).all()
            suggestions = [{'value': s.supplier_name} for s in suppliers if s.supplier_name]
        elif field == 'material_name':
            materials = db.query(PurchaseOrderItem).filter(
                PurchaseOrderItem.material_name.ilike(f'%{escape_like(keyword)}%')
            ).distinct(PurchaseOrderItem.material_name).limit(limit).all()
            suggestions = [{'value': m.material_name} for m in materials if m.material_name]
    except Exception as e:
        logger.exception(f"获取联想建议失败: {str(e)}")

    return suggestions[:limit]


def get_completed_order_quick_filters() -> list:
    """获取下单查询的常用快捷筛选条件"""
    today = datetime.now().date()
    yesterday = today - timedelta(days=1)
    week_ago = today - timedelta(days=7)
    month_ago = today - timedelta(days=30)

    return [
        {'id': 'today', 'name': '今日', 'filters': {'start_date': today.strftime('%Y-%m-%d'), 'end_date': today.strftime('%Y-%m-%d')}},
        {'id': 'yesterday', 'name': '昨日', 'filters': {'start_date': yesterday.strftime('%Y-%m-%d'), 'end_date': yesterday.strftime('%Y-%m-%d')}},
        {'id': 'last_7_days', 'name': '近7天', 'filters': {'start_date': week_ago.strftime('%Y-%m-%d'), 'end_date': today.strftime('%Y-%m-%d')}},
        {'id': 'last_30_days', 'name': '近30天', 'filters': {'start_date': month_ago.strftime('%Y-%m-%d'), 'end_date': today.strftime('%Y-%m-%d')}},
    ]


# ============================================================
# BOM 复制功能 (从 material.py 迁移)
# ============================================================


def search_products_for_bom_copy(db: Session, keyword: str) -> list:
    """搜索产品用于复制BOM

    根据关键词搜索产品名称或条码，返回产品基本信息和BOM状态。
    """
    if not keyword:
        return []

    query = db.query(Product).filter(
        or_(
            Product.name.ilike(f'%{escape_like(keyword)}%'),
            Product.barcode.ilike(f'%{escape_like(keyword)}%')
        )
    )

    products = query.limit(20).all()

    result = []
    for product in products:
        # 使用 joinedload 预加载 BOM 关系
        p = db.query(Product).options(
            joinedload(Product.material),
            joinedload(Product.fabrics),
            joinedload(Product.accessories),
            joinedload(Product.packagings),
        ).get(product.id)

        has_bom = _product_has_bom(p)
        material_count = (
            len(p.fabrics) + len(p.accessories) + len(p.packagings) +
            (1 if p.material and getattr(p.material, 'cotton_usage', Decimal('0')) > 0 else 0)
        )
        result.append({
            'id': p.id,
            'name': p.name,
            'barcode': p.barcode,
            'price': float(p.price) if p.price else 0,
            'has_bom': has_bom,
            'material_count': material_count,
        })

    return result


def get_bom_preview(db: Session, source_product_id: int) -> dict:
    """获取源产品BOM预览用于复制确认

    返回源产品的基本信息和完整BOM数据（filling/fabric/accessory/packaging）。
    """
    source_product = db.query(Product).options(
        joinedload(Product.material),
        joinedload(Product.fabrics),
        joinedload(Product.accessories),
        joinedload(Product.packagings),
    ).get(source_product_id)

    if not source_product:
        raise ValueError(f'产品ID {source_product_id} 不存在')

    if not _product_has_bom(source_product):
        raise ValueError('该产品没有配置BOM表，无法复制')

    bom_data = {
        'filling': None,
        'fabric': [],
        'accessory': [],
        'packaging': [],
    }

    if source_product.material and getattr(source_product.material, 'cotton_usage', Decimal('0')) > 0:
        bom_data['filling'] = source_product.material.to_dict()

    for fabric in source_product.fabrics:
        bom_data['fabric'].append(fabric.to_dict())

    for accessory in source_product.accessories:
        bom_data['accessory'].append(accessory.to_dict())

    for packaging in source_product.packagings:
        bom_data['packaging'].append(packaging.to_dict())

    material_count = (
        (1 if bom_data['filling'] else 0) +
        len(bom_data['fabric']) +
        len(bom_data['accessory']) +
        len(bom_data['packaging'])
    )

    create_time_str = None
    if source_product.create_time:
        create_time_str = source_product.create_time.strftime('%Y-%m-%d %H:%M:%S')

    return {
        'product': {
            'id': source_product.id,
            'name': source_product.name,
            'barcode': source_product.barcode,
            'create_time': create_time_str,
        },
        'bom': bom_data,
        'material_count': material_count,
    }


def copy_bom_to_product(db: Session, target_product_id: int, data: dict, username: str = 'unknown') -> dict:
    """复制BOM到目标产品

    从源产品复制完整的BOM数据（filling/fabric/accessory/packaging）到目标产品。

    参数:
        target_product_id: 目标产品ID
        data: 包含 source_product_id 和 overwrite 的字典
        username: 操作用户名
    """
    source_product_id = data.get('source_product_id')
    overwrite = data.get('overwrite', False)

    if not source_product_id:
        raise ValueError('请选择源产品')

    if source_product_id == target_product_id:
        raise ValueError('不能复制到同一产品')

    source_product = db.query(Product).options(
        joinedload(Product.material),
        joinedload(Product.fabrics),
        joinedload(Product.accessories),
        joinedload(Product.packagings),
    ).get(source_product_id)

    target_product = db.query(Product).options(
        joinedload(Product.material),
        joinedload(Product.fabrics),
        joinedload(Product.accessories),
        joinedload(Product.packagings),
    ).get(target_product_id)

    if not source_product:
        raise ValueError(f'源产品ID {source_product_id} 不存在')
    if not target_product:
        raise ValueError(f'目标产品ID {target_product_id} 不存在')

    if not _product_has_bom(source_product):
        raise ValueError('源产品没有配置BOM表')

    if not overwrite and _product_has_bom(target_product):
        raise ValueError('目标产品已有BOM表，请确认是否覆盖')

    copied_count = 0

    if overwrite:
        db.query(ProductMaterial).filter_by(product_id=target_product_id).delete()
        db.query(ProductFabric).filter_by(product_id=target_product_id).delete()
        db.query(ProductAccessory).filter_by(product_id=target_product_id).delete()
        db.query(ProductPackaging).filter_by(product_id=target_product_id).delete()

    # 复制填充类
    if source_product.material and getattr(source_product.material, 'cotton_usage', Decimal('0')) > 0:
        old_material = source_product.material
        new_material = ProductMaterial(
            product_id=target_product_id,
            material_code=getattr(old_material, 'material_code', '') or '',
            cotton_usage=old_material.cotton_usage,
            specification=getattr(old_material, 'specification', '') or '',
            supplier_id=getattr(old_material, 'supplier_id', None),
            supplier_name=getattr(old_material, 'supplier_name', '') or '',
            unit=getattr(old_material, 'unit', '') or '克',
            remark=getattr(old_material, 'remark', '') or '',
        )
        db.add(new_material)
        copied_count += 1

    # 复制面料类
    for old_fabric in source_product.fabrics:
        new_fabric = ProductFabric(
            product_id=target_product_id,
            material_code=getattr(old_fabric, 'material_code', '') or '',
            fabric_name=old_fabric.fabric_name,
            specification=getattr(old_fabric, 'specification', '') or '',
            quantity=old_fabric.quantity,
            supplier_id=getattr(old_fabric, 'supplier_id', None),
            supplier_name=getattr(old_fabric, 'supplier_name', '') or '',
            unit=getattr(old_fabric, 'unit', '') or '码',
            remark=getattr(old_fabric, 'remark', '') or '',
        )
        db.add(new_fabric)
        copied_count += 1

    # 复制辅料类
    for old_accessory in source_product.accessories:
        new_accessory = ProductAccessory(
            product_id=target_product_id,
            material_code=getattr(old_accessory, 'material_code', '') or '',
            accessory_name=old_accessory.accessory_name,
            specification=getattr(old_accessory, 'specification', '') or '',
            quantity=old_accessory.quantity,
            supplier_id=getattr(old_accessory, 'supplier_id', None),
            supplier_name=getattr(old_accessory, 'supplier_name', '') or '',
            unit=getattr(old_accessory, 'unit', '') or '个',
            material_category=getattr(old_accessory, 'material_category', '') or 'accessory',
            remark=getattr(old_accessory, 'remark', '') or '',
        )
        db.add(new_accessory)
        copied_count += 1

    # 复制包装类
    for old_packaging in source_product.packagings:
        new_packaging = ProductPackaging(
            product_id=target_product_id,
            material_code=getattr(old_packaging, 'material_code', '') or '',
            packaging_name=old_packaging.packaging_name,
            specification=getattr(old_packaging, 'specification', '') or '',
            quantity=old_packaging.quantity,
            supplier_id=getattr(old_packaging, 'supplier_id', None),
            supplier_name=getattr(old_packaging, 'supplier_name', '') or '',
            unit=getattr(old_packaging, 'unit', '') or '',
            remark=getattr(old_packaging, 'remark', '') or '',
        )
        db.add(new_packaging)
        copied_count += 1

    db.commit()

    logger.info(
        f'BOM复制成功 | 操作人: {username} | '
        f'源产品: {source_product.name}({source_product_id}) | '
        f'目标产品: {target_product.name}({target_product_id}) | '
        f'复制物料数: {copied_count} | 覆盖: {overwrite}'
    )

    return {
        'message': f'BOM复制成功，共复制 {copied_count} 项物料',
        'copied_count': copied_count,
        'source_product': {'id': source_product.id, 'name': source_product.name},
        'target_product': {'id': target_product.id, 'name': target_product.name},
    }


def batch_delete_purchase_orders(db: Session, order_ids: list, username: str = 'unknown') -> dict:
    """批量删除采购订单

    参数:
        order_ids: 要删除的订单ID列表
        username: 操作用户名
    """
    if not order_ids:
        raise ValueError('请选择要删除的订单')

    orders_to_delete = db.query(PurchaseOrder).filter(PurchaseOrder.id.in_(order_ids)).all()

    if not orders_to_delete:
        raise ValueError('未找到要删除的订单')

    deleted_info = []
    for order in orders_to_delete:
        item_count = db.query(PurchaseOrderItem).filter_by(order_id=order.id).count()
        deleted_info.append({
            'order_no': order.order_no,
            'supplier_name': order.supplier_name or '',
            'customer_name': order.customer_name or '',
            'item_count': item_count,
        })
        db.delete(order)

    db.commit()

    logger.warning(
        f'批量删除采购订单 | 操作人: {username} | '
        f'删除数量: {len(deleted_info)} | '
        f"订单编号: {', '.join([info['order_no'] for info in deleted_info])}"
    )

    return {
        'message': f'成功删除 {len(deleted_info)} 个订单',
        'deleted_count': len(deleted_info),
    }
