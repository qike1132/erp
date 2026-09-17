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
   将源产品 BOM 复制到目标产品，支持覆盖模式；
   当 data 携带 role_id 时复制到该指定角色（不新建角色、不波及默认/其他角色）；
   当 role_id 为空但携带 role_name 时，在目标产品中按名称查找角色（幂等），
   不存在则新建后再复制，用于支持前端尚未保存的新角色。
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

from sqlalchemy import delete, inspect as sa_inspect, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import InstanceState, selectinload

from fastapi_app.shared_models import (
    ModificationLog,
    Product,
    ProductAccessory,
    ProductFabric,
    ProductMaterial,
    ProductRole,
)
from fastapi_app.services.product.bom_role_resolver import resolve_role_rows
from fastapi_app.services.product.role_service import ensure_global_role

logger = logging.getLogger(__name__)


def has_bom(product) -> bool:
    """判断产品是否配置了BOM（任意一类物料有数据即视为有BOM）

    从 purchase_product_service.py 提取至 product_service.py，
    消除 product_search_service ↔ purchase_product_service 的循环依赖。
    purchase_product_service 仍重新导出此函数以保持向后兼容。

    填充物判定含各角色行（material_rows 已加载时按全量统计）；
    未加载 material_rows 的旧调用方回退到产品级 material（1:1 兼容）。

    注意：material_rows 为 lazy="raise" 关系，禁止直接 getattr 探测——
    那会触发关系加载并抛 InvalidRequestError（生产 /products/search 500 根因）。
    用 inspect().unloaded 判断是否已加载，未加载时静默回退。
    """
    state = sa_inspect(product)
    if isinstance(state, InstanceState):
        rows = None if 'material_rows' in state.unloaded else product.material_rows
    else:
        # 非 ORM 实体（测试桩等）：直接访问属性
        rows = getattr(product, 'material_rows', None)
    if isinstance(rows, list):
        has_filling = any(getattr(m, 'cotton_usage', Decimal('0')) > 0 for m in rows)
    else:
        has_filling = (
            getattr(product, 'material', None) is not None
            and getattr(product.material, 'cotton_usage', Decimal('0')) > 0
        )
    if isinstance(state, InstanceState):
        has_fabric = 'fabrics' not in state.unloaded and len(product.fabrics) > 0
        has_accessory = 'accessories' not in state.unloaded and len(product.accessories) > 0
    else:
        # 非 ORM 实体（测试桩等）：直接访问属性
        has_fabric = len(getattr(product, 'fabrics', []) or []) > 0
        has_accessory = len(getattr(product, 'accessories', []) or []) > 0
    return has_filling or has_fabric or has_accessory


def _loaded_relation(entity, name: str):
    """安全读取 ORM 关系。

    对已加载关系返回其值；对 ``lazy='raise'`` 且未加载的关系返回 ``None``，
    避免触发关系加载抛 ``InvalidRequestError``（与 ``has_bom`` 同一套判断）。
    非 ORM 实体（测试桩等）直接取属性。

    Args:
        entity: ORM 实体或测试桩。
        name: 关系属性名。

    Returns:
        关系值；未加载时返回 ``None``。
    """
    state = sa_inspect(entity)
    if isinstance(state, InstanceState):
        if name in state.unloaded:
            return None
        return getattr(entity, name)
    return getattr(entity, name, None)


def _role_display_name(product_role) -> str:
    """角色展示名：优先全局角色名（§7#10），回退回滚镜像列 ``role_name``。

    调用方（``get_bom``）必须已 ``selectinload(ProductRole.global_role)``，
    否则 ``lazy='raise'`` 关系会抛 ``InvalidRequestError``（生产 500 历史根因）。
    """
    global_role = getattr(product_role, 'global_role', None)
    if global_role is not None:
        name = getattr(global_role, 'name', None)
        if name:
            return name
    return product_role.role_name or ''


