"""
采购中心 - 产品/BOM 管理服务

从 purchase_center_service.py 拆分，包含产品查询、BOM 保存和物料计算。
"""
import logging
from decimal import Decimal

from sqlalchemy import func, or_, select, union_all
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from fastapi_app.core.cache import cache_result
from fastapi_app.core.sanitizer import escape_like
from fastapi_app.shared_models import (
    Product,
    ProductAccessory,
    ProductFabric,
    ProductMaterial,
)
from fastapi_app.utils import calc_total_pages

logger = logging.getLogger(__name__)


# BOM 领域逻辑已聚合到 bom_service.py，此处重新导出以保持向后兼容
# （purchase_bom_copy_service、purchase_center_service 等仍从此处导入）
from fastapi_app.services.bom_service import get_bom as get_product_bom  # noqa: F401
from fastapi_app.services.bom_service import has_bom as product_has_bom
from fastapi_app.services.bom_service import save_bom as save_product_bom  # noqa: F401


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
    )
    result = await db.execute(select(subq.c.product_id))
    return {row[0] for row in result}


@cache_result(
    key_prefix="purchase:products",
    ttl=60,
    key_builder=lambda **kwargs: (
        f"p{kwargs.get('page', 1)}:pp{kwargs.get('per_page', 50)}:"
        f"s{(kwargs.get('search', '') or '').strip().lower()}:"
        f"hb{kwargs.get('has_bom', 'all')}:c{kwargs.get('category', '')}:"
        f"sb{kwargs.get('sort_by', 'name')}:so{kwargs.get('sort_order', 'asc')}:"
        f"simp{kwargs.get('simple', False)}"
    ),
)
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
        'pages': calc_total_pages(total, per_page),
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


def aggregate_materials(orders_data: list, product_map: dict) -> dict:
    """按 (分类, 物料名, 供应商, 规格) 聚合物料用量。

    纯函数：无 DB 依赖，便于单元测试聚合策略。

    Args:
        orders_data: 订单列表，每项含 product_id 与 quantity。
        product_map: {product_id: Product} 映射，Product 须实现 has_bom() 与 get_all_materials()。

    Returns:
        dict: {category: [CalcRow, ...]}，category ∈ filling/fabric/accessory/packaging。
    """
    result: dict[str, list[dict]] = {
        'filling': [],
        'fabric': [],
        'accessory': [],
        'packaging': [],
    }
    # 聚合 key 必须包含供应商与规格，避免同名不同供应商/规格的物料被错误合并
    # 使用元组而非字符串拼接，杜绝分隔符 ':' 导致的键冲突
    totals: dict[tuple, dict] = {}

    for order_item in orders_data:
        product_id = order_item.get('product_id')
        quantity = Decimal(str(order_item.get('quantity', 0)))

        product = product_map.get(product_id)
        if not product or not product.has_bom():
            continue

        for mat in product.get_all_materials():
            category = mat.get('category', '')
            name = mat.get('material_name', '')
            supplier_name = mat.get('supplier_name', '') or ''
            specification = mat.get('specification', '') or ''
            key = (category, name, supplier_name, specification)

            bucket = totals.get(key)
            if bucket is None:
                bucket = {
                    'total': Decimal(0),
                    'name': name,
                    'category': category,
                    'unit': mat.get('unit', ''),
                    'supplier_name': supplier_name,
                    'specification': specification,
                    'material_code': mat.get('material_code', ''),
                }
                totals[key] = bucket

            per_unit = Decimal(str(mat.get('unit_usage', 0)))
            bucket['total'] += per_unit * quantity

    for info in totals.values():
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
        else:
            logger.warning('未知物料分类被丢弃: %s (物料: %s)', category, info['name'])

    return result


async def calculate_material(db: AsyncSession, orders_data: list) -> dict:
    result = {
        'filling': [],
        'fabric': [],
        'accessory': [],
        'packaging': [],
    }

    product_ids = [item.get('product_id') for item in orders_data if item.get('product_id')]
    if not product_ids:
        return result

    products_result = await db.execute(
        select(Product).options(
            selectinload(Product.material),
            selectinload(Product.fabrics),
            selectinload(Product.accessories),
        ).where(Product.id.in_(product_ids))
    )
    products = products_result.scalars().unique().all()
    product_map = {p.id: p for p in products}

    return aggregate_materials(orders_data, product_map)
