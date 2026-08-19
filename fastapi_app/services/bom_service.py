"""
BOM（物料清单）领域服务 - 深模块聚合

将原分散于 product_service、purchase_product_service、purchase_bom_copy_service、
product_search_service 四个文件中的 BOM 领域逻辑聚合为单一深模块，统一对外提供
BOM 的查询、保存、复制、预览与搜索能力。

入口函数（共 6 个）：
1. has_bom(product) -> bool
   判断产品是否配置了 BOM（填充物/面料/辅料任一有数据即视为有 BOM）。
2. get_bom(db, product_id) -> dict
   获取产品的完整 BOM 明细（含填充物、面料、辅料列表）。
3. save_bom(db, product_id, data, username) -> str
   保存产品 BOM，支持填充物(1:1)、面料(1:N)、辅料(1:N) 的增删改与变更日志。
4. copy_bom(db, target_product_id, data, username) -> dict
   将源产品 BOM 复制到目标产品，支持覆盖模式。
5. preview_bom(db, source_product_id) -> dict
   预览源产品 BOM 结构，供复制前确认。
6. search_for_bom_copy(db, keyword) -> list
   搜索可用于 BOM 复制的产品（含 has_bom 标记与物料计数）。

三类物料映射规则：
- filling（填充物）: ProductMaterial 模型，与产品 1:1 关系，
  以 cotton_usage 字段 > 0 判定存在；保存时走单独的 1:1 分支（未纳入
  _save_material_bom_items 通用框架，因其结构与 1:N 列表差异较大）。
- fabric（面料）: ProductFabric 模型，与产品 1:N 关系，
  名称字段为 fabric_name，日志 target_type 为 'fabric'。
- accessory（辅料）: ProductAccessory 模型，与产品 1:N 关系，
  名称字段为 accessory_name，日志 target_type 为 'accessory'。
"""
import json
import logging
from decimal import Decimal

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from fastapi_app.shared_models import (
    ModificationLog,
    Product,
    ProductAccessory,
    ProductFabric,
    ProductMaterial,
)

logger = logging.getLogger(__name__)


def has_bom(product) -> bool:
    """判断产品是否配置了BOM（任意一类物料有数据即视为有BOM）

    从 purchase_product_service.py 提取至 product_service.py，
    消除 product_search_service ↔ purchase_product_service 的循环依赖。
    purchase_product_service 仍重新导出此函数以保持向后兼容。
    """
    has_filling = (
        product.material is not None and
        getattr(product.material, 'cotton_usage', Decimal('0')) > 0
    )
    has_fabric = hasattr(product, 'fabrics') and len(product.fabrics) > 0
    has_accessory = hasattr(product, 'accessories') and len(product.accessories) > 0
    return has_filling or has_fabric or has_accessory


async def get_bom(db: AsyncSession, product_id: int) -> dict:
    result = await db.execute(
        select(Product).options(
            selectinload(Product.material),
            selectinload(Product.fabrics),
            selectinload(Product.accessories),
        ).where(Product.id == product_id)
    )
    product = result.scalars().first()
    if not product:
        return None
    all_materials = product.get_all_materials() if product.has_bom() else []
    return {
        'id': product.id,
        'name': product.name,
        'barcode': product.barcode,
        'materials': all_materials,
    }


