"""customer_sampling 子包 - 按客户分类打样信息模块

职责拆分（由 customer_sampling_service.py 1619 行上帝服务拆分而来）：
- grouping: 按客户分组聚合查询
- crud: 打样项目与部位 CRUD
- version_diff: 版本创建与字段级 diff
- upload: 产品图片上传
- roles: 角色管理
- common: 公共工具函数

对应需求规格：.codeartsdoer/specs/customer_sampling/spec.md
"""
from __future__ import annotations

import logging
from datetime import UTC, datetime

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import noload, selectinload

from fastapi_app.core.exceptions import BusinessError, ConflictError, NotFoundError
from fastapi_app.services.numbering import generate_customer_sampling_number
from fastapi_app.shared_models import (
    CustomerSamplingFabricVersion,
    CustomerSamplingPart,
    CustomerSamplingProject,
    CustomerSamplingRole,
)

logger = logging.getLogger(__name__)

# 版本快照中参与 diff 计算的布料业务字段
_SNAPSHOT_FIELDS = (
    'part_name', 'sort_order', 'fabric_name', 'fabric_spec',
    'supplier_id', 'supplier_name', 'contact_person', 'contact_phone',
    'unit_price', 'delivery_days', 'remark',
)

from .common import (
    _ensure_part_name_unique,
    _ensure_project_exists,
    _ensure_role_belongs_to_project,
    _get_default_role_id,
    _get_user_name,
    _resolve_pattern_maker_name,
    _resolve_supplier_name,
    _write_change_log,
)
from .grouping import _project_to_summary
from .upload import _batch_get_image_urls, _get_product_image_urls
from .version_diff import _version_num


async def create_project(
    db: AsyncSession,
    *,
    product_name: str,
    pattern_maker_id: int | None = None,
    remark: str | None = None,
    initial_roles: list[str] | None = None,
    user_id: int | None = None,
) -> dict:
    """新增打样项目

    - 自动生成序列号 CS-YYYYMMDD-XXXX
    - 自动创建"默认角色"（is_default=true）
    - 若传入 initial_roles，额外创建用户指定的角色（去重、去空白）
    - 自动创建 T1 基线版本挂在默认角色下（snapshot_data=[], change_summary=null）
    - 校验 pattern_maker_id 存在性，冗余存储 pattern_maker_name
    """
    # 校验版师存在性
    pattern_maker_name = ''
    if pattern_maker_id is not None:
        pattern_maker_name = await _resolve_pattern_maker_name(db, pattern_maker_id)
        if not pattern_maker_name:
            raise NotFoundError('所选版师不存在')

    # 生成序列号
    sequence_no = await generate_customer_sampling_number(db)

    # 创建项目
    project = CustomerSamplingProject(
        sequence_no=sequence_no,
        product_name=product_name,
        pattern_maker_id=pattern_maker_id,
        pattern_maker_name=pattern_maker_name,
        remark=remark,
        created_by=user_id,
    )
    db.add(project)
    await db.flush()

    # 创建默认角色（永远兜底，不可删除）
    default_role = CustomerSamplingRole(
        project_id=project.id,
        role_name='默认',
        sort_order=0,
        is_default=True,
        current_version='T1',
    )
    db.add(default_role)
    await db.flush()

    # 创建用户指定的额外角色（去重、去空白、不与"默认角色"重名）
    extra_role_names: list[str] = []
    seen = {'默认角色'}
    if initial_roles:
        for name in initial_roles:
            n = (name or '').strip()
            if n and n not in seen:
                seen.add(n)
                extra_role_names.append(n)

    for idx, role_name in enumerate(extra_role_names, start=1):
        role = CustomerSamplingRole(
            project_id=project.id,
            role_name=role_name,
            sort_order=idx,
            is_default=False,
            current_version='T1',
        )
        db.add(role)
        await db.flush()

    # 自动创建 T1 基线版本挂在默认角色下（快照初始为空数组）
    t1_version = CustomerSamplingFabricVersion(
        project_id=project.id,
        role_id=default_role.id,
        version_no='T1',
        snapshot_data=[],
        change_summary=None,
        reason='T1 基线版本（自动创建）',
        created_by=user_id,
    )
    db.add(t1_version)
    await db.flush()

    # 写审计日志
    operator_name = await _get_user_name(db, user_id)
    await _write_change_log(
        db, project.id, 'create_project', user_id, operator_name,
        target_version='T1',
    )

    logger.info(
        '创建打样项目: id=%s, sequence_no=%s, roles_count=%d',
        project.id, sequence_no, 1 + len(extra_role_names),
    )
    return {'id': project.id, 'sequence_no': sequence_no}



