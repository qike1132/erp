"""
采购中心 - 产品/BOM 管理服务

从 purchase_center_service.py 拆分，包含产品查询、BOM 保存和物料计算。
"""
import json
import logging
from decimal import Decimal

from sqlalchemy import func, or_, select, union_all
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from fastapi_app.services import escape_like
from fastapi_app.shared_models import (
    ModificationLog,
    Product,
    ProductAccessory,
    ProductFabric,
    ProductMaterial,
    ProductPackaging,
)

logger = logging.getLogger(__name__)


def product_has_bom(product) -> bool:
    """判断产品是否配置了BOM（任意一类物料有数据即视为有BOM）"""
    has_filling = (
        product.material is not None and
        getattr(product.material, 'cotton_usage', Decimal('0')) > 0
    )
    has_fabric = hasattr(product, 'fabrics') and len(product.fabrics) > 0
    has_accessory = hasattr(product, 'accessories') and len(product.accessories) > 0
    has_packaging = hasattr(product, 'packagings') and len(product.packagings) > 0
    return has_filling or has_fabric or has_accessory or has_packaging


async def _batch_check_bom_exists(db: AsyncSession, product_ids: list[int]) -> set[int]:
    if not product_ids:
        return set()

    subq = union_all(
        select(ProductMaterial.product_id).where(
            ProductMaterial.product_id.in_(product_ids),
            ProductMaterial.cotton_usage > 0,
        ),
        select(ProductFabric.product_id).where(
            ProductFabric.product_id.in_(product_ids),
        ),
        select(ProductAccessory.product_id).where(
            ProductAccessory.product_id.in_(product_ids),
        ),
        select(ProductPackaging.product_id).where(
            ProductPackaging.product_id.in_(product_ids),
        ),
    )
    result = await db.execute(select(subq.c.product_id))
    return {row[0] for row in result}


async def get_products(db: AsyncSession, *, page: int = 1, per_page: int = 50,
                       search: str = '', has_bom: str = 'all', category: str = '',
                       sort_by: str = 'name', sort_order: str = 'asc',
                       simple: bool = False) -> dict:
    query = select(Product)
    count_query = select(func.count(Product.id))

    if not simple:
        query = query.options(
            selectinload(Product.material),
            selectinload(Product.fabrics),
            selectinload(Product.accessories),
            selectinload(Product.packagings),
        )

    if search:
        query = query.where(
            or_(
                Product.name.ilike(f'%{escape_like(search)}%'),
                Product.barcode.ilike(f'%{escape_like(search)}%')
            )
        )
        count_query = count_query.where(
            or_(
                Product.name.ilike(f'%{escape_like(search)}%'),
                Product.barcode.ilike(f'%{escape_like(search)}%')
            )
        )

    if has_bom == 'true':
        query = query.where(Product.material.has())
        count_query = count_query.where(Product.material.has())
    elif has_bom == 'false':
        query = query.where(~Product.material.has())
        count_query = count_query.where(~Product.material.has())

    if category:
        if category == 'filling':
            query = query.where(Product.material.has())
            count_query = count_query.where(Product.material.has())
        elif category == 'fabric':
            query = query.where(Product.fabrics.any())
            count_query = count_query.where(Product.fabrics.any())
        elif category == 'accessory':
            query = query.where(Product.accessories.any())
            count_query = count_query.where(Product.accessories.any())
        elif category == 'packaging':
            query = query.where(Product.packagings.any())
            count_query = count_query.where(Product.packagings.any())

    sort_map = {
        'name': Product.name,
        'barcode': Product.barcode,
        'create_time': Product.create_time,
    }
    sort_col = sort_map.get(sort_by, Product.name)
    if sort_order == 'desc':
        sort_col = sort_col.desc()
    query = query.order_by(sort_col)

    query = query.offset((page - 1) * per_page).limit(per_page)
    result = await db.execute(query)
    products = result.scalars().unique().all()

    if simple:
        product_ids = [p.id for p in products]
        bom_product_ids = await _batch_check_bom_exists(db, product_ids)
        output = []
        for p in products:
            output.append({
                'id': p.id,
                'name': p.name,
                'barcode': p.barcode,
                'has_bom': p.id in bom_product_ids,
            })
        return {
            'products': output,
            'total': len(output),
            'pages': 1,
            'current_page': page,
        }

    total_result = await db.execute(count_query)
    total = total_result.scalar()

    output = []
    for p in products:
        has_bom_flag = product_has_bom(p)
        bom_info = {}
        if has_bom_flag:
            bom_info = {
                'filling_count': 1 if (p.material and p.material.cotton_usage and p.material.cotton_usage > 0) else 0,
                'fabric_count': len(p.fabrics),
                'accessory_count': len(p.accessories),
                'packaging_count': len(p.packagings),
            }
        output.append({
            'id': p.id,
            'name': p.name,
            'barcode': p.barcode,
            'price': float(p.price) if p.price else 0,
            'has_bom': has_bom_flag,
            'bom_info': bom_info,
            'current_stock': p.current_stock,
        })

    return {
        'products': output,
        'total': total,
        'pages': (total + per_page - 1) // per_page if per_page > 0 else 0,
        'current_page': page,
    }


