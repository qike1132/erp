"""
采购中心 - BOM 复制服务

从 purchase_center_service.py 拆分，包含 BOM 复制搜索、预览和执行功能。
"""
import logging
from decimal import Decimal

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from fastapi_app.services.product_search_service import product_search_service
from fastapi_app.services.purchase_product_service import product_has_bom
from fastapi_app.shared_models import (
    Product,
    ProductAccessory,
    ProductFabric,
    ProductMaterial,
    PurchaseOrder,
    PurchaseOrderItem,
)

logger = logging.getLogger(__name__)


async def search_products_for_bom_copy(db: AsyncSession, keyword: str) -> list:
    if not keyword:
        return []

    query = product_search_service.build_search_query_async(db, keyword)
    query = query.options(
        selectinload(Product.material),
        selectinload(Product.fabrics),
        selectinload(Product.accessories),
    ).limit(20)
    result = await db.execute(query)
    products = result.scalars().unique().all()

    output = []
    for p in products:
        has_bom = product_has_bom(p)
        material_count = (
            len(p.fabrics) + len(p.accessories)
            + (1 if p.material and getattr(p.material, "cotton_usage", Decimal("0")) > 0 else 0)
        )
        output.append({
            "id": p.id,
            "name": p.name,
            "barcode": p.barcode,
            "price": float(p.price) if p.price else 0,
            "has_bom": has_bom,
            "material_count": material_count,
        })

    return output


async def get_bom_preview(db: AsyncSession, source_product_id: int) -> dict:
    result = await db.execute(
        select(Product).options(
            selectinload(Product.material),
            selectinload(Product.fabrics),
            selectinload(Product.accessories),
        ).where(Product.id == source_product_id)
    )
    source_product = result.scalar_one_or_none()
    if not source_product:
        raise ValueError(f'产品ID {source_product_id} 不存在')
    if not product_has_bom(source_product):
        raise ValueError('该产品没有配置BOM表，无法复制')

    bom_data = {
        'filling': None,
        'fabric': [],
        'accessory': [],
    }

    if source_product.material and getattr(source_product.material, 'cotton_usage', Decimal('0')) > 0:
        bom_data['filling'] = source_product.material.to_dict()

    for fabric in source_product.fabrics:
        bom_data['fabric'].append(fabric.to_dict())
    for accessory in source_product.accessories:
        bom_data['accessory'].append(accessory.to_dict())

    material_count = (
        (1 if bom_data['filling'] else 0)
        + len(bom_data['fabric'])
        + len(bom_data['accessory'])
    )

    create_time_str = (
        source_product.create_time.strftime('%Y-%m-%d %H:%M:%S')
        if source_product.create_time else None
    )

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


async def copy_bom_to_product(db: AsyncSession, target_product_id: int, data: dict, username: str = 'unknown') -> dict:
    source_product_id = data.get('source_product_id')
    overwrite = data.get('overwrite', False)

    if not source_product_id:
        raise ValueError('请选择源产品')
    if source_product_id == target_product_id:
        raise ValueError('不能复制到同一产品')

    src_result = await db.execute(
        select(Product).options(
            selectinload(Product.material),
            selectinload(Product.fabrics),
            selectinload(Product.accessories),
        ).where(Product.id == source_product_id)
    )
    source_product = src_result.scalar_one_or_none()

    tgt_result = await db.execute(
        select(Product).options(
            selectinload(Product.material),
            selectinload(Product.fabrics),
            selectinload(Product.accessories),
        ).where(Product.id == target_product_id)
    )
    target_product = tgt_result.scalar_one_or_none()

    if not source_product:
        raise ValueError(f'源产品ID {source_product_id} 不存在')
    if not target_product:
        raise ValueError(f'目标产品ID {target_product_id} 不存在')
    if not product_has_bom(source_product):
        raise ValueError('源产品没有配置BOM表')
    if not overwrite and product_has_bom(target_product):
        raise ValueError('目标产品已有BOM表，请确认是否覆盖')

    copied_count = 0

    if overwrite:
        await db.execute(delete(ProductMaterial).where(ProductMaterial.product_id == target_product_id))
        await db.execute(delete(ProductFabric).where(ProductFabric.product_id == target_product_id))
        await db.execute(delete(ProductAccessory).where(ProductAccessory.product_id == target_product_id))

    if source_product.material and getattr(source_product.material, 'cotton_usage', Decimal('0')) > 0:
        old_mat = source_product.material
        db.add(ProductMaterial(
            product_id=target_product_id,
            material_code=getattr(old_mat, 'material_code', '') or '',
            cotton_usage=old_mat.cotton_usage,
            specification=getattr(old_mat, 'specification', '') or '',
            supplier_id=getattr(old_mat, 'supplier_id', None),
            supplier_name=getattr(old_mat, 'supplier_name', '') or '',
            unit=getattr(old_mat, 'unit', '') or '克',
            remark=getattr(old_mat, 'remark', '') or '',
        ))
        copied_count += 1

    for old_fabric in source_product.fabrics:
        db.add(ProductFabric(
            product_id=target_product_id,
            material_code=getattr(old_fabric, 'material_code', '') or '',
            fabric_name=old_fabric.fabric_name,
            specification=getattr(old_fabric, 'specification', '') or '',
            quantity=old_fabric.quantity,
            supplier_id=getattr(old_fabric, 'supplier_id', None),
            supplier_name=getattr(old_fabric, 'supplier_name', '') or '',
            unit=getattr(old_fabric, 'unit', '') or '码',
            remark=getattr(old_fabric, 'remark', '') or '',
        ))
        copied_count += 1

    for old_accessory in source_product.accessories:
        db.add(ProductAccessory(
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
        ))
        copied_count += 1

    await db.commit()

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


async def batch_delete_purchase_orders(db: AsyncSession, order_ids: list, username: str = 'unknown') -> dict:
    if not order_ids:
        raise ValueError('请选择要删除的订单')

    result = await db.execute(select(PurchaseOrder).where(PurchaseOrder.id.in_(order_ids)))
    orders_to_delete = result.scalars().all()
    if not orders_to_delete:
        raise ValueError('未找到要删除的订单')

    deleted_info = []
    for order in orders_to_delete:
        count_result = await db.execute(
            select(func.count(PurchaseOrderItem.id)).where(PurchaseOrderItem.order_id == order.id)
        )
        item_count = count_result.scalar()
        deleted_info.append({
            'order_no': order.order_no,
            'supplier_name': order.supplier_name or '',
            'customer_name': order.customer_name or '',
            'item_count': item_count,
        })
        await db.delete(order)

    await db.commit()

    logger.warning(
        f'批量删除采购订单 | 操作人: {username} | '
        f'删除数量: {len(deleted_info)} | '
        f"订单编号: {', '.join(info['order_no'] for info in deleted_info)}"
    )

    return {
        'message': f'成功删除 {len(deleted_info)} 个订单',
        'deleted_count': len(deleted_info),
    }
