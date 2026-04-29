"""
采购中心 - 产品/BOM 管理服务

从 purchase_center_service.py 拆分，包含产品查询、BOM 保存和物料计算。
"""
import json
import logging
from decimal import Decimal
from typing import Optional

from sqlalchemy import or_
from sqlalchemy.orm import Session, selectinload

from fastapi_app.shared_models import (
    Product, ProductMaterial, ProductFabric, ProductAccessory, ProductPackaging,
    ModificationLog, MATERIAL_CATEGORIES,
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


def get_products(db: Session, *, page: int = 1, per_page: int = 50,
                 search: str = '', has_bom: str = 'all', category: str = '',
                 sort_by: str = 'name', sort_order: str = 'asc',
                 simple: bool = False) -> dict:
    query = db.query(Product)

    if not simple:
        query = query.options(
            selectinload(Product.material),
            selectinload(Product.fabrics),
            selectinload(Product.accessories),
            selectinload(Product.packagings),
        )

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

    if simple:
        product_ids = [p.id for p in products]
        has_material_ids = set()
        has_fabric_ids = set()
        has_accessory_ids = set()
        has_packaging_ids = set()
        if product_ids:
            has_material_ids = set(
                row[0] for row in db.query(ProductMaterial.product_id)
                .filter(ProductMaterial.product_id.in_(product_ids), ProductMaterial.cotton_usage > 0)
                .all()
            )
            has_fabric_ids = set(
                row[0] for row in db.query(ProductFabric.product_id)
                .filter(ProductFabric.product_id.in_(product_ids))
                .distinct().all()
            )
            has_accessory_ids = set(
                row[0] for row in db.query(ProductAccessory.product_id)
                .filter(ProductAccessory.product_id.in_(product_ids))
                .distinct().all()
            )
            has_packaging_ids = set(
                row[0] for row in db.query(ProductPackaging.product_id)
                .filter(ProductPackaging.product_id.in_(product_ids))
                .distinct().all()
            )
        result = []
        for p in products:
            has_bom_flag = (
                p.id in has_material_ids or
                p.id in has_fabric_ids or
                p.id in has_accessory_ids or
                p.id in has_packaging_ids
            )
            result.append({
                'id': p.id,
                'name': p.name,
                'barcode': p.barcode,
                'has_bom': has_bom_flag,
            })
    else:
        result = []
        for p in products:
            has_bom_flag = _product_has_bom(p)
            bom_info = {}
            if has_bom_flag:
                bom_info = {
                    'filling_count': 1 if (p.material and p.material.cotton_usage and p.material.cotton_usage > 0) else 0,
                    'fabric_count': len(p.fabrics),
                    'accessory_count': len(p.accessories),
                    'packaging_count': len(p.packagings),
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

    products = db.query(Product).options(
        selectinload(Product.material),
        selectinload(Product.fabrics),
        selectinload(Product.accessories),
        selectinload(Product.packagings),
    ).filter(Product.id.in_(pid_list)).all()
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

    products = db.query(Product).options(
        selectinload(Product.material),
        selectinload(Product.fabrics),
        selectinload(Product.accessories),
        selectinload(Product.packagings),
    ).filter(
        or_(
            Product.name.ilike(f'%{escape_like(keyword)}%'),
            Product.barcode.ilike(f'%{escape_like(keyword)}%')
        )
    ).limit(10).all()

    return [
        {'id': p.id, 'name': p.name, 'barcode': p.barcode, 'price': float(p.price) if p.price else 0, 'has_bom': _product_has_bom(p)}
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
                fab.remark = fab_data.get('remark', '')
                if old_val != fab.fabric_name:
                    db.add(ModificationLog(
                        target_type='fabric', target_id=fab.id,
                        field_name='fabric_name', old_value=old_val, new_value=fab.fabric_name,
                        modifier_name=username,
                    ))
        else:
            fab = ProductFabric(
                product_id=product_id,
                fabric_name=fab_data.get('fabric_name', ''),
                quantity=Decimal(str(fab_data.get('quantity', 0))),
                supplier_id=fab_data.get('supplier_id'),
                supplier_name=fab_data.get('supplier_name', ''),
                remark=fab_data.get('remark', ''),
            )
            db.add(fab)

    accessories_data = data.get('accessories', [])
    for acc_data in accessories_data:
        if acc_data.get('id'):
            acc = db.get(ProductAccessory, acc_data['id'])
            if acc and acc.product_id == product_id:
                old_val = acc.accessory_name
                acc.accessory_name = acc_data.get('accessory_name', '')
                acc.quantity = Decimal(str(acc_data.get('quantity', 0)))
                acc.supplier_id = acc_data.get('supplier_id')
                acc.supplier_name = acc_data.get('supplier_name', '')
                acc.remark = acc_data.get('remark', '')
                if old_val != acc.accessory_name:
                    db.add(ModificationLog(
                        target_type='accessory', target_id=acc.id,
                        field_name='accessory_name', old_value=old_val, new_value=acc.accessory_name,
                        modifier_name=username,
                    ))
        else:
            acc = ProductAccessory(
                product_id=product_id,
                accessory_name=acc_data.get('accessory_name', ''),
                quantity=Decimal(str(acc_data.get('quantity', 0))),
                supplier_id=acc_data.get('supplier_id'),
                supplier_name=acc_data.get('supplier_name', ''),
                remark=acc_data.get('remark', ''),
            )
            db.add(acc)

    packagings_data = data.get('packagings', [])
    for pkg_data in packagings_data:
        if pkg_data.get('id'):
            pkg = db.get(ProductPackaging, pkg_data['id'])
            if pkg and pkg.product_id == product_id:
                old_val = pkg.packaging_name
                pkg.packaging_name = pkg_data.get('packaging_name', '')
                pkg.quantity = Decimal(str(pkg_data.get('quantity', 0)))
                pkg.supplier_id = pkg_data.get('supplier_id')
                pkg.supplier_name = pkg_data.get('supplier_name', '')
                pkg.remark = pkg_data.get('remark', '')
                if old_val != pkg.packaging_name:
                    db.add(ModificationLog(
                        target_type='packaging', target_id=pkg.id,
                        field_name='packaging_name', old_value=old_val, new_value=pkg.packaging_name,
                        modifier_name=username,
                    ))
        else:
            pkg = ProductPackaging(
                product_id=product_id,
                packaging_name=pkg_data.get('packaging_name', ''),
                quantity=Decimal(str(pkg_data.get('quantity', 0))),
                supplier_id=pkg_data.get('supplier_id'),
                supplier_name=pkg_data.get('supplier_name', ''),
                remark=pkg_data.get('remark', ''),
            )
            db.add(pkg)

    # 处理删除
    for category, model_cls in [('fabrics', ProductFabric), ('accessories', ProductAccessory), ('packagings', ProductPackaging)]:
        existing_ids = {item['id'] for item in data.get(category, []) if item.get('id')}
        to_delete = db.query(model_cls).filter(
            model_cls.product_id == product_id,
            ~model_cls.id.in_(existing_ids) if existing_ids else True,
        ).all()
        for item in to_delete:
            db.delete(item)
            db.add(ModificationLog(
                target_type=category[:-1], target_id=item.id,
                field_name='deleted', old_value=getattr(item, f'{category[:-2]}y_name', '') or '',
                new_value='(已删除)',
                modifier_name=username,
            ))

    db.commit()
    return 'BOM 保存成功'


def calculate_material(db: Session, orders_data: list) -> dict:
    """聚合多个订单的物料需求，按类别分组"""
    from collections import defaultdict

    result = {
        'filling': [],
        'fabric': [],
        'accessory': [],
        'packaging': [],
    }
    totals = defaultdict(lambda: defaultdict(Decimal))

    product_ids = [item.get('product_id') for item in orders_data if item.get('product_id')]
    if not product_ids:
        return result

    product_map = {}
    products = db.query(Product).options(
        selectinload(Product.material),
        selectinload(Product.fabrics),
        selectinload(Product.accessories),
        selectinload(Product.packagings),
    ).filter(Product.id.in_(product_ids)).all()
    for p in products:
        product_map[p.id] = p

    for order_item in orders_data:
        product_id = order_item.get('product_id')
        quantity = Decimal(str(order_item.get('quantity', 0)))

        product = product_map.get(product_id)
        if not product or not product.has_bom():
            continue

        all_materials = product.get_all_materials()

        for mat in all_materials:
            category = mat.get('category', '')
            name = mat.get('material_name', '')
            key = f"{category}:{name}"
            per_unit = Decimal(str(mat.get('unit_usage', 0)))
            totals[key]['total'] += per_unit * quantity
            totals[key]['name'] = name
            totals[key]['category'] = category
            totals[key]['unit'] = mat.get('unit', '')
            totals[key]['supplier_name'] = mat.get('supplier_name', '')
            totals[key]['specification'] = mat.get('specification', '')
            totals[key]['material_code'] = mat.get('material_code', '')

    for key, info in totals.items():
        category = info['category']
        if category in result:
            result[category].append({
                'name': info['name'],
                'material_name': info['name'],
                'material_code': info.get('material_code', ''),
                'specification': info.get('specification', ''),
                'total_quantity': float(info['total']),
                'unit': info['unit'],
                'supplier_name': info['supplier_name'],
            })

    return result
