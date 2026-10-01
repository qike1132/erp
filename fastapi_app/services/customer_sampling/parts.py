"""打样部位 CRUD 与版本复制（创建/更新/删除/批量创建/列表/复制版本）

自 crud.py 拆分（批次2-3），函数原文零改动。"""
# ruff: noqa: F401 - 拆分过渡期沿用完整导入块
from __future__ import annotations

import logging
from datetime import UTC, datetime

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import noload, selectinload

from fastapi_app.core.exceptions import BusinessError, ConflictError, NotFoundError
from fastapi_app.shared_models import (
    CustomerSamplingChangeLog,
    CustomerSamplingFabricVersion,
    CustomerSamplingPart,
    CustomerSamplingProject,
    CustomerSamplingRole,
    Supplier,
)

logger = logging.getLogger(__name__)

from .common import (
    _ensure_part_name_unique,
    _ensure_project_exists,
    _ensure_role_belongs_to_project,
    _get_primary_role_id,
    _get_user_name,
    _resolve_pattern_maker_name,
    _resolve_role_id,
    _resolve_supplier_name,
    _write_change_log,
)
from .grouping import _project_to_summary
from .upload import _batch_get_image_urls, _get_product_image_urls
from .version_diff import _version_num


async def create_part(
    db: AsyncSession,
    project_id: int,
    *,
    part_name: str,
    sort_order: int = 0,
    fabric_name: str | None = None,
    fabric_spec: str | None = None,
    fabric_color_no: str | None = None,
    supplier_id: int | None = None,
    contact_person: str | None = None,
    contact_phone: str | None = None,
    unit_price: float | None = None,
    delivery_days: int | None = None,
    remark: str | None = None,
    role_id: int | None = None,
    user_id: int | None = None,
) -> dict:
    """新增部位

    - 校验项目存在
    - 校验 part_name 同项目下唯一（应用层校验 + DB 唯一索引双重保障）
    - 校验 supplier_id 存在性，冗余存储 supplier_name
    - role_id 指定归属角色（校验属于该项目），未传时归属项目的基准角色
    """
    await _ensure_project_exists(db, project_id)
    role_id = await _resolve_role_id(db, project_id, role_id)

    # 校验部位名称同角色、同版本下唯一；角色已在上方解析，避免重复查询
    await _ensure_part_name_unique(db, project_id, part_name, role_id=role_id)

    # 解析供应商名称
    supplier_name = ''
    if supplier_id is not None:
        supplier_name = await _resolve_supplier_name(db, supplier_id)
        if not supplier_name:
            raise NotFoundError('所选供应商不存在')

    part = CustomerSamplingPart(
        project_id=project_id,
        role_id=role_id,
        part_name=part_name,
        sort_order=sort_order,
        fabric_name=fabric_name,
        fabric_spec=fabric_spec,
        fabric_color_no=fabric_color_no,
        supplier_id=supplier_id,
        supplier_name=supplier_name,
        contact_person=contact_person,
        contact_phone=contact_phone,
        unit_price=unit_price,
        delivery_days=delivery_days,
        remark=remark,
    )
    db.add(part)
    await db.flush()

    # 写审计日志
    operator_name = await _get_user_name(db, user_id)
    await _write_change_log(
        db, project_id, 'create_part', user_id, operator_name,
        part_name=part_name,
    )

    logger.info('新增部位: project_id=%s, part_id=%s, part_name=%s', project_id, part.id, part_name)
    return {'id': part.id}

async def update_part(
    db: AsyncSession,
    part_id: int,
    *,
    part_name: str | None = None,
    sort_order: int | None = None,
    fabric_name: str | None = None,
    fabric_spec: str | None = None,
    fabric_color_no: str | None = None,
    supplier_id: int | None = None,
    supplier_name: str | None = None,
    contact_person: str | None = None,
    contact_phone: str | None = None,
    unit_price: float | None = None,
    delivery_days: int | None = None,
    remark: str | None = None,
    version: int,
    user_id: int | None = None,
) -> dict:
    """编辑部位布料

    - 乐观锁校验（SELECT ... FOR UPDATE 行锁，防止并发更新丢失）
    - 校验 part_name 同项目下唯一（排除自身）
    - 修改在当前版本生效，历史版本快照不变
    - 返回更新后的乐观锁版本号，供前端局部回写
    """
    result = await db.execute(
        select(CustomerSamplingPart)
        .where(CustomerSamplingPart.id == part_id)
        .with_for_update()
    )
    part = result.scalar_one_or_none()
    if part is None:
        raise NotFoundError('部位不存在')

    # 乐观锁校验
    if part.version != version:
        raise ConflictError('该部位已被他人更新，请刷新后重试')

    # 校验部位名称同角色同版本下唯一（排除自身）
    if part_name is not None and part_name != part.part_name:
        await _ensure_part_name_unique(
            db, part.project_id, part_name,
            role_id=part.role_id, exclude_id=part_id,
        )
        part.part_name = part_name

    # 解析供应商
    if supplier_id is not None and supplier_id != part.supplier_id:
        resolved_name = ''
        if supplier_id is not None:
            resolved_name = await _resolve_supplier_name(db, supplier_id)
            if not resolved_name:
                raise NotFoundError('所选供应商不存在')
        part.supplier_id = supplier_id
        part.supplier_name = resolved_name
    elif supplier_name is not None and supplier_name != part.supplier_name:
        # 允许直接更新供应商名称（不通过 supplier_id）
        part.supplier_name = supplier_name

    # 更新可选字段
    if sort_order is not None:
        part.sort_order = sort_order
    if fabric_name is not None:
        part.fabric_name = fabric_name
    if fabric_spec is not None:
        part.fabric_spec = fabric_spec
    if fabric_color_no is not None:
        part.fabric_color_no = fabric_color_no
    if contact_person is not None:
        part.contact_person = contact_person
    if contact_phone is not None:
        part.contact_phone = contact_phone
    if unit_price is not None:
        part.unit_price = unit_price
    if delivery_days is not None:
        part.delivery_days = delivery_days
    if remark is not None:
        part.remark = remark

    # 乐观锁 +1
    part.version += 1
    await db.flush()

    # 写审计日志
    operator_name = await _get_user_name(db, user_id)
    await _write_change_log(
        db, part.project_id, 'update_part', user_id, operator_name,
        part_name=part.part_name,
    )

    logger.info('编辑部位: part_id=%s, part_name=%s', part_id, part.part_name)
    return {'id': part.id, 'version': part.version}