async def copy_part_version(
    db: AsyncSession,
    part_id: int,
    *,
    user_id: int | None = None,
) -> dict:
    """复制部位版本 — 在该部位名称下新增一个版本号 +1 的空白记录

    流程：
    1. 加载原部位记录
    2. 计算下一版本号（如 T1 → T2, T2 → T3）
    3. 创建新部位行：相同 part_name、空布料信息、新 version_no
    4. 写审计日志
    """
    # 加载原部位
    result = await db.execute(
        select(CustomerSamplingPart).where(CustomerSamplingPart.id == part_id)
    )
    part = result.scalar_one_or_none()
    if part is None:
        raise NotFoundError('部位不存在')

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



async def update_project(
    db: AsyncSession,
    project_id: int,
    *,
    product_name: str | None = None,
    pattern_maker_id: int | None = None,
    remark: str | None = None,
    product_image_file_id: int | None = None,
    current_version: str | None = None,
    version: int,
    user_id: int | None = None,
) -> dict:
    """编辑打样项目

    - 乐观锁校验（version 不匹配抛 ConflictError 409）
    - 可修改：product_name、pattern_maker_id、pattern_maker_name、remark、product_image_file_id
    - 序列号与历史版本快照不可修改
    """
    result = await db.execute(
        select(CustomerSamplingProject).where(CustomerSamplingProject.id == project_id)
    )
    project = result.scalar_one_or_none()
    if project is None:
        raise NotFoundError('打样项目不存在')

    # 乐观锁校验
    if project.version != version:
        raise ConflictError('该打样项目已被他人更新，请刷新后重试')

    # 收集字段变更用于审计
    field_diffs = []

    if product_name is not None and product_name != project.product_name:
        field_diffs.append({'field': 'product_name', 'old': project.product_name, 'new': product_name})
        project.product_name = product_name

    if pattern_maker_id is not None and pattern_maker_id != project.pattern_maker_id:
        # 校验新版师存在性
        new_pattern_maker_name = await _resolve_pattern_maker_name(db, pattern_maker_id)
        if not new_pattern_maker_name:
            raise NotFoundError('所选版师不存在')
        field_diffs.append({'field': 'pattern_maker_id', 'old': project.pattern_maker_id, 'new': pattern_maker_id})
        field_diffs.append({'field': 'pattern_maker_name', 'old': project.pattern_maker_name, 'new': new_pattern_maker_name})
        project.pattern_maker_id = pattern_maker_id
        project.pattern_maker_name = new_pattern_maker_name

    if remark is not None and remark != (project.remark or ''):
        field_diffs.append({'field': 'remark', 'old': project.remark, 'new': remark})
        project.remark = remark

    if product_image_file_id is not None and product_image_file_id != project.product_image_file_id:
        field_diffs.append({'field': 'product_image_file_id', 'old': project.product_image_file_id, 'new': product_image_file_id})
        project.product_image_file_id = product_image_file_id

    if current_version is not None and current_version != project.current_version:
        field_diffs.append({'field': 'current_version', 'old': project.current_version, 'new': current_version})
        project.current_version = current_version
        # 同步更新默认角色的 current_version（保持向后兼容）
        # 旧端点仍调 update_project 设置最终版本时，默认角色同步生效
        default_role_id = await _get_default_role_id(db, project_id)
        dr_result = await db.execute(
            select(CustomerSamplingRole).where(CustomerSamplingRole.id == default_role_id)
        )
        default_role = dr_result.scalar_one_or_none()
        if default_role is not None and default_role.current_version != current_version:
            default_role.current_version = current_version

    # 乐观锁 +1
    project.version += 1
    await db.flush()

    # 写审计日志
    operator_name = await _get_user_name(db, user_id)
    await _write_change_log(
        db, project.id, 'update_project', user_id, operator_name,
        field_diffs=field_diffs,
    )

    logger.info('编辑打样项目: id=%s, field_diffs=%s', project_id, field_diffs)
    return {'id': project.id}



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

    - 乐观锁校验
    - 校验 part_name 同项目下唯一（排除自身）
    - 修改在当前版本生效，历史版本快照不变
    """
    result = await db.execute(
        select(CustomerSamplingPart).where(CustomerSamplingPart.id == part_id)
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
    return {'id': part.id}



async def get_project_detail(db: AsyncSession, project_id: int) -> dict:
    """查询打样项目详情（含部位布料 + 版本列表）

    - 部位按 sort_order 升序
    - 版本按 version_no 升序
    - 拼接 product_image_url
    """
    result = await db.execute(
        select(CustomerSamplingProject)
        .options(
            selectinload(CustomerSamplingProject.parts).selectinload(CustomerSamplingPart.supplier),
            selectinload(CustomerSamplingProject.fabric_versions),
            selectinload(CustomerSamplingProject.creator),
            selectinload(CustomerSamplingProject.roles),
        )
        .where(CustomerSamplingProject.id == project_id)
    )
    project = result.scalar_one_or_none()
    if project is None:
        raise NotFoundError('打样项目不存在')

    image_info = await _get_product_image_urls(db, project.product_image_file_id)

    # 部位按 sort_order 升序（relationship 已配置 order_by，但显式排序更安全）
    parts_sorted = sorted(project.parts or [], key=lambda p: p.sort_order)
    # 版本按 version_no 升序
    versions_sorted = sorted(project.fabric_versions or [], key=lambda v: v.version_no)
    # 角色按 sort_order 升序
    roles_sorted = sorted(project.roles or [], key=lambda r: r.sort_order)

    return {
        'id': project.id,
        'sequence_no': project.sequence_no,
        'product_name': project.product_name,
        'product_image_url': image_info.get('url') if image_info else None,
        'product_image_thumbnail_url': image_info.get('thumbnail_url') if image_info else None,
        'product_image_blur_url': image_info.get('blur_url') if image_info else None,
        'product_image_file_id': project.product_image_file_id,
        'pattern_maker_id': project.pattern_maker_id,
        'pattern_maker_name': project.pattern_maker_name or '',
        'current_version': project.current_version,
        'status': project.status,
        'remark': project.remark or '',
        'created_by_name': project.creator.username if project.creator else None,
        'created_at': project.created_at.strftime('%Y-%m-%d %H:%M:%S') if project.created_at else '',
        'updated_at': project.updated_at.strftime('%Y-%m-%d %H:%M:%S') if project.updated_at else '',
        'version': project.version,
        'parts': [p.to_dict() for p in parts_sorted],
        'versions': [
            {
                'id': v.id,
                'version_no': v.version_no,
                'created_at': v.created_at.strftime('%Y-%m-%d %H:%M:%S') if v.created_at else '',
                'reason': v.reason or '',
            }
            for v in versions_sorted
        ],
        'roles': [r.to_dict() for r in roles_sorted],
    }



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

    Args:
        role_id: 归属角色ID；未传时自动解析项目的默认角色
    """
    await _ensure_project_exists(db, project_id)
    if role_id is None:
        role_id = await _get_default_role_id(db, project_id)
    else:
        await _ensure_role_belongs_to_project(db, role_id, project_id)

    operator_name = await _get_user_name(db, user_id)
    created_ids: list[int] = []

    for item in items:
        part_name = item['part_name']
        version_no = item.get('version_no', 'T1')
        supplier_id = item.get('supplier_id')
        fabric_name = item.get('fabric_name')
        fabric_color_no = item.get('fabric_color_no')

        # 同角色同版本下部位名称唯一
        await _ensure_part_name_unique(db, project_id, part_name, role_id=role_id, version_no=version_no)

        supplier_name = item.get('supplier_name') or ''
        if supplier_id is not None:
            supplier_name = await _resolve_supplier_name(db, supplier_id)
            if not supplier_name:
                raise NotFoundError(f'供应商 {supplier_id} 不存在')

        part = CustomerSamplingPart(
            project_id=project_id,
            role_id=role_id,
            version_no=version_no,
            part_name=part_name,
            sort_order=0,
            fabric_name=fabric_name,
            fabric_color_no=fabric_color_no,
            supplier_id=supplier_id,
            supplier_name=supplier_name,
        )
        db.add(part)
        await db.flush()
        created_ids.append(part.id)

        await _write_change_log(
            db, project_id, 'create_part', user_id, operator_name,
            part_name=part_name,
        )

    logger.info(
        '批量新增部位: project_id=%s, role_id=%s, count=%d, ids=%s',
        project_id, role_id, len(created_ids), created_ids,
    )
    return {'ids': created_ids, 'count': len(created_ids)}