async def get_products_batch_bom(db: AsyncSession, product_ids_str: str) -> dict:
    if not product_ids_str:
        return {'products': {}}

    try:
        pid_list = [int(x) for x in product_ids_str.split(',') if x.strip().isdigit()]
    except ValueError:
        return {'products': {}}

    result = await db.execute(
        select(Product).options(
            selectinload(Product.material),
            selectinload(Product.fabrics),
            selectinload(Product.accessories),
            selectinload(Product.packagings),
        ).where(Product.id.in_(pid_list))
    )
    products = result.scalars().unique().all()

    output = {}
    for p in products:
        if p.has_bom():
            all_mats = p.get_all_materials()
            output[str(p.id)] = {
                'name': p.name,
                'barcode': p.barcode,
                'materials': all_mats,
            }
    return {'products': output}


async def get_search_suggestions(db: AsyncSession, keyword: str) -> list:
    if not keyword or len(keyword) < 1:
        return []

    result = await db.execute(
        select(Product).where(
            or_(
                Product.name.ilike(f'%{escape_like(keyword)}%'),
                Product.barcode.ilike(f'%{escape_like(keyword)}%')
            )
        ).limit(10)
    )
    products = result.scalars().all()

    product_ids = [p.id for p in products]
    bom_product_ids = await _batch_check_bom_exists(db, product_ids)

    return [
        {
            'id': p.id, 'name': p.name, 'barcode': p.barcode,
            'price': float(p.price) if p.price else 0,
            'has_bom': p.id in bom_product_ids,
        }
        for p in products
    ]


async def get_products_statistics(db: AsyncSession) -> dict:
    total_result = await db.execute(select(func.count(Product.id)))
    total = total_result.scalar()

    has_bom_result = await db.execute(
        select(func.count(Product.id)).where(Product.material.has())
    )
    has_bom = has_bom_result.scalar()

    return {
        'total': total,
        'has_bom': has_bom,
        'no_bom': total - has_bom,
    }


async def get_product_bom(db: AsyncSession, product_id: int) -> dict:
    product = await db.get(Product, product_id)
    if not product:
        return None
    all_materials = product.get_all_materials() if product.has_bom() else []
    return {
        'id': product.id,
        'name': product.name,
        'barcode': product.barcode,
        'materials': all_materials,
    }