async def _save_material_bom_items(
    db: AsyncSession,
    product_id: int,
    items: list,
    material_type: str,
    model_class,
    username: str,
) -> None:
    """保存 1:N 物料 BOM 明细（面料/辅料）的通用框架。

    处理逻辑：
    - 对每条 item：若含 id 则更新对应记录（需校验 product_id 一致），
      否则新建一条属于当前 product_id 的记录。
    - 名称字段变更时写入 ModificationLog。

    Args:
        db: 异步会话。
        product_id: 当前产品 ID，用于归属校验与新建记录。
        items: 前端传入的物料明细列表（dict 列表）。
        material_type: 物料类别标识，'fabric' 或 'accessory'，
            用于定位 name 字段与日志 target_type。
        model_class: ORM 模型类（ProductFabric / ProductAccessory）。
        username: 操作人，用于 ModificationLog。
    """
    # 各类物料的名称字段与日志 target_type 映射
    _meta = {
        'fabric': {'name_field': 'fabric_name', 'log_type': 'fabric'},
        'accessory': {'name_field': 'accessory_name', 'log_type': 'accessory'},
    }
    meta = _meta[material_type]
    name_field = meta['name_field']
    log_type = meta['log_type']

    # 批量预取待更新记录，避免循环内逐条 db.get 造成 N+1 查询
    item_ids = [it.get('id') for it in items if it.get('id')]
    existing_map: dict = {}
    if item_ids:
        existing_result = await db.execute(
            select(model_class).where(model_class.id.in_(item_ids))
        )
        existing_map = {obj.id: obj for obj in existing_result.scalars().all()}

    for item_data in items:
        item_id = item_data.get('id')
        if item_id:
            existing = existing_map.get(item_id)
            if existing and existing.product_id == product_id:
                old_val = getattr(existing, name_field)
                setattr(existing, name_field, item_data.get(name_field, ''))
                existing.specification = item_data.get('specification', '')
                existing.unit = item_data.get('unit', '')
                existing.quantity = Decimal(str(item_data.get('quantity', 0)))
                existing.supplier_id = item_data.get('supplier_id')
                existing.supplier_name = item_data.get('supplier_name', '')
                existing.remark = item_data.get('remark', '')
                new_val = getattr(existing, name_field)
                if old_val != new_val:
                    db.add(ModificationLog(
                        target_type=log_type, target_id=existing.id,
                        field_name=name_field, old_value=old_val,
                        new_value=new_val, modifier_name=username,
                    ))
                continue
        # 新建（含 id 不匹配当前产品的情况，与原实现一致）
        db.add(model_class(
            product_id=product_id,
            **{name_field: item_data.get(name_field, '')},
            specification=item_data.get('specification', ''),
            unit=item_data.get('unit', ''),
            quantity=Decimal(str(item_data.get('quantity', 0))),
            supplier_id=item_data.get('supplier_id'),
            supplier_name=item_data.get('supplier_name', ''),
            remark=item_data.get('remark', ''),
        ))


async def save_bom(db: AsyncSession, product_id: int, data: dict, username: str) -> str:
    result = await db.execute(
        select(Product).options(
            selectinload(Product.material),
            selectinload(Product.fabrics),
            selectinload(Product.accessories),
        ).where(Product.id == product_id)
    )
    product = result.scalars().first()
    if not product:
        raise ValueError('产品不存在')

    filling_data = data.get('filling')
    # TODO: filling 为 1:1 关系（cotton_usage 字段 + 多字段日志），结构与 fabric/accessory 的
    # 1:N 列表模式差异较大，未纳入 _save_material_bom_items 通用框架以避免改变业务语义。
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
    await _save_material_bom_items(db, product_id, fabrics_data, 'fabric', ProductFabric, username)

    accessories_data = data.get('accessories', [])
    await _save_material_bom_items(db, product_id, accessories_data, 'accessory', ProductAccessory, username)

    _delete_meta = {
        'fabrics': ('fabric', 'fabric_name'),
        'accessories': ('accessory', 'accessory_name'),
    }
    for category, model_cls in [('fabrics', ProductFabric), ('accessories', ProductAccessory)]:
        existing_ids = {item['id'] for item in data.get(category, []) if item.get('id')}
        result = await db.execute(  # batch-loop: 有意逐行处理,非 N+1
            select(model_cls).where(
                model_cls.product_id == product_id,
                ~model_cls.id.in_(existing_ids) if existing_ids else True,
            )
        )
        to_delete = result.scalars().all()
        target_type, name_attr = _delete_meta[category]
        if to_delete:
            # 先采集审计日志所需字段，再单条批量 DELETE 替代逐条 session.delete
            delete_ids = []
            for item in to_delete:
                delete_ids.append(item.id)
                db.add(ModificationLog(
                    target_type=target_type, target_id=item.id,
                    field_name='deleted',
                    old_value=getattr(item, name_attr, '') or '',
                    new_value='(已删除)',
                    modifier_name=username,
                ))
            await db.execute(delete(model_cls).where(model_cls.id.in_(delete_ids)))  # batch-loop: 有意逐行处理,非 N+1

    return 'BOM 保存成功'


async def copy_bom(db: AsyncSession, target_product_id: int, data: dict, username: str = 'unknown') -> dict:
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
    if not has_bom(source_product):
        raise ValueError('源产品没有配置BOM表')
    if not overwrite and has_bom(target_product):
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

    await db.flush()

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


async def preview_bom(db: AsyncSession, source_product_id: int) -> dict:
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
    if not has_bom(source_product):
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


async def search_for_bom_copy(db: AsyncSession, keyword: str) -> list:
    from fastapi_app.services.product_search_service import product_search_service

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
        has_bom_flag = has_bom(p)
        material_count = (
            len(p.fabrics) + len(p.accessories)
            + (1 if p.material and getattr(p.material, "cotton_usage", Decimal("0")) > 0 else 0)
        )
        output.append({
            "id": p.id,
            "name": p.name,
            "barcode": p.barcode,
            "price": float(p.price) if p.price else 0,
            "has_bom": has_bom_flag,
            "material_count": material_count,
        })

    return output