async def delete_project(
    db: AsyncSession,
    project_id: int,
    *,
    user_id: int | None = None,
) -> dict:
    """删除打样项目

    - 先写审计日志（确保删除操作可追溯）
    - ORM cascade 级联删除部位/版本
    - 变更日志不级联删除：project_id 外键 SET NULL，日志保留可追溯
    - product_image_file_id 外键 SET NULL，FileRecord 保留
    """
    result = await db.execute(
        select(CustomerSamplingProject).where(CustomerSamplingProject.id == project_id)
    )
    project = result.scalar_one_or_none()
    if project is None:
        raise NotFoundError('打样项目不存在')

    # 先写审计日志（在级联删除前）
    operator_name = await _get_user_name(db, user_id)
    await _write_change_log(
        db, project_id, 'delete_project', user_id, operator_name,
    )
    await db.flush()

    # 级联删除（ORM cascade='all, delete-orphan'）
    # 注：change_logs relationship 已去掉 cascade，日志不级联删除（project_id SET NULL）
    await db.delete(project)
    await db.flush()

    logger.info('删除打样项目: id=%s', project_id)
    return {'id': project_id}


# ==================== T06: 部位布料 CRUD + 产品图片上传 ====================



async def update_project_status(
    db: AsyncSession,
    project_id: int,
    *,
    status: str,
    user_id: int | None = None,
) -> dict:
    """更新打样项目状态（in_progress / completed / cancelled）

    - 不参与乐观锁（独立的状态标记操作，最后写入为准）
    - 写审计日志
    """
    result = await db.execute(
        select(CustomerSamplingProject).where(CustomerSamplingProject.id == project_id)
    )
    project = result.scalar_one_or_none()
    if project is None:
        raise NotFoundError('打样项目不存在')

    old_status = project.status
    project.status = status
    # 标记完成时记录完成时间；取消完成/改为进行中时清空
    if status == 'completed' and old_status != 'completed':
        project.completed_at = datetime.now(UTC)
    elif status != 'completed':
        project.completed_at = None
    await db.flush()

    # 写审计日志
    operator_name = await _get_user_name(db, user_id)
    await _write_change_log(
        db, project.id, 'update_project_status', user_id, operator_name,
        field_diffs=[{'field': 'status', 'old': old_status, 'new': status}],
    )

    logger.info('更新打样项目状态: id=%s, %s → %s', project_id, old_status, status)
    return {'id': project.id}