async def save_product_bom(db: AsyncSession, product_id: int, data: dict, username: str) -> str:
    product = await db.get(Product, product_id)
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
            product.material.unit = filling_data.get('unit', '')
            product.material.remark = filling_data.get('remark', '')
            new_data = {
                'cotton_usage': float(product.material.cotton_usage),
                'supplier_name': product.material.supplier_name,
            }
            if old_data != new_data:
                db.add(ModificationLog(
                    target_type='material', target_id=product.material.id,
                    field_name='filling_data',
                    old_value=json.dumps(old_data, ensure_ascii=False),
                    new_value=json.dumps(new_data, ensure_ascii=False),
                    modifier_name=username,
                ))
        else:
            db.add(ProductMaterial(
                product_id=product_id,
                cotton_usage=Decimal(str(filling_data.get('cotton_usage', 0))),
                supplier_id=filling_data.get('supplier_id'),
                supplier_name=filling_data.get('supplier_name', ''),
                specification=filling_data.get('specification', ''),
                unit=filling_data.get('unit', ''),
                remark=filling_data.get('remark', ''),
            ))

    fabrics_data = data.get('fabrics', [])
    for fab_data in fabrics_data:
        if fab_data.get('id'):
            fab = await db.get(ProductFabric, fab_data['id'])
            if fab and fab.product_id == product_id:
                old_val = fab.fabric_name
                fab.fabric_name = fab_data.get('fabric_name', '')
                fab.specification = fab_data.get('specification', '')
                fab.unit = fab_data.get('unit', '')
                fab.quantity = Decimal(str(fab_data.get('quantity', 0)))
                fab.supplier_id = fab_data.get('supplier_id')
                fab.supplier_name = fab_data.get('supplier_name', '')
                fab.remark = fab_data.get('remark', '')
                if old_val != fab.fabric_name:
                    db.add(ModificationLog(
                        target_type='fabric', target_id=fab.id,
                        field_name='fabric_name', old_value=old_val,
                        new_value=fab.fabric_name, modifier_name=username,
                    ))
            else:
                db.add(ProductFabric(
                    product_id=product_id,
                    fabric_name=fab_data.get('fabric_name', ''),
                    specification=fab_data.get('specification', ''),
                    unit=fab_data.get('unit', ''),
                    quantity=Decimal(str(fab_data.get('quantity', 0))),
                    supplier_id=fab_data.get('supplier_id'),
                    supplier_name=fab_data.get('supplier_name', ''),
                    remark=fab_data.get('remark', ''),
                ))
        else:
            db.add(ProductFabric(
                product_id=product_id,
                fabric_name=fab_data.get('fabric_name', ''),
                specification=fab_data.get('specification', ''),
                unit=fab_data.get('unit', ''),
                quantity=Decimal(str(fab_data.get('quantity', 0))),
                supplier_id=fab_data.get('supplier_id'),
                supplier_name=fab_data.get('supplier_name', ''),
                remark=fab_data.get('remark', ''),
            ))

    accessories_data = data.get('accessories', [])
    for acc_data in accessories_data:
        if acc_data.get('id'):
            acc = await db.get(ProductAccessory, acc_data['id'])
            if acc and acc.product_id == product_id:
                old_val = acc.accessory_name
                acc.accessory_name = acc_data.get('accessory_name', '')
                acc.specification = acc_data.get('specification', '')
                acc.unit = acc_data.get('unit', '')
                acc.quantity = Decimal(str(acc_data.get('quantity', 0)))
                acc.supplier_id = acc_data.get('supplier_id')
                acc.supplier_name = acc_data.get('supplier_name', '')
                acc.remark = acc_data.get('remark', '')
                if old_val != acc.accessory_name:
                    db.add(ModificationLog(
                        target_type='accessory', target_id=acc.id,
                        field_name='accessory_name', old_value=old_val,
                        new_value=acc.accessory_name, modifier_name=username,
                    ))
            else:
                db.add(ProductAccessory(
                    product_id=product_id,
                    accessory_name=acc_data.get('accessory_name', ''),
                    specification=acc_data.get('specification', ''),
                    unit=acc_data.get('unit', ''),
                    quantity=Decimal(str(acc_data.get('quantity', 0))),
                    supplier_id=acc_data.get('supplier_id'),
                    supplier_name=acc_data.get('supplier_name', ''),
                    remark=acc_data.get('remark', ''),
                ))
        else:
            db.add(ProductAccessory(
                product_id=product_id,
                accessory_name=acc_data.get('accessory_name', ''),
                specification=acc_data.get('specification', ''),
                unit=acc_data.get('unit', ''),
                quantity=Decimal(str(acc_data.get('quantity', 0))),
                supplier_id=acc_data.get('supplier_id'),
                supplier_name=acc_data.get('supplier_name', ''),
                remark=acc_data.get('remark', ''),
            ))

    for category, model_cls in [('fabrics', ProductFabric), ('accessories', ProductAccessory)]:
        existing_ids = {item['id'] for item in data.get(category, []) if item.get('id')}
        result = await db.execute(
            select(model_cls).where(
                model_cls.product_id == product_id,
                ~model_cls.id.in_(existing_ids) if existing_ids else True,
            )
        )
        to_delete = result.scalars().all()
        for item in to_delete:
            await db.delete(item)
            db.add(ModificationLog(
                target_type=category[:-1], target_id=item.id,
                field_name='deleted',
                old_value=getattr(item, f'{category[:-2]}y_name', '') or '',
                new_value='(已删除)',
                modifier_name=username,
            ))

    await db.commit()
    return 'BOM 保存成功'


async def calculate_material(db: AsyncSession, orders_data: list) -> dict:
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

    products_result = await db.execute(
        select(Product).options(
            selectinload(Product.material),
            selectinload(Product.fabrics),
            selectinload(Product.accessories),
            selectinload(Product.packagings),
        ).where(Product.id.in_(product_ids))
    )
    products = products_result.scalars().unique().all()
    product_map = {p.id: p for p in products}

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

    for _key, info in totals.items():
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