def _role_has_materials(product, role_id: int) -> bool:
    """判断产品在指定角色名下是否已有 BOM 物料。

    仅统计归属该角色（``role_id`` 相等）且填充用量大于 0 的物料，
    用于目标角色模式下 ``overwrite=False`` 时的冲突判定。

    Args:
        product: 目标产品（应已加载 fabrics/accessories/material_rows）。
        role_id: 角色 ID。

    Returns:
        bool: 该角色下存在任一物料即返回 ``True``。
    """
    for fabric in (_loaded_relation(product, 'fabrics') or []):
        if getattr(fabric, 'role_id', None) == role_id:
            return True
    for accessory in (_loaded_relation(product, 'accessories') or []):
        if getattr(accessory, 'role_id', None) == role_id:
            return True
    rows = _loaded_relation(product, 'material_rows')
    if isinstance(rows, list):
        for material in rows:
            if (
                getattr(material, 'role_id', None) == role_id
                and getattr(material, 'cotton_usage', Decimal('0')) > 0
            ):
                return True
    return False


async def get_bom(db: AsyncSession, product_id: int) -> dict | None:
    """查询产品 BOM（含角色列表与物料）

    产品不存在时返回 ``None`` —— 注解必须带 ``| None``，
    否则调用方会误以为返回值恒为 dict 而漏掉空值检查。

    ``roles`` 每项含 ``{id(product_role.id), global_role_id, name}``，展示名取自全局
    角色名（回退镜像列），并按 ``(name, id)`` 升序（REQ-P0-10 / §7#2、#10）。
    """
    result = await db.execute(
        select(Product).options(
            selectinload(Product.material),
            selectinload(Product.material_rows),
            selectinload(Product.fabrics),
            selectinload(Product.accessories),
            selectinload(Product.roles).selectinload(ProductRole.global_role),
        ).where(Product.id == product_id)
    )
    product = result.scalars().first()
    if not product:
        return None
    all_materials = product.get_all_materials() if product.has_bom() else []
    role_items = [
        {
            'id': r.id,
            'global_role_id': r.global_role_id,
            'name': _role_display_name(r),
        }
        for r in product.roles
    ]
    role_items.sort(key=lambda item: (item['name'], item['id']))
    return {
        'id': product.id,
        'name': product.name,
        'barcode': product.barcode,
        'default_bom_label': product.default_bom_label,
        'roles': role_items,
        'materials': all_materials,
    }