async def delete_part(
    db: AsyncSession,
    part_id: int,
    *,
    user_id: int | None = None,
) -> dict:
    """删除部位

    - 历史版本快照中该部位数据保留（快照不可变，spec 5.5.1.6）
    - 允许删除任意版本（含角色当前最终版本）：
      快照不可变，diff 基于快照计算；
      最终版本删除的强确认提示由前端 onDeleteVersion 承担，后端不做硬性拦截。
    """
    result = await db.execute(
        select(CustomerSamplingPart).where(CustomerSamplingPart.id == part_id)
    )
    part = result.scalar_one_or_none()
    if part is None:
        raise NotFoundError('部位不存在')

    project_id = part.project_id
    part_name = part.part_name

    await db.delete(part)
    await db.flush()

    # 写审计日志
    operator_name = await _get_user_name(db, user_id)
    await _write_change_log(
        db, project_id, 'delete_part', user_id, operator_name,
        part_name=part_name,
    )

    logger.info('删除部位: part_id=%s, part_name=%s', part_id, part_name)
    return {'id': part_id}

async def batch_create_parts(
    db: AsyncSession,
    project_id: int,
    *,
    items: list[dict],
    role_id: int | None = None,
    user_id: int | None = None,
) -> dict:
    """批量新增部位

    一次事务中创建多条部位记录。
    每项 item 包含: part_name (必填), version_no (默认 T1),
    supplier_id / fabric_name / fabric_color_no (可选)

    批量优化：供应商名称与既有部位名各一次 IN 查询预取，
    部位与审计日志 add_all 后统一 flush（原先每条 3+ 次往返，50 条 150+ 次）。

    Args:
        role_id: 归属角色ID；未传时自动解析项目的基准角色
    """
    await _ensure_project_exists(db, project_id)
    role_id = await _resolve_role_id(db, project_id, role_id)

    # 供应商名称批量预取（一次 IN 查询）
    supplier_ids: set[int] = {sid for item in items if (sid := item.get('supplier_id')) is not None}
    supplier_name_map: dict[int, str] = {}
    if supplier_ids:
        rows = (await db.execute(
            select(Supplier.id, Supplier.name).where(Supplier.id.in_(supplier_ids))
        )).all()
        supplier_name_map = {row[0]: row[1] for row in rows}
        missing = supplier_ids - set(supplier_name_map)
        if missing:
            raise NotFoundError(f'供应商 {sorted(missing)[0]} 不存在')

    # 既有部位名批量预取（一次查询，覆盖该角色全部版本）
    existing_rows = (await db.execute(
        select(CustomerSamplingPart.part_name, CustomerSamplingPart.version_no).where(
            CustomerSamplingPart.project_id == project_id,
            CustomerSamplingPart.role_id == role_id,
        )
    )).all()
    existing_keys = {(name, vno) for name, vno in existing_rows}

    # 应用层校验：与库内既有 + 批次内部均不可重名（同角色同版本）
    batch_keys: set[tuple[str, str]] = set()
    for item in items:
        key = (item['part_name'], item.get('version_no', 'T1'))
        if key in existing_keys or key in batch_keys:
            raise BusinessError(f'部位名称 "{item["part_name"]}" 在当前版本中已存在')
        batch_keys.add(key)

    operator_name = await _get_user_name(db, user_id)

    parts_to_create = []
    logs_to_create = []
    for item in items:
        part_name = item['part_name']
        version_no = item.get('version_no', 'T1')
        supplier_id = item.get('supplier_id')
        supplier_name = (
            supplier_name_map.get(supplier_id, '')
            if supplier_id is not None
            else (item.get('supplier_name') or '')
        )
        parts_to_create.append(CustomerSamplingPart(
            project_id=project_id,
            role_id=role_id,
            version_no=version_no,
            part_name=part_name,
            sort_order=0,
            fabric_name=item.get('fabric_name'),
            fabric_color_no=item.get('fabric_color_no'),
            supplier_id=supplier_id,
            supplier_name=supplier_name,
        ))
        logs_to_create.append(CustomerSamplingChangeLog(
            project_id=project_id,
            action='create_part',
            part_name=part_name,
            operator_id=user_id,
            operator_name=operator_name,
        ))

    db.add_all(parts_to_create)
    db.add_all(logs_to_create)
    await db.flush()

    created_ids = [p.id for p in parts_to_create]
    logger.info(
        '批量新增部位: project_id=%s, role_id=%s, count=%d, ids=%s',
        project_id, role_id, len(created_ids), created_ids,
    )
    return {'ids': created_ids, 'count': len(created_ids)}