async def delete_part(
    db: AsyncSession,
    part_id: int,
    *,
    user_id: int | None = None,
) -> dict:
    """删除部位

    - 历史版本快照中该部位数据保留（快照不可变，spec 5.5.1.6）
    """
    result = await db.execute(
        select(CustomerSamplingPart).where(CustomerSamplingPart.id == part_id)
    )
    part = result.scalar_one_or_none()
    if part is None:
        raise NotFoundError('部位不存在')

    # 禁止删除所属角色的当前最终版本，避免 role.current_version 悬空
    role_result = await db.execute(
        select(CustomerSamplingRole).where(CustomerSamplingRole.id == part.role_id)
    )
    role = role_result.scalar_one_or_none()
    if (
        role is not None
        and part.version_no is not None
        and part.version_no == role.current_version
    ):
        raise BusinessError('该版本为角色当前最终版本，请先将其他版本设为最终版后再删除')

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
    user_id: int | None = None,
) -> dict:
    """新增部位

    - 校验项目存在
    - 校验 part_name 同项目下唯一（应用层校验 + DB 唯一索引双重保障）
    - 校验 supplier_id 存在性，冗余存储 supplier_name
    - 未传 role_id 时归属项目的默认角色
    """
    await _ensure_project_exists(db, project_id)
    role_id = await _get_default_role_id(db, project_id)

    # 校验部位名称同项目下唯一
    await _ensure_part_name_unique(db, project_id, part_name)

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