async def _save_material_bom_items(
    db: AsyncSession,
    product_id: int,
    items: list,
    material_type: str,
    model_class,
    username: str,
    temp_role_map: dict | None = None,
) -> None:
    """保存 1:N 物料 BOM 明细（面料/辅料）的通用框架。

    处理逻辑：
    - 对每条 item：若含 id 则更新对应记录（需校验 product_id 一致），
      否则新建一条属于当前 product_id 的记录。
    - 名称字段变更时写入 ModificationLog。
    - role_id 归属：物料项可携带 role_id（真实角色），或 role_key（本次新建角色的
      客户端临时键，由 temp_role_map 解析为真实 id）。

    Args:
        db: 异步会话。
        product_id: 当前产品 ID，用于归属校验与新建记录。
        items: 前端传入的物料明细列表（dict 列表）。
        material_type: 物料类别标识，'fabric' 或 'accessory'，
            用于定位 name 字段与日志 target_type。
        model_class: ORM 模型类（ProductFabric / ProductAccessory）。
        username: 操作人，用于 ModificationLog。
        temp_role_map: 客户端 role_key -> 新建角色 id 映射（可选）。
    """
    temp_role_map = temp_role_map or {}
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
        role_id = item_data.get('role_id')
        if role_id is None:
            role_id = temp_role_map.get(item_data.get('role_key'))
        if item_id:
            existing = existing_map.get(item_id)
            if existing and existing.product_id == product_id:
                old_val = getattr(existing, name_field)
                setattr(existing, name_field, item_data.get(name_field, ''))
                existing.role_id = role_id  # 归属可迁移（角色变更时挂到新角色）
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
            role_id=role_id,
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
            selectinload(Product.material_rows),
            selectinload(Product.fabrics),
            selectinload(Product.accessories),
            selectinload(Product.roles),
        ).where(Product.id == product_id)
    )
    product = result.scalars().first()
    if not product:
        raise ValueError('产品不存在')

    # ===== 默认 BOM 自定义名称（default_bom_label 键存在才更新，旧客户端不传则保持原状） =====
    if 'default_bom_label' in data:
        label = (data.get('default_bom_label') or '').strip() or None
        if label != product.default_bom_label:
            if label is not None:
                db.add(ModificationLog(
                    target_type='product', target_id=product.id,
                    field_name='default_bom_label',
                    old_value=product.default_bom_label or '', new_value=label,
                    modifier_name=username,
                ))
            product.default_bom_label = label

    # ===== 角色保存（roles 键存在才执行全量替换，旧客户端不传则保持原状） =====
    # 角色段解析抽到 bom_role_resolver（支持 global_role_id / role_key / id 三路径），
    # 避免本文件继续膨胀（958 行已超服务文件上限，风险 M2）。
    temp_role_map: dict = {}  # 客户端临时 role_key -> 新建角色真实 id
    if 'roles' in data:
        resolution = await resolve_role_rows(
            payload_roles=data.get('roles') or [],
            existing_product_roles=list(product.roles),
            db=db,
            product_id=product_id,
            username=username,
        )
        temp_role_map = resolution.temp_role_map
        role_ids = resolution.role_ids
        # 删除未出现在 payload 中的角色（物料由 DB 级 FK ON DELETE CASCADE 清理）
        to_delete = [r for r in product.roles if r.id not in role_ids]
        for role in to_delete:
            db.add(ModificationLog(
                target_type='role', target_id=role.id,
                field_name='deleted',
                old_value=role.role_name or '', new_value='(已删除)',
                modifier_name=username,
            ))
            # AsyncSession.delete 是**协程**（SQLAlchemy 2.0 async API），
            # 漏 await 会导致协程被丢弃、角色**静默不删除**。
            await db.delete(role)

    def _resolve_role_id(item: dict):
        """物料项 role_id：优先真实 id，其次用 role_key 映射新建角色"""
        rid = item.get('role_id')
        if rid is not None:
            return rid
        role_key = item.get('role_key')
        if role_key:
            return temp_role_map.get(role_key)
        return None

    # 填充物：支持 fillings 列表（每角色一条），兼容旧字段 filling（产品级）
    fillings_data = data.get('fillings')
    if not fillings_data and data.get('filling'):
        fillings_data = [data['filling']]
    # 批量预取填充物，避免循环内 N+1 查询
    existing_map: dict = {}
    if fillings_data:
        filling_role_ids = [_resolve_role_id(fd) for fd in fillings_data]
        non_none_ids = [rid for rid in filling_role_ids if rid]
        has_none_role = any(rid is None for rid in filling_role_ids)
        or_conditions = []
        if non_none_ids:
            or_conditions.append(ProductMaterial.role_id.in_(non_none_ids))
        if has_none_role:
            or_conditions.append(ProductMaterial.role_id.is_(None))
        if or_conditions:
            batch_result = await db.execute(
                select(ProductMaterial).where(
                    ProductMaterial.product_id == product_id,
                    or_(*or_conditions),
                )
            )
            existing_map = {m.role_id: m for m in batch_result.scalars()}

    for filling_data in fillings_data or []:
        filling_role_id = _resolve_role_id(filling_data)
        filling_material = existing_map.get(filling_role_id)
        if filling_material:
            old_data = {
                'cotton_usage': float(filling_material.cotton_usage) if filling_material.cotton_usage else 0,
                'supplier_name': filling_material.supplier_name,
            }
            filling_material.role_id = filling_role_id
            filling_material.cotton_usage = Decimal(str(filling_data.get('cotton_usage', 0)))
            filling_material.supplier_id = filling_data.get('supplier_id')
            filling_material.supplier_name = filling_data.get('supplier_name', '')
            filling_material.specification = filling_data.get('specification', '')
            filling_material.unit = filling_data.get('unit', '')
            filling_material.remark = filling_data.get('remark', '')
            new_data = {
                'cotton_usage': float(filling_material.cotton_usage),
                'supplier_name': filling_material.supplier_name,
            }
            if old_data != new_data:
                db.add(ModificationLog(
                    target_type='material', target_id=filling_material.id,
                    field_name='filling_data',
                    old_value=json.dumps(old_data, ensure_ascii=False),
                    new_value=json.dumps(new_data, ensure_ascii=False),
                    modifier_name=username,
                ))
        else:
            db.add(ProductMaterial(
                product_id=product_id,
                role_id=filling_role_id,
                cotton_usage=Decimal(str(filling_data.get('cotton_usage', 0))),
                supplier_id=filling_data.get('supplier_id'),
                supplier_name=filling_data.get('supplier_name', ''),
                specification=filling_data.get('specification', ''),
                unit=filling_data.get('unit', ''),
                remark=filling_data.get('remark', ''),
            ))

    fabrics_data = data.get('fabrics', [])
    await _save_material_bom_items(db, product_id, fabrics_data, 'fabric', ProductFabric, username, temp_role_map)

    accessories_data = data.get('accessories', [])
    await _save_material_bom_items(db, product_id, accessories_data, 'accessory', ProductAccessory, username, temp_role_map)

    # 角色感知客户端才执行"payload 外删除"（与角色全量替换同门控，避免旧客户端误删角色物料）
    if 'roles' in data:
        # 面料/辅料：删除未出现在 payload 中的行（含各角色行）
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

        # 填充物：删除未出现在 payload 中的行（含产品级与各角色行）
        submitted_filling_ids = [fd.get('id') for fd in fillings_data or [] if fd.get('id')]
        filling_result = await db.execute(
            select(ProductMaterial).where(
                ProductMaterial.product_id == product_id,
                ~ProductMaterial.id.in_(submitted_filling_ids) if submitted_filling_ids else True,
            )
        )
        fillings_to_delete = filling_result.scalars().all()
        if fillings_to_delete:
            filling_delete_ids = []
            for item in fillings_to_delete:
                filling_delete_ids.append(item.id)
                db.add(ModificationLog(
                    target_type='material', target_id=item.id,
                    field_name='deleted',
                    old_value='填充物', new_value='(已删除)',
                    modifier_name=username,
                ))
            await db.execute(delete(ProductMaterial).where(ProductMaterial.id.in_(filling_delete_ids)))  # batch-loop: 有意逐行处理,非 N+1

    return 'BOM 保存成功'


