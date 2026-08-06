"""板房模块服务层

职责：
- BOM CRUD（含树形结构整树提交、diff + apply）
- 版本快照（创建新版本时对当前节点做快照）
- 版本对比（按版本号聚合节点快照）
- 变更日志（自动生成字段级 diff）

约定：
- 服务层使用 flush() 而非 commit()，事务由 db_transaction 控制
- 编号通过 services/numbering.py 生成
- 所有写操作必须记录变更日志（包含操作人、原因、字段级 diff）
"""
from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from fastapi_app.core.exceptions import BusinessError, NotFoundError
from fastapi_app.services.numbering import generate_pattern_room_bom_number
from fastapi_app.shared_models import (
    PATTERN_ROOM_BOM_STATUSES,
    PATTERN_ROOM_CATEGORIES,
    PatternRoomBom,
    PatternRoomBomItem,
    PatternRoomBomItemVersion,
    PatternRoomChangeLog,
    User,
)

logger = logging.getLogger(__name__)


# ==================== 校验工具 ====================

def _validate_category(category: str) -> None:
    if category not in PATTERN_ROOM_CATEGORIES:
        raise BusinessError(f'物料类别无效，必须为 {list(PATTERN_ROOM_CATEGORIES.keys())} 之一')


def _validate_status(status: str) -> None:
    if status not in PATTERN_ROOM_BOM_STATUSES:
        raise BusinessError(f'BOM 状态无效，必须为 {list(PATTERN_ROOM_BOM_STATUSES.keys())} 之一')


def _next_version(current: str) -> str:
    """T1 -> T2, T2 -> T3, ..."""
    try:
        n = int(current.lstrip('Tt'))
        return f'T{n + 1}'
    except (ValueError, AttributeError):
        return 'T1'


# ==================== BOM 列表 ====================