async def list_projects(
    db: AsyncSession,
    *,
    page: int = 1,
    per_page: int = 20,
    keyword: str | None = None,
    pattern_maker_id: int | None = None,
    status: str | None = None,
) -> dict:
    """分页查询打样项目列表

    keyword 匹配序列号与产品名称（ILIKE），pattern_maker_id 筛选版师。
    status 缺省（None）时默认仅返回"进行中"项目（与 grouped-list 一致，前端漏传状态时的兜底）；
    显式传 'all' 返回全部状态的项目；传 in_progress/completed/cancelled 按对应状态过滤。
    """
    # status 缺省时默认按"进行中"过滤（兜底），显式传 'all' 可返回全部状态
    if status is None:
        status = 'in_progress'

    conditions = []
    if keyword:
        like = f'%{keyword}%'
        conditions.append(
            or_(
                CustomerSamplingProject.sequence_no.ilike(like),
                CustomerSamplingProject.product_name.ilike(like),
            )
        )
    if pattern_maker_id is not None:
        conditions.append(CustomerSamplingProject.pattern_maker_id == pattern_maker_id)
    if status != 'all':
        conditions.append(CustomerSamplingProject.status == status)

    # 计算总数
    count_query = select(func.count()).select_from(CustomerSamplingProject)
    for cond in conditions:
        count_query = count_query.where(cond)
    total = (await db.execute(count_query)).scalar_one()

    # 分页查询
    pages = max(1, (total + per_page - 1) // per_page)
    page = max(1, min(page, pages))

    # noload 抑制模型默认 lazy='selectin' 级联加载（列表摘要无需任何关联对象，
    # 图片 URL 由下方 _batch_get_image_urls 单次批量查询提供）
    query = (
        select(CustomerSamplingProject)
        .options(
            noload(CustomerSamplingProject.parts),
            noload(CustomerSamplingProject.roles),
            noload(CustomerSamplingProject.fabric_versions),
            noload(CustomerSamplingProject.change_logs),
            noload(CustomerSamplingProject.pattern_maker),
            noload(CustomerSamplingProject.product_image),
            noload(CustomerSamplingProject.creator),
        )
    )
    for cond in conditions:
        query = query.where(cond)
    query = query.order_by(CustomerSamplingProject.updated_at.desc()).offset((page - 1) * per_page).limit(per_page)

    result = await db.execute(query)
    rows = result.scalars().all()

    # 批量预取产品图片 URL（单次 SQL，消除逐项目查询的 N+1）
    image_url_map = await _batch_get_image_urls(
        db, [p.product_image_file_id for p in rows if p.product_image_file_id]
    )

    return {
        'success': True,
        'items': [_project_to_summary(p, image_url_map) for p in rows],
        'total': total,
        'pages': pages,
        'current_page': page,
    }



async def list_parts(db: AsyncSession, project_id: int, *, role_id: int | None = None) -> dict:
    """部位列表查询（按 sort_order 升序，含布料信息）

    Args:
        role_id: 角色ID筛选；未传时自动解析项目的默认角色
    """
    await _ensure_project_exists(db, project_id)
    if role_id is None:
        role_id = await _get_default_role_id(db, project_id)

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
