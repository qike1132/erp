"""
采购中心 - BOM 复制服务

从 purchase_center_service.py 拆分，包含 BOM 复制搜索、预览和执行功能。
"""
import logging
from decimal import Decimal

from sqlalchemy.orm import Session, joinedload

from fastapi_app.services.purchase_product_service import _product_has_bom
from fastapi_app.shared_models import (
    Product,
    ProductAccessory,
    ProductFabric,
    ProductMaterial,
    ProductPackaging,
    PurchaseOrder,
    PurchaseOrderItem,
)

logger = logging.getLogger(__name__)


def search_products_for_bom_copy(db: Session, keyword: str) -> list:
    """搜索产品用于复制BOM

    委托至 product_search_service 统一实现，保持原有返回格式。
    """
    from fastapi_app.services.product_search_service import product_search_service
    return product_search_service.search_for_bom_copy_sync(db, keyword)


def get_bom_preview(db: Session, source_product_id: int) -> dict:
    """获取源产品BOM预览用于复制确认"""
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
    """复制BOM到目标产品"""
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
    """批量删除采购订单"""
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