async def list_boms(
    db: AsyncSession,
    *,
    page: int = 1,
    per_page: int = 20,
    keyword: str | None = None,
    status: str | None = None,
    current_version: str | None = None,
    customer_id: int | None = None,
) -> dict:
    """分页查询 BOM 列表"""
    conditions = []
    if keyword:
        like = f'%{keyword}%'
        conditions.append(
            (PatternRoomBom.product_name.ilike(like))
            | (PatternRoomBom.bom_no.ilike(like))
            | (PatternRoomBom.customer_name.ilike(like))
        )
    if status:
        _validate_status(status)
        conditions.append(PatternRoomBom.status == status)
    if current_version:
        conditions.append(PatternRoomBom.current_version == current_version)
    if customer_id:
        conditions.append(PatternRoomBom.customer_id == customer_id)

    base_query = select(PatternRoomBom).options(selectinload(PatternRoomBom.creator))
    for cond in conditions:
        base_query = base_query.where(cond)

    # 计算总数
    count_query = select(func.count()).select_from(PatternRoomBom)
    for cond in conditions:
        count_query = count_query.where(cond)
    total = (await db.execute(count_query)).scalar_one()

    # 分页
    pages = max(1, (total + per_page - 1) // per_page)
    page = max(1, min(page, pages))
    rows = (
        await db.execute(
            base_query.order_by(PatternRoomBom.created_at.desc())
            .offset((page - 1) * per_page)
            .limit(per_page)
        )
    ).scalars().all()

    return {
        'success': True,
        'items': [b.to_dict(include_items=False) for b in rows],
        'total': total,
        'pages': pages,
        'current_page': page,
    }


# ==================== BOM 详情 ====================

async def get_bom_detail(db: AsyncSession, bom_id: int, include_logs: bool = False) -> dict:
    """获取 BOM 详情（含完整树形结构 + 可选变更日志）。

    实现说明：
        自引用 ``children`` 关系的 ``lazy='selectin'`` 默认只加载 1 层，
        在 async 上下文中递归访问深层 ``children`` 会触发 ``MissingGreenlet``。
        因此这里**单独扁平加载所有节点（含 versions）**，在 Python 中按
        ``parent_id`` 分组构建树，再调用 ``to_dict(children=...)`` 避免
        任何 ORM 递归 lazy load。
    """
    bom = (
        await db.execute(
            select(PatternRoomBom)
            .options(
                selectinload(PatternRoomBom.creator),
                selectinload(PatternRoomBom.change_logs).selectinload(PatternRoomChangeLog.operator),
            )
            .where(PatternRoomBom.id == bom_id)
        )
    ).scalar_one_or_none()
    if not bom:
        raise NotFoundError(f'BOM {bom_id} 不存在')

    # 扁平加载所有节点 + 版本快照（一次性查询，避免 N+1）
    all_items = (
        await db.execute(
            select(PatternRoomBomItem)
            .options(selectinload(PatternRoomBomItem.versions))
            .where(PatternRoomBomItem.bom_id == bom_id)
            .order_by(PatternRoomBomItem.sort_order)
        )
    ).scalars().all()

    # 按 parent_id 分组（None 为根）
    items_by_parent: dict[int | None, list[PatternRoomBomItem]] = {}
    for item in all_items:
        items_by_parent.setdefault(item.parent_id, []).append(item)

    def _build_tree(parent_id: int | None) -> list[dict]:
        return [
            item.to_dict(include_versions=True, children=_build_tree(item.id))
            for item in items_by_parent.get(parent_id, [])
        ]

    result = bom.to_dict(include_items=False, include_logs=include_logs)
    result['items'] = _build_tree(None)
    return {'success': True, 'bom': result}


# ==================== 创建 BOM ====================

async def create_bom(
    db: AsyncSession,
    *,
    product_name: str,
    customer_id: int | None = None,
    customer_name: str = '',
    remark: str = '',
    items: list[dict] | None = None,
    operator: User,
) -> dict:
    """创建 BOM 主表 + 初始节点 + 写入 create 变更日志"""
    if not product_name or not product_name.strip():
        raise BusinessError('产品名称不能为空')

    bom_no = await generate_pattern_room_bom_number(db)

    bom = PatternRoomBom(
        bom_no=bom_no,
        product_name=product_name.strip(),
        customer_id=customer_id,
        customer_name=customer_name,
        remark=remark,
        current_version='T1',
        status='draft',
        created_by=operator.id,
    )
    db.add(bom)
    await db.flush()  # 获取 bom.id

    # 创建初始节点
    if items:
        _create_items_recursive(db, bom.id, None, items)

    # 写入创建日志
    log = PatternRoomChangeLog(
        bom_id=bom.id,
        change_type='create',
        from_version=None,
        to_version='T1',
        change_reason=f'创建 BOM：{product_name}',
        change_details=[
            {'field': 'product_name', 'old': None, 'new': product_name},
            {'field': 'customer_name', 'old': None, 'new': customer_name},
            {'field': 'current_version', 'old': None, 'new': 'T1'},
            {'field': 'status', 'old': None, 'new': 'draft'},
            {'field': 'items_count', 'old': 0, 'new': len(items or [])},
        ],
        operator_id=operator.id,
        operator_name=operator.username,
    )
    db.add(log)
    await db.flush()
    return {'id': bom.id, 'bom_no': bom_no}


def _create_items_recursive(
    db: AsyncSession,
    bom_id: int,
    parent_id: int | None,
    items: list[dict],
    sort_offset: int = 0,
) -> None:
    """递归创建节点（不刷新，由调用方控制）"""
    for idx, raw in enumerate(items):
        _validate_category(raw.get('category', ''))
        qty = float(raw.get('quantity') or 0)
        if qty <= 0:
            raise BusinessError(f'物料 "{raw.get("material_name", "")}" 用量必须大于 0')
        item = PatternRoomBomItem(
            bom_id=bom_id,
            parent_id=parent_id,
            sort_order=sort_offset + idx,
            material_name=raw['material_name'],
            category=raw['category'],
            quantity=qty,
            unit=raw.get('unit') or '个',
            spec=raw.get('spec') or '',
            current_supplier_id=raw.get('current_supplier_id'),
            current_supplier_name=raw.get('current_supplier_name') or '',
            current_version=raw.get('current_version') or 'T1',
            remark=raw.get('remark') or '',
        )
        db.add(item)
        # 同步创建 T1 版本快照
        if item.current_supplier_id or item.current_supplier_name:
            version_data = raw.get('versions') or []
            if not version_data:
                # 自动生成 T1 快照
                db.add(PatternRoomBomItemVersion(
                    bom_item_id=None,  # 需要 flush 后才能拿到 id
                    version='T1',
                    supplier_id=item.current_supplier_id,
                    supplier_name=item.current_supplier_name,
                    material_spec=item.spec,
                ))
        # 递归创建子节点（flush 在父级调用后进行）
        children = raw.get('children') or []
        if children:
            # 注意：由于未 flush，子节点的 parent_id 暂为 None，需要外层 flush 后回填
            # 简化处理：在 _save_items_full_replace 中处理
            pass


# ==================== 更新 BOM 元信息 ====================

async def update_bom(
    db: AsyncSession,
    bom_id: int,
    *,
    product_name: str | None = None,
    customer_id: int | None = None,
    customer_name: str | None = None,
    remark: str | None = None,
    status: str | None = None,
    operator: User,
) -> dict:
    """更新 BOM 元信息（不含节点）"""
    bom = await _load_bom(db, bom_id)
    if bom.status == 'archived':
        raise BusinessError('已归档的 BOM 不可编辑')

    changes: list[dict] = []
    if product_name is not None and product_name != bom.product_name:
        changes.append({'field': 'product_name', 'old': bom.product_name, 'new': product_name})
        bom.product_name = product_name
    if customer_id is not None and customer_id != bom.customer_id:
        changes.append({'field': 'customer_id', 'old': bom.customer_id, 'new': customer_id})
        bom.customer_id = customer_id
    if customer_name is not None and customer_name != bom.customer_name:
        changes.append({'field': 'customer_name', 'old': bom.customer_name, 'new': customer_name})
        bom.customer_name = customer_name
    if remark is not None and remark != (bom.remark or ''):
        changes.append({'field': 'remark', 'old': bom.remark or '', 'new': remark})
        bom.remark = remark
    if status is not None and status != bom.status:
        _validate_status(status)
        # 状态流转校验
        transitions = {
            'draft': {'sampling', 'archived'},
            'sampling': {'confirmed', 'draft', 'archived'},
            'confirmed': {'archived', 'sampling'},
            'archived': set(),
        }
        allowed = transitions.get(bom.status, set())
        if status not in allowed:
            raise BusinessError(f'状态不可从 {bom.status} 流转到 {status}')
        changes.append({'field': 'status', 'old': bom.status, 'new': status})
        bom.status = status

    if changes:
        bom.version += 1
        log = PatternRoomChangeLog(
            bom_id=bom.id,
            change_type='status_change' if any(c['field'] == 'status' for c in changes) else 'item_edit',
            from_version=bom.current_version,
            to_version=bom.current_version,
            change_reason=f'编辑 BOM 字段：{", ".join(c["field"] for c in changes)}',
            change_details=changes,
            operator_id=operator.id,
            operator_name=operator.username,
        )
        db.add(log)
    await db.flush()
    return {'id': bom.id, 'version': bom.version}


# ==================== 整树保存 BOM 节点 ====================

async def save_bom_items(
    db: AsyncSession,
    bom_id: int,
    *,
    items: list[dict],
    operator: User,
) -> dict:
    """
    整树保存 BOM 节点（替换式）：
    1. 加载旧节点
    2. 与新节点做 diff
    3. 删除旧节点 + 插入新节点（外键级联删除 versions）
    4. 写入变更日志
    """
    bom = await _load_bom(db, bom_id)
    if bom.status == 'archived':
        raise BusinessError('已归档的 BOM 不可编辑')

    # 加载旧节点（顶层 + 递归）
    old_root = (
        await db.execute(
            select(PatternRoomBomItem)
            .where(PatternRoomBomItem.bom_id == bom_id, PatternRoomBomItem.parent_id.is_(None))
            .order_by(PatternRoomBomItem.sort_order)
        )
    ).scalars().all()

    # 计算 diff（按物料名称 + 类别匹配，简单策略）
    old_map = {(i.material_name, i.category): i for i in old_root}
    new_map = {(i.get('material_name', ''), i.get('category', '')): i for i in items}
    diff_details: list[dict] = []

    for key, new_item in new_map.items():
        if key not in old_map:
            diff_details.append({
                'field': 'item_added',
                'old': None,
                'new': {'material_name': new_item.get('material_name'), 'category': new_item.get('category')},
            })
        else:
            old_item = old_map[key]
            for field in ('quantity', 'unit', 'spec', 'current_supplier_name', 'current_version', 'remark'):
                old_v = getattr(old_item, field, None)
                new_v = new_item.get(field)
                if field == 'quantity':
                    old_v = float(old_v or 0)
                    new_v = float(new_v or 0)
                if new_v is not None and str(old_v) != str(new_v):
                    diff_details.append({
                        'field': f'{field} ({new_item.get("material_name")})',
                        'old': old_v,
                        'new': new_v,
                    })

    for key, old_item in old_map.items():
        if key not in new_map:
            diff_details.append({
                'field': 'item_removed',
                'old': {'material_name': old_item.material_name, 'category': old_item.category},
                'new': None,
            })

    # 删除旧节点（级联删除 versions 和 children）
    await db.execute(
        delete(PatternRoomBomItem).where(
            PatternRoomBomItem.bom_id == bom_id,
            PatternRoomBomItem.parent_id.is_(None),
        )
    )
    await db.flush()

    # 插入新节点
    _save_items_full_replace(db, bom_id, None, items, 0)
    bom.version += 1

    # 写日志（仅在 diff 非空时）
    if diff_details:
        log = PatternRoomChangeLog(
            bom_id=bom.id,
            change_type='item_edit',
            from_version=bom.current_version,
            to_version=bom.current_version,
            change_reason=f'编辑 BOM 节点（共 {len(diff_details)} 项变更）',
            change_details=diff_details,
            operator_id=operator.id,
            operator_name=operator.username,
        )
        db.add(log)

    await db.flush()
    return {'id': bom.id, 'version': bom.version, 'changes': len(diff_details)}


def _save_items_full_replace(
    db: AsyncSession,
    bom_id: int,
    parent_id: int | None,
    items: list[dict],
    sort_offset: int,
) -> None:
    """递归插入整棵子树（替换式，已清理旧数据）"""
    for idx, raw in enumerate(items):
        _validate_category(raw.get('category', ''))
        qty = float(raw.get('quantity') or 0)
        if qty <= 0:
            raise BusinessError(f'物料 "{raw.get("material_name", "")}" 用量必须大于 0')

        item = PatternRoomBomItem(
            bom_id=bom_id,
            parent_id=parent_id,
            sort_order=sort_offset + idx,
            material_name=raw['material_name'],
            category=raw['category'],
            quantity=qty,
            unit=raw.get('unit') or '个',
            spec=raw.get('spec') or '',
            current_supplier_id=raw.get('current_supplier_id'),
            current_supplier_name=raw.get('current_supplier_name') or '',
            current_version=raw.get('current_version') or 'T1',
            remark=raw.get('remark') or '',
        )
        db.add(item)
        db.flush()  # 获取 item.id

        # 创建版本快照（与节点 current_version 一致）
        versions_data = raw.get('versions') or []
        if not versions_data and (item.current_supplier_id or item.current_supplier_name):
            versions_data = [{
                'version': item.current_version,
                'supplier_id': item.current_supplier_id,
                'supplier_name': item.current_supplier_name,
                'material_spec': item.spec,
            }]
        for v in versions_data:
            db.add(PatternRoomBomItemVersion(
                bom_item_id=item.id,
                version=v.get('version') or item.current_version,
                supplier_id=v.get('supplier_id'),
                supplier_name=v.get('supplier_name') or '',
                material_spec=v.get('material_spec') or '',
                unit_price=v.get('unit_price'),
                contact_person=v.get('contact_person') or '',
                contact_phone=v.get('contact_phone') or '',
                delivery_days=v.get('delivery_days'),
                remark=v.get('remark') or '',
            ))

        # 递归子节点
        children = raw.get('children') or []
        if children:
            _save_items_full_replace(db, bom_id, item.id, children, 0)


# ==================== 删除 BOM ====================

async def delete_bom(db: AsyncSession, bom_id: int) -> dict:
    """删除 BOM（级联删除节点、版本、日志）"""
    bom = await _load_bom(db, bom_id)
    await db.delete(bom)
    await db.flush()
    return {'id': bom_id}


# ==================== 复制 BOM ====================

async def copy_bom(
    db: AsyncSession,
    source_bom_id: int,
    *,
    product_name: str | None = None,
    operator: User,
) -> dict:
    """复制 BOM（含节点 + 版本快照，新编号、状态为 draft、版本为 T1）。

    实现说明：与 get_bom_detail 一致，单独扁平加载所有源节点 + versions，
    在 Python 中按 parent_id 分组后递归复制，避免自引用 children 的 lazy load。
    """
    src = (
        await db.execute(
            select(PatternRoomBom).where(PatternRoomBom.id == source_bom_id)
        )
    ).scalar_one_or_none()
    if not src:
        raise NotFoundError(f'BOM {source_bom_id} 不存在')

    # 扁平加载所有源节点 + 版本快照
    src_items = (
        await db.execute(
            select(PatternRoomBomItem)
            .options(selectinload(PatternRoomBomItem.versions))
            .where(PatternRoomBomItem.bom_id == source_bom_id)
            .order_by(PatternRoomBomItem.sort_order)
        )
    ).scalars().all()

    src_by_parent: dict[int | None, list[PatternRoomBomItem]] = {}
    for it in src_items:
        src_by_parent.setdefault(it.parent_id, []).append(it)

    new_bom_no = await generate_pattern_room_bom_number(db)
    new_bom = PatternRoomBom(
        bom_no=new_bom_no,
        product_name=product_name or f'{src.product_name}（副本）',
        customer_id=src.customer_id,
        customer_name=src.customer_name,
        current_version='T1',
        status='draft',
        remark=src.remark,
        created_by=operator.id,
    )
    db.add(new_bom)
    await db.flush()

    # 递归复制节点（用扁平 map 而非 ORM children 关系）
    def _copy_subtree(new_parent_id: int | None, src_parent_id: int | None) -> None:
        for src_item in src_by_parent.get(src_parent_id, []):
            new_item = PatternRoomBomItem(
                bom_id=new_bom.id,
                parent_id=new_parent_id,
                sort_order=src_item.sort_order,
                material_name=src_item.material_name,
                category=src_item.category,
                quantity=src_item.quantity,
                unit=src_item.unit,
                spec=src_item.spec,
                current_supplier_id=src_item.current_supplier_id,
                current_supplier_name=src_item.current_supplier_name,
                current_version='T1',
                remark=src_item.remark,
            )
            db.add(new_item)
            db.flush()

            # 复制版本快照（versions 已 selectinload，访问安全）
            for v in (src_item.versions or []):
                db.add(PatternRoomBomItemVersion(
                    bom_item_id=new_item.id,
                    version=v.version,
                    supplier_id=v.supplier_id,
                    supplier_name=v.supplier_name,
                    material_spec=v.material_spec,
                    unit_price=v.unit_price,
                    contact_person=v.contact_person,
                    contact_phone=v.contact_phone,
                    delivery_days=v.delivery_days,
                    remark=v.remark,
                ))

            _copy_subtree(new_item.id, src_item.id)

    _copy_subtree(None, None)

    log = PatternRoomChangeLog(
        bom_id=new_bom.id,
        change_type='create',
        from_version=None,
        to_version='T1',
        change_reason=f'从 BOM {src.bom_no} 复制创建',
        change_details=[{'field': 'source_bom_no', 'old': None, 'new': src.bom_no}],
        operator_id=operator.id,
        operator_name=operator.username,
    )
    db.add(log)
    await db.flush()
    return {'id': new_bom.id, 'bom_no': new_bom_no}


# ==================== 创建新版本 ====================

async def create_version(
    db: AsyncSession,
    bom_id: int,
    *,
    reason: str,
    operator: User,
) -> dict:
    """
    创建新版本：
    1. 对当前所有节点的当前数据做快照（写入 pattern_room_bom_item_version）
    2. 更新 BOM.current_version
    3. 写入版本升级变更日志
    """
    if not reason or len(reason.strip()) < 10:
        raise BusinessError('变更原因 必须 ≥ 10 字符')

    bom = await _load_bom(db, bom_id, for_update=True)
    if bom.status == 'archived':
        raise BusinessError('已归档的 BOM 不可创建新版本')

    old_version = bom.current_version
    new_version = _next_version(old_version)

    # 加载所有节点
    items = (
        await db.execute(
            select(PatternRoomBomItem)
            .options(selectinload(PatternRoomBomItem.versions))
            .where(PatternRoomBomItem.bom_id == bom_id)
        )
    ).scalars().all()

    snapshot_count = 0
    for item in items:
        # 检查是否已存在该版本的快照
        existing = [v for v in (item.versions or []) if v.version == new_version]
        if existing:
            continue
        db.add(PatternRoomBomItemVersion(
            bom_item_id=item.id,
            version=new_version,
            supplier_id=item.current_supplier_id,
            supplier_name=item.current_supplier_name,
            material_spec=item.spec,
        ))
        snapshot_count += 1

    bom.current_version = new_version
    bom.version += 1

    log = PatternRoomChangeLog(
        bom_id=bom.id,
        change_type='version_upgrade',
        from_version=old_version,
        to_version=new_version,
        change_reason=reason.strip(),
        change_details=[
            {'field': 'current_version', 'old': old_version, 'new': new_version},
            {'field': 'snapshot_count', 'old': 0, 'new': snapshot_count},
        ],
        operator_id=operator.id,
        operator_name=operator.username,
    )
    db.add(log)
    await db.flush()
    return {'from_version': old_version, 'to_version': new_version, 'snapshot_count': snapshot_count}


# ==================== 版本列表 ====================

async def list_versions(db: AsyncSession, bom_id: int) -> dict:
    """获取 BOM 的所有版本号"""
    bom = await _load_bom(db, bom_id)
    rows = (
        await db.execute(
            select(PatternRoomBomItemVersion.version)
            .join(PatternRoomBomItem, PatternRoomBomItem.id == PatternRoomBomItemVersion.bom_item_id)
            .where(PatternRoomBomItem.bom_id == bom_id)
            .distinct()
            .order_by(PatternRoomBomItemVersion.version)
        )
    ).scalars().all()
    versions = sorted(set(list(rows) + [bom.current_version]), key=lambda x: int(x.lstrip('Tt')))
    return {'success': True, 'versions': versions}


# ==================== 版本对比 ====================

async def compare_versions(
    db: AsyncSession,
    bom_id: int,
    *,
    from_version: str,
    to_version: str,
) -> dict:
    """对比两个版本：返回 BOM 当前快照 + 差异列表"""
    bom = await _load_bom(db, bom_id)
    items = (
        await db.execute(
            select(PatternRoomBomItem)
            .options(selectinload(PatternRoomBomItem.versions))
            .where(PatternRoomBomItem.bom_id == bom_id)
            .order_by(PatternRoomBomItem.sort_order)
        )
    ).scalars().all()

    differences: list[dict] = []
    for item in items:
        v_from = next((v for v in (item.versions or []) if v.version == from_version), None)
        v_to = next((v for v in (item.versions or []) if v.version == to_version), None)

        # 如果都没有快照，跳过
        if not v_from and not v_to:
            continue

        item_diff: list[dict] = []
        for field in ('supplier_name', 'material_spec', 'unit_price', 'contact_person', 'contact_phone', 'delivery_days'):
            old_v = getattr(v_from, field, None) if v_from else None
            new_v = getattr(v_to, field, None) if v_to else None
            if str(old_v) != str(new_v):
                item_diff.append({'field': field, 'old': old_v, 'new': new_v})

        if item_diff:
            differences.append({
                'bom_item_id': item.id,
                'material_name': item.material_name,
                'category': item.category,
                'quantity': float(item.quantity or 0),
                'unit': item.unit,
                'from_supplier': v_from.supplier_name if v_from else '',
                'to_supplier': v_to.supplier_name if v_to else '',
                'diff': item_diff,
            })

    return {
        'success': True,
        'from_version': from_version,
        'to_version': to_version,
        'bom': bom.to_dict(include_items=False),
        'differences': differences,
    }


# ==================== 变更日志 ====================

async def list_change_logs(
    db: AsyncSession,
    bom_id: int,
    *,
    change_type: str | None = None,
    page: int = 1,
    per_page: int = 50,
) -> dict:
    """获取 BOM 的变更日志（分页 + 按时间倒序）"""
    bom = await _load_bom(db, bom_id)
    conditions = [PatternRoomChangeLog.bom_id == bom.id]
    if change_type:
        conditions.append(PatternRoomChangeLog.change_type == change_type)

    count_query = select(func.count()).select_from(PatternRoomChangeLog).where(*conditions)
    total = (await db.execute(count_query)).scalar_one()

    pages = max(1, (total + per_page - 1) // per_page)
    page = max(1, min(page, pages))

    query = (
        select(PatternRoomChangeLog)
        .options(selectinload(PatternRoomChangeLog.operator))
        .where(*conditions)
        .order_by(PatternRoomChangeLog.created_at.desc())
        .offset((page - 1) * per_page)
        .limit(per_page)
    )
    rows = (await db.execute(query)).scalars().all()

    return {
        'success': True,
        'items': [log.to_dict() for log in rows],
        'total': total,
        'pages': pages,
        'current_page': page,
    }


async def get_change_log_detail(db: AsyncSession, log_id: int) -> dict:
    """获取单条变更日志详情"""
    log = (
        await db.execute(
            select(PatternRoomChangeLog)
            .options(selectinload(PatternRoomChangeLog.operator))
            .where(PatternRoomChangeLog.id == log_id)
        )
    ).scalar_one_or_none()
    if not log:
        raise NotFoundError(f'变更日志 {log_id} 不存在')
    return {'success': True, 'log': log.to_dict()}


# ==================== 工具 ====================

async def _load_bom(db: AsyncSession, bom_id: int, for_update: bool = False) -> PatternRoomBom:
    """加载 BOM（轻量，仅主表 + creator）"""
    stmt = select(PatternRoomBom).options(selectinload(PatternRoomBom.creator)).where(PatternRoomBom.id == bom_id)
    if for_update:
        stmt = stmt.with_for_update()
    bom = (await db.execute(stmt)).scalar_one_or_none()
    if not bom:
        raise NotFoundError(f'BOM {bom_id} 不存在')
    return bom