def _add_default_scope_items_to_role(
    db: AsyncSession,
    source_product,
    target_product_id: int,
    role_id: int,
) -> int:
    """把源产品「产品级默认作用域」的面料/辅料/填充物写入目标产品的目标角色。

    仅处理 role_id 为 NULL 的默认作用域物料（角色级物料无法并入单一角色，另行统计为
    skipped_role_items）。返回本次新增的物料行数（copied_count）。

    说明：本函数为纯机械抽取，行为与抽取前 `_copy_bom_into_role` 的内联实现完全等价。
    """
    copied_count = 0

    default_material = getattr(source_product, 'material', None)
    if default_material is not None and getattr(default_material, 'cotton_usage', Decimal('0')) > 0:
        db.add(ProductMaterial(
            product_id=target_product_id,
            role_id=role_id,
            material_code=getattr(default_material, 'material_code', '') or '',
            cotton_usage=default_material.cotton_usage,
            specification=getattr(default_material, 'specification', '') or '',
            supplier_id=getattr(default_material, 'supplier_id', None),
            supplier_name=getattr(default_material, 'supplier_name', '') or '',
            unit=getattr(default_material, 'unit', '') or '克',
            remark=getattr(default_material, 'remark', '') or '',
        ))
        copied_count += 1

    for old_fabric in (getattr(source_product, 'fabrics', None) or []):
        if old_fabric.role_id is not None:
            continue
        db.add(ProductFabric(
            product_id=target_product_id,
            role_id=role_id,
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

    for old_accessory in (getattr(source_product, 'accessories', None) or []):
        if old_accessory.role_id is not None:
            continue
        db.add(ProductAccessory(
            product_id=target_product_id,
            role_id=role_id,
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

    return copied_count


async def _copy_bom_into_role(
    db: AsyncSession,
    source_product,
    target_product,
    target_product_id: int,
    role_id: int,
    overwrite: bool,
    username: str,
) -> dict:
    """将源产品默认作用域 BOM 复制到目标产品的指定角色。

    目标角色模式（``role_id`` 不为空）语义：
    - 只把源产品**产品级默认 BOM**（``role_id`` 为 NULL）的面料/辅料/填充
      写入目标产品的目标角色（``role_id=目标角色id``）；
    - 不新建任何 ``ProductRole``，也不改动目标产品的默认作用域与其他角色；
    - ``overwrite=True`` 时仅清理该角色名下既有物料行，绝不触碰默认作用域与其他角色；
    - 源产品的角色级物料无法并入单一角色（受唯一约束
      ``uq_product_material_product_role`` 限制），计入 ``skipped_role_items`` 供前端提示。

    Args:
        db: 异步数据库会话。
        source_product: 源产品（已加载 fabrics/accessories/material/material_rows）。
        target_product: 目标产品（已加载 fabrics/accessories/material_rows/roles）。
        target_product_id: 目标产品 ID。
        role_id: 目标角色 ID，必须属于目标产品。
        overwrite: 是否覆盖目标角色已有物料。
        username: 操作人名称（用于日志）。

    Returns:
        dict: 含 message / copied_count / skipped_role_items / target_role 的复制结果。

    Raises:
        ValueError: 目标角色不存在或不属于该产品；或目标角色已有物料且未覆盖。
    """
    # a. 校验角色存在且属于目标产品
    role = next(
        (r for r in (getattr(target_product, 'roles', None) or []) if getattr(r, 'id', None) == role_id),
        None,
    )
    if role is None:
        raise ValueError('目标角色不存在或不属于该产品')

    # e. 目标角色已有物料且不覆盖 → 沿用「已有BOM」冲突语义
    if not overwrite and _role_has_materials(target_product, role_id):
        raise ValueError('目标角色已有BOM表，请确认是否覆盖')

    # 源产品所有填充物（含各角色行，用于统计被跳过的角色级物料）
    src_mat_result = await db.execute(
        select(ProductMaterial).where(ProductMaterial.product_id == source_product.id)
    )
    source_materials = src_mat_result.scalars().all()

    # d. 覆盖：仅删除该角色名下的物料行（绝不删除 ProductRole 或默认/其他角色数据）
    if overwrite:
        await db.execute(delete(ProductFabric).where(
            ProductFabric.product_id == target_product_id,
            ProductFabric.role_id == role_id,
        ))
        await db.execute(delete(ProductAccessory).where(
            ProductAccessory.product_id == target_product_id,
            ProductAccessory.role_id == role_id,
        ))
        await db.execute(delete(ProductMaterial).where(
            ProductMaterial.product_id == target_product_id,
            ProductMaterial.role_id == role_id,
        ))

    # c. 源产品默认作用域 → 目标角色（抽出为纯机械辅助函数，保持行为等价、降低本函数行数）
    copied_count = _add_default_scope_items_to_role(
        db, source_product, target_product_id, role_id,
    )

    # 源产品角色级物料无法并入单一角色（会撞唯一约束），统计跳过数供前端提示
    skipped_role_items = (
        sum(1 for f in (getattr(source_product, 'fabrics', None) or []) if f.role_id is not None)
        + sum(1 for a in (getattr(source_product, 'accessories', None) or []) if a.role_id is not None)
        + sum(1 for m in source_materials if getattr(m, 'role_id', None) is not None)
    )

    await db.flush()

    role_name = getattr(role, 'role_name', None) or getattr(role, 'name', '') or ''
    logger.info(
        f'BOM复制成功(目标角色) | 操作人: {username} | '
        f'源产品: {source_product.name}({source_product.id}) | '
        f'目标产品: {target_product.name}({target_product_id}) | '
        f'目标角色: {role_name}({role_id}) | '
        f'复制物料数: {copied_count} | 跳过角色级物料: {skipped_role_items} | 覆盖: {overwrite}'
    )

    return {
        'message': f'BOM复制成功，共复制 {copied_count} 项物料到角色「{role_name}」',
        'copied_count': copied_count,
        'skipped_role_items': skipped_role_items,
        'target_role': {'id': role_id, 'name': role_name},
        'source_product': {'id': source_product.id, 'name': source_product.name},
        'target_product': {'id': target_product.id, 'name': target_product.name},
    }


async def copy_bom(db: AsyncSession, target_product_id: int, data: dict, username: str = 'unknown') -> dict:
    source_product_id = data.get('source_product_id')
    overwrite = data.get('overwrite', False)
    role_id = data.get('role_id')

    if not source_product_id:
        raise ValueError('请选择源产品')
    if source_product_id == target_product_id:
        raise ValueError('不能复制到同一产品')

    src_result = await db.execute(
        select(Product).options(
            selectinload(Product.material),
            selectinload(Product.material_rows),
            selectinload(Product.fabrics),
            selectinload(Product.accessories),
            selectinload(Product.roles),
        ).where(Product.id == source_product_id)
    )
    source_product = src_result.scalar_one_or_none()

    tgt_result = await db.execute(
        select(Product).options(
            selectinload(Product.material),
            selectinload(Product.material_rows),
            selectinload(Product.fabrics),
            selectinload(Product.accessories),
            selectinload(Product.roles),
        ).where(Product.id == target_product_id)
    )
    target_product = tgt_result.scalar_one_or_none()

    if not source_product:
        raise ValueError(f'源产品ID {source_product_id} 不存在')
    if not target_product:
        raise ValueError(f'目标产品ID {target_product_id} 不存在')
    if not has_bom(source_product):
        raise ValueError('源产品没有配置BOM表')

    # ===== 目标角色模式：复制到当前选中的自定义角色 =====
    if role_id is not None:
        return await _copy_bom_into_role(
            db, source_product, target_product, target_product_id, role_id, overwrite, username,
        )

    # ===== 目标角色名模式：按名称查找或新建角色后复制（支持前端未保存的新角色）=====
    role_name = (data.get('role_name') or '').strip()
    if role_name:
        target_roles = list(getattr(target_product, 'roles', None) or [])
        # a. 目标产品已有同名角色（镜像列）→ 幂等复用
        role = next(
            (
                r for r in target_roles
                if (getattr(r, 'role_name', None) or getattr(r, 'name', '') or '').strip() == role_name
            ),
            None,
        )
        if role is None:
            # b. 按名称查找或新建全局角色（copy_bom 不产生审计噪音）
            global_role = await ensure_global_role(db, role_name, username)
            # c. 目标产品已关联同一全局角色（镜像名漂移）→ 复用，避免撞
            #    uq_product_role_product_global(product_id, global_role_id)
            role = next(
                (r for r in target_roles if getattr(r, 'global_role_id', None) == global_role.id),
                None,
            )
        if role is None:
            # d. 新建关联行：global_role_id 必填（迁移 045 后 NOT NULL），role_name 取全局角色名
            role = ProductRole(
                product_id=target_product_id,
                global_role_id=global_role.id,
                role_name=global_role.name,
            )
            db.add(role)
            await db.flush()
            # 挂进关系集合，否则 _copy_bom_into_role 的归属校验会误判「角色不属于该产品」
            target_product.roles.append(role)
        return await _copy_bom_into_role(
            db, source_product, target_product, target_product_id, role.id, overwrite, username,
        )

    # ===== 以下为 role_id 为空时的原有逻辑，保持行为完全不变 =====
    if not overwrite and has_bom(target_product):
        raise ValueError('目标产品已有BOM表，请确认是否覆盖')

    # 源产品所有填充物（含各角色行，source_product.material 仅为产品级）
    src_mat_result = await db.execute(
        select(ProductMaterial).where(ProductMaterial.product_id == source_product_id)
    )
    source_materials = src_mat_result.scalars().all()

    copied_count = 0

    if overwrite:
        # 先删目标角色（DB 级 FK CASCADE 一并清理其物料），再删产品级物料
        await db.execute(delete(ProductRole).where(ProductRole.product_id == target_product_id))
        await db.execute(delete(ProductMaterial).where(ProductMaterial.product_id == target_product_id))
        await db.execute(delete(ProductFabric).where(ProductFabric.product_id == target_product_id))
        await db.execute(delete(ProductAccessory).where(ProductAccessory.product_id == target_product_id))

    # ===== 产品级默认 BOM（role_id 为 NULL） =====
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
        if old_fabric.role_id is not None:
            continue
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
        if old_accessory.role_id is not None:
            continue
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

    # ===== 角色及其独立物料 =====
    # 先批量建角色并单次 flush 取 id（原逐 role flush 为 R 次往返），
    # 再按 role_id 建索引，避免对 fabrics/accessories/materials 的 R 次嵌套扫描。
    # 每个新关联行必须携带 global_role_id（迁移 045 后 NOT NULL + FK RESTRICT）；
    # 覆盖模式已在上方批量删除目标全部角色，故仅非覆盖模式需按 global_role_id 去重。
    target_by_global: dict[int, ProductRole] = {}
    if not overwrite:
        for existing_role in (getattr(target_product, 'roles', None) or []):
            gid_existing = getattr(existing_role, 'global_role_id', None)
            if gid_existing is not None:
                target_by_global[gid_existing] = existing_role
    role_id_map: dict[int, ProductRole] = {}
    for old_role in source_product.roles:
        gid = old_role.global_role_id
        if gid is None:
            # 历史遗留行（迁移 045 回填 + NOT NULL 后不应再出现）：按名称补齐全局角色
            legacy_name = (old_role.role_name or '').strip()
            if not legacy_name:
                raise ValueError('源产品存在无名角色，无法复制')
            gid = (await ensure_global_role(db, legacy_name, username)).id
        reused = target_by_global.get(gid)
        if reused is not None:
            # 目标产品已关联同一全局角色 → 复用，避免撞 uq_product_role_product_global
            role_id_map[old_role.id] = reused
            continue
        new_role = ProductRole(
            product_id=target_product_id,
            global_role_id=gid,
            role_name=old_role.role_name,
        )
        db.add(new_role)
        target_by_global[gid] = new_role
        role_id_map[old_role.id] = new_role
    copied_count += len(role_id_map)
    if role_id_map:
        await db.flush()

    def _items_by_role(items):
        grouped: dict[int, list] = {}
        for item in items:
            if item.role_id is not None:
                grouped.setdefault(item.role_id, []).append(item)
        return grouped

    fabrics_by_role = _items_by_role(source_product.fabrics)
    accessories_by_role = _items_by_role(source_product.accessories)
    materials_by_role = _items_by_role(source_materials)

    for old_role in source_product.roles:
        new_role_id = role_id_map[old_role.id].id
        for old_fabric in fabrics_by_role.get(old_role.id, []):
            db.add(ProductFabric(
                product_id=target_product_id,
                role_id=new_role_id,
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
        for old_accessory in accessories_by_role.get(old_role.id, []):
            db.add(ProductAccessory(
                product_id=target_product_id,
                role_id=new_role_id,
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
        for old_material in materials_by_role.get(old_role.id, []):
            db.add(ProductMaterial(
                product_id=target_product_id,
                role_id=new_role_id,
                material_code=getattr(old_material, 'material_code', '') or '',
                cotton_usage=old_material.cotton_usage,
                specification=getattr(old_material, 'specification', '') or '',
                supplier_id=getattr(old_material, 'supplier_id', None),
                supplier_name=getattr(old_material, 'supplier_name', '') or '',
                unit=getattr(old_material, 'unit', '') or '克',
                remark=getattr(old_material, 'remark', '') or '',
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
            selectinload(Product.material_rows),
            selectinload(Product.fabrics),
            selectinload(Product.accessories),
            selectinload(Product.roles),
        ).where(Product.id == source_product_id)
    )
    source_product = result.scalar_one_or_none()
    if not source_product:
        raise ValueError(f'产品ID {source_product_id} 不存在')
    if not has_bom(source_product):
        raise ValueError('该产品没有配置BOM表，无法复制')

    # 源产品所有填充物（含各角色行）
    src_mat_result = await db.execute(
        select(ProductMaterial).where(ProductMaterial.product_id == source_product_id)
    )
    source_materials = src_mat_result.scalars().all()

    bom_data = {
        'filling': None,
        'fabric': [],
        'accessory': [],
        'roles': [],
    }

    if source_product.material and getattr(source_product.material, 'cotton_usage', Decimal('0')) > 0:
        bom_data['filling'] = source_product.material.to_dict()

    for fabric in source_product.fabrics:
        if fabric.role_id is not None:
            continue
        bom_data['fabric'].append(fabric.to_dict())
    for accessory in source_product.accessories:
        if accessory.role_id is not None:
            continue
        bom_data['accessory'].append(accessory.to_dict())

    for role in source_product.roles:
        bom_data['roles'].append({
            'id': role.id,
            'name': role.role_name,
            'filling_count': sum(1 for m in source_materials if m.role_id == role.id),
            'fabric_count': sum(1 for f in source_product.fabrics if f.role_id == role.id),
            'accessory_count': sum(1 for a in source_product.accessories if a.role_id == role.id),
        })

    material_count = (
        (1 if bom_data['filling'] else 0)
        + len(bom_data['fabric'])
        + len(bom_data['accessory'])
        + sum(r['filling_count'] + r['fabric_count'] + r['accessory_count'] for r in bom_data['roles'])
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
        'role_count': len(source_product.roles),
    }


async def search_for_bom_copy(db: AsyncSession, keyword: str, *, search_service=None) -> list:
    if search_service is None:
        from fastapi_app.core.container import get_product_search_service
        search_service = get_product_search_service()

    if not keyword:
        return []

    query = search_service.build_search_query_async(db, keyword)
    query = query.options(
        selectinload(Product.material),
        selectinload(Product.material_rows),
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