async def list_parts(db: AsyncSession, project_id: int, *, role_id: int | None = None) -> dict:
    """部位列表查询（按 sort_order 升序，含布料信息）

    Args:
        role_id: 角色ID筛选；未传时自动解析项目的默认角色
    （读路径：默认角色缺失时返回空列表，不在只读会话上隐式创建）
    """
    await _ensure_project_exists(db, project_id)
    if role_id is None:
        role_id = await _get_primary_role_id(db, project_id)
        if role_id is None:
            return {'success': True, 'items': []}

    result = await db.execute(
        select(CustomerSamplingPart)
        .options(selectinload(CustomerSamplingPart.supplier))
        .where(
            CustomerSamplingPart.project_id == project_id,
            CustomerSamplingPart.role_id == role_id,
        )
        .order_by(CustomerSamplingPart.sort_order)
    )
    parts = result.scalars().all()
    return {
        'success': True,
        'items': [p.to_dict() for p in parts],
    }

async def copy_part_version(
    db: AsyncSession,
    part_id: int,
    *,
    user_id: int | None = None,
) -> dict:
    """复制部位版本 — 在该部位名称下新增一个版本号 +1 的空白记录

    流程：
    1. 加载原部位记录（FOR UPDATE 行锁）
    2. 锁定所属角色行，串行化同角色并发的版本复制/创建（防止版本号冲突）
    3. 计算下一版本号（如 T1 → T2, T2 → T3）
    4. 创建新部位行：相同 part_name、空布料信息、新 version_no
    5. 写审计日志
    """
    # 加载原部位（行锁，防同部位并发复制）
    result = await db.execute(
        select(CustomerSamplingPart)
        .where(CustomerSamplingPart.id == part_id)
        .with_for_update()
    )
    part = result.scalar_one_or_none()
    if part is None:
        raise NotFoundError('部位不存在')

    # 锁定角色行（串行化同角色并发的版本号推算，防止版本号冲突）
    role_lock = await db.execute(
        select(CustomerSamplingRole.id)
        .where(CustomerSamplingRole.id == part.role_id)
        .with_for_update()
    )
    if role_lock.scalar_one_or_none() is None:
        raise NotFoundError('角色不存在')

    # 计算下一版本号：以该角色下同部位名称所有行的最大版本号为准
    ver_rows = (await db.execute(
        select(CustomerSamplingPart.version_no).where(
            CustomerSamplingPart.project_id == part.project_id,
            CustomerSamplingPart.role_id == part.role_id,
            CustomerSamplingPart.part_name == part.part_name,
        )
    )).all()
    max_no = max((_version_num(v) for (v,) in ver_rows), default=0)
    current_ver = part.version_no or 'T1'
    new_version_no = f'T{max(max_no, _version_num(current_ver)) + 1}'

    # 确保新版本号下同名称不重复（防御性检查）
    await _ensure_part_name_unique(
        db, part.project_id, part.part_name,
        role_id=part.role_id, version_no=new_version_no,
    )

    # 创建新版本行：保留 part_name，清空布料信息
    new_part = CustomerSamplingPart(
        project_id=part.project_id,
        role_id=part.role_id,
        version_no=new_version_no,
        part_name=part.part_name,
        sort_order=part.sort_order,
        fabric_name=None,
        fabric_color_no=None,
        supplier_id=None,
        supplier_name='',
    )
    db.add(new_part)
    await db.flush()

    # 写审计日志
    operator_name = await _get_user_name(db, user_id)
    await _write_change_log(
        db, part.project_id, 'copy_part_version', user_id, operator_name,
        part_name=part.part_name,
        target_version=new_version_no,
    )

    logger.info(
        '复制部位版本: part_id=%s → %s, part_name=%s, version %s → %s',
        part_id, new_part.id, part.part_name, current_ver, new_version_no,
    )
    return {'id': new_part.id, 'version_no': new_version_no}
