"""按客户分类打样信息模块服务层

职责：
- 按客户分组聚合查询（含"未分类"分组、按更新时间倒序）
- 打样项目 CRUD（含序列号自动生成、T1 基线版本自动创建、级联删除、乐观锁）
- 部位布料 CRUD（含部位名称同项目唯一校验、数值非负校验）
- 版本创建（快照当前部位布料 → 计算相对前一版本 diff → 写入快照表 + 审计日志）
- 版本详情查询（T1 完整快照 / T2+ 预计算 diff / 前一版本缺失降级）
- 变更日志查询
- 产品图片上传（复用 storage_service.save_upload）

约定：
- 服务层使用 flush() 而非 commit()，事务由 db_transaction 控制
- 编号通过 services/numbering.py 生成
- 所有写操作必须记录变更日志（包含操作人、原因、字段级 diff）

对应需求规格：.codeartsdoer/specs/customer_sampling/spec.md
对应技术设计：.codeartsdoer/specs/customer_sampling/design.md
"""
from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from fastapi_app.core.exceptions import BusinessError, ConflictError, NotFoundError
from fastapi_app.services.numbering import generate_customer_sampling_number
from fastapi_app.shared_models import (
    Customer,
    CustomerSamplingChangeLog,
    CustomerSamplingFabricVersion,
    CustomerSamplingPart,
    CustomerSamplingProject,
    CustomerSamplingRole,
    FileRecord,
    Supplier,
    User,
)

logger = logging.getLogger(__name__)


# ==================== 内部工具函数 ====================

# 版本快照中参与 diff 计算的布料业务字段
_SNAPSHOT_FIELDS = (
    'part_name', 'sort_order', 'fabric_name', 'fabric_spec',
    'supplier_id', 'supplier_name', 'contact_person', 'contact_phone',
    'unit_price', 'delivery_days', 'remark',
)


def _version_num(version_no: str | None) -> int:
    """解析版本号数值部分：T1 -> 1，解析失败返回 0"""
    try:
        return int((version_no or '').lstrip('Tt'))
    except (ValueError, AttributeError):
        return 0


def _next_version(current: str) -> str:
    """T1 -> T2, T2 -> T3, ..."""
    n = _version_num(current)
    return f'T{n + 1}' if n else 'T1'


def _normalize_value(value: Any) -> Any:
    """规范化字段值用于 diff 比较

    - None 与空字符串统一为 None
    - 数值转 float 避免 Decimal 与 float 精度差异
    """
    if value is None or value == '':
        return None
    # Decimal / int / float 统一转 float
    if isinstance(value, (int, float)) or hasattr(value, '__float__'):
        try:
            return float(value)
        except (TypeError, ValueError):
            return value
    return value


def _compute_diff(snapshot_n: list[dict], snapshot_prev: list[dict]) -> list[dict]:
    """计算两个版本快照的字段级 diff（纯函数，便于单元测试）

    算法（design.md 2.1.3.3）：
    1. 按 part_name 建字典索引
    2. 遍历 T_n 检测新增/修改
    3. 遍历 T_{n-1} 检测删除
    4. 修改类记录字段级 old/new 对照

    Args:
        snapshot_n: 新版本快照（部位布料数组）
        snapshot_prev: 前一版本快照（部位布料数组）

    Returns:
        变更记录列表，每元素含 change_type/part_name/new_value/old_value/field_diffs
    """
    dict_n = {p.get('part_name'): p for p in (snapshot_n or [])}
    dict_prev = {p.get('part_name'): p for p in (snapshot_prev or [])}
    changes: list[dict] = []

    # 遍历 T_n 检测新增与修改
    for part_name, part_n in dict_n.items():
        if part_name not in dict_prev:
            # 新增部位
            changes.append({
                'change_type': 'add',
                'part_name': part_name,
                'new_value': part_n,
                'old_value': None,
                'field_diffs': None,
            })
        else:
            # 检测字段级修改
            part_prev = dict_prev[part_name]
            field_diffs = []
            for field in _SNAPSHOT_FIELDS:
                old_val = _normalize_value(part_prev.get(field))
                new_val = _normalize_value(part_n.get(field))
                if old_val != new_val:
                    field_diffs.append({
                        'field': field,
                        'old': part_prev.get(field),
                        'new': part_n.get(field),
                    })
            if field_diffs:
                changes.append({
                    'change_type': 'modify',
                    'part_name': part_name,
                    'new_value': part_n,
                    'old_value': part_prev,
                    'field_diffs': field_diffs,
                })

    # 遍历 T_{n-1} 检测删除
    for part_name, part_prev in dict_prev.items():
        if part_name not in dict_n:
            changes.append({
                'change_type': 'delete',
                'part_name': part_name,
                'new_value': None,
                'old_value': part_prev,
                'field_diffs': None,
            })

    return changes


async def _get_user_name(db: AsyncSession, user_id: int | None) -> str:
    """获取用户名（用于审计日志冗余存储）"""
    if user_id is None:
        return ''
    result = await db.execute(select(User.username).where(User.id == user_id))
    row = result.scalar_one_or_none()
    return row or ''


async def _resolve_customer_name(db: AsyncSession, customer_id: int | None) -> str:
    """解析客户名称（冗余存储）

    客户不存在时返回空字符串（降级展示，spec 5.1.3.1）
    """
    if customer_id is None:
        return ''
    result = await db.execute(select(Customer.name).where(Customer.id == customer_id))
    row = result.scalar_one_or_none()
    return row or ''


async def _resolve_supplier_name(db: AsyncSession, supplier_id: int | None) -> str:
    """解析供应商名称（冗余存储）"""
    if supplier_id is None:
        return ''
    result = await db.execute(select(Supplier.name).where(Supplier.id == supplier_id))
    row = result.scalar_one_or_none()
    return row or ''


async def _batch_get_image_urls(db: AsyncSession, file_ids: list[int]) -> dict[int, dict]:
    """批量获取文件存储 URL（单次 IN 查询，替代逐个查询，消除列表页 N+1）

    Args:
        db: 数据库会话。
        file_ids: FileRecord ID 列表（可含重复，内部去重）。

    Returns:
        {file_id: {"url": ..., "thumbnail_url": ..., "blur_url": ...}} 映射；存储后端异常或单条失败时对应条目缺失。
        thumbnail_url / blur_url 通过 storage_key 派生固定后缀，前端加载失败时回退到 url（兼容历史无变体文件）。
    """
    if not file_ids:
        return {}
    from fastapi_app.services.storage_service import get_blur_key, get_storage, get_thumbnail_key
    result = await db.execute(
        select(FileRecord.id, FileRecord.storage_key).where(FileRecord.id.in_(set(file_ids)))
    )
    rows = result.all()
    if not rows:
        return {}
    try:
        storage = get_storage()
    except Exception as e:
        logger.warning('获取存储后端失败: %s', e)
        return {}
    url_map: dict[int, dict] = {}
    for fid, storage_key in rows:
        if not storage_key:
            continue
        try:
            url_map[fid] = {
                'url': storage.get_url(storage_key),
                'thumbnail_url': storage.get_url(get_thumbnail_key(storage_key)),
                'blur_url': storage.get_url(get_blur_key(storage_key)),
            }
        except Exception as e:
            logger.warning('获取产品图片 URL 失败: file_id=%s, error=%s', fid, e)
    return url_map


async def _get_product_image_urls(db: AsyncSession, file_id: int | None) -> dict | None:
    """通过 FileRecord.storage_key 拼接产品图片访问 URL（单条场景，复用批量实现）

    返回 {"url": ..., "thumbnail_url": ..., "blur_url": ...} 或 None
    """
    if file_id is None:
        return None
    url_map = await _batch_get_image_urls(db, [file_id])
    return url_map.get(file_id)


async def _write_change_log(
    db: AsyncSession,
    project_id: int,
    action: str,
    operator_id: int | None,
    operator_name: str = '',
    target_version: str | None = None,
    change_type: str | None = None,
    part_name: str | None = None,
    field_diffs: list | None = None,
) -> None:
    """写入变更日志（审计追溯）"""
    log = CustomerSamplingChangeLog(
        project_id=project_id,
        target_version=target_version,
        action=action,
        change_type=change_type,
        part_name=part_name,
        field_diffs=field_diffs,
        operator_id=operator_id,
        operator_name=operator_name,
    )
    db.add(log)
    await db.flush()


# ==================== T05: 按客户分组聚合查询 + 项目 CRUD ====================

# 分组列表单次查询的项目数上限（防护性截断，避免极端数据量下全量序列化）
_GROUPED_LIST_MAX_PROJECTS = 2000


async def get_grouped_list(
    db: AsyncSession,
    *,
    keyword: str | None = None,
    customer_id: int | None = None,
) -> dict:
    """按客户分组聚合查询打样项目列表

    - 未关联客户的项目归入"未分类"分组
    - 分组间按组内最新 updated_at 倒序，"未分类"始终最后
    - 组内项目按 updated_at 倒序

    Returns:
        GroupedListResponse dict
    """
    # 构建查询条件
    conditions = []
    if keyword:
        like = f'%{keyword}%'
        conditions.append(
            or_(
                CustomerSamplingProject.sequence_no.ilike(like),
                CustomerSamplingProject.product_name.ilike(like),
            )
        )
    if customer_id is not None:
        conditions.append(CustomerSamplingProject.customer_id == customer_id)

    # 查询所有项目（含客户关联，避免 N+1）
    query = select(CustomerSamplingProject).options(
        selectinload(CustomerSamplingProject.customer),
    )
    for cond in conditions:
        query = query.where(cond)
    query = query.order_by(CustomerSamplingProject.updated_at.desc()).limit(_GROUPED_LIST_MAX_PROJECTS)

    result = await db.execute(query)
    projects = result.scalars().all()

    # 批量预取产品图片 URL（单次 SQL，消除逐项目查询的 N+1）
    image_url_map = await _batch_get_image_urls(
        db, [p.product_image_file_id for p in projects if p.product_image_file_id]
    )
    summary_map = {p.id: _project_to_summary(p, image_url_map) for p in projects}

    # 应用层按 customer_id 分组
    groups_map: dict[int | None, list[CustomerSamplingProject]] = {}
    for p in projects:
        key = p.customer_id
        groups_map.setdefault(key, []).append(p)

    # 构建分组响应
    groups = []
    for cid, proj_list in groups_map.items():
        if cid is None:
            # "未分类"分组最后处理
            continue
        # 获取客户名称（优先用冗余字段，降级用关联查询）
        customer_name = proj_list[0].customer_name or ''
        if not customer_name and proj_list[0].customer:
            customer_name = proj_list[0].customer.name
        latest_update = max(p.updated_at for p in proj_list)
        groups.append({
            'customer_id': cid,
            'customer_name': customer_name or '未命名客户',
            'project_count': len(proj_list),
            'latest_update_time': latest_update.strftime('%Y-%m-%d %H:%M:%S') if latest_update else '',
            'projects': [summary_map[p.id] for p in proj_list],
        })

    # 分组间按组内最新更新时间倒序
    groups.sort(key=lambda g: g['latest_update_time'], reverse=True)

    # "未分类"分组始终最后
    unclassified = groups_map.get(None, [])
    if unclassified:
        latest_update = max(p.updated_at for p in unclassified)
        groups.append({
            'customer_id': None,
            'customer_name': '未分类',
            'project_count': len(unclassified),
            'latest_update_time': latest_update.strftime('%Y-%m-%d %H:%M:%S') if latest_update else '',
            'projects': [summary_map[p.id] for p in unclassified],
        })

    return {
        'success': True,
        'groups': groups,
        'total_projects': len(projects),
    }


def _project_to_summary(project: CustomerSamplingProject, image_url_map: dict[int, dict]) -> dict:
    """将项目 ORM 对象转为 ProjectSummary dict（纯函数，图片 URL 由批量映射提供）"""
    image_info = (
        image_url_map.get(project.product_image_file_id)
        if project.product_image_file_id else None
    )
    return {
        'id': project.id,
        'sequence_no': project.sequence_no,
        'product_name': project.product_name,
        'product_image_url': image_info.get('url') if image_info else None,
        'product_image_thumbnail_url': image_info.get('thumbnail_url') if image_info else None,
        'product_image_blur_url': image_info.get('blur_url') if image_info else None,
        'current_version': project.current_version,
        'updated_at': project.updated_at.strftime('%Y-%m-%d %H:%M:%S') if project.updated_at else '',
    }


async def list_projects(
    db: AsyncSession,
    *,
    page: int = 1,
    per_page: int = 20,
    keyword: str | None = None,
    customer_id: int | None = None,
) -> dict:
    """分页查询打样项目列表

    keyword 匹配序列号与产品名称（ILIKE），customer_id 筛选客户
    """
    conditions = []
    if keyword:
        like = f'%{keyword}%'
        conditions.append(
            or_(
                CustomerSamplingProject.sequence_no.ilike(like),
                CustomerSamplingProject.product_name.ilike(like),
            )
        )
    if customer_id is not None:
        conditions.append(CustomerSamplingProject.customer_id == customer_id)

    # 计算总数
    count_query = select(func.count()).select_from(CustomerSamplingProject)
    for cond in conditions:
        count_query = count_query.where(cond)
    total = (await db.execute(count_query)).scalar_one()

    # 分页查询
    pages = max(1, (total + per_page - 1) // per_page)
    page = max(1, min(page, pages))

    query = select(CustomerSamplingProject)
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
        'customer_id': project.customer_id,
        'customer_name': project.customer_name or '',
        'current_version': project.current_version,
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


async def create_project(
    db: AsyncSession,
    *,
    product_name: str,
    customer_id: int | None = None,
    remark: str | None = None,
    initial_roles: list[str] | None = None,
    user_id: int | None = None,
) -> dict:
    """新增打样项目

    - 自动生成序列号 CS-YYYYMMDD-XXXX
    - 自动创建"默认角色"（is_default=true）
    - 若传入 initial_roles，额外创建用户指定的角色（去重、去空白）
    - 自动创建 T1 基线版本挂在默认角色下（snapshot_data=[], change_summary=null）
    - 校验 customer_id 存在性，冗余存储 customer_name
    """
    # 校验客户存在性
    customer_name = ''
    if customer_id is not None:
        customer_name = await _resolve_customer_name(db, customer_id)
        if not customer_name:
            raise NotFoundError('所选客户不存在')

    # 生成序列号
    sequence_no = await generate_customer_sampling_number(db)

    # 创建项目
    project = CustomerSamplingProject(
        sequence_no=sequence_no,
        product_name=product_name,
        customer_id=customer_id,
        customer_name=customer_name,
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


async def update_project(
    db: AsyncSession,
    project_id: int,
    *,
    product_name: str | None = None,
    customer_id: int | None = None,
    remark: str | None = None,
    product_image_file_id: int | None = None,
    current_version: str | None = None,
    version: int,
    user_id: int | None = None,
) -> dict:
    """编辑打样项目

    - 乐观锁校验（version 不匹配抛 ConflictError 409）
    - 可修改：product_name、customer_id、customer_name、remark、product_image_file_id
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

    if customer_id is not None and customer_id != project.customer_id:
        # 校验新客户存在性
        new_customer_name = await _resolve_customer_name(db, customer_id)
        if customer_id is not None and not new_customer_name:
            raise NotFoundError('所选客户不存在')
        field_diffs.append({'field': 'customer_id', 'old': project.customer_id, 'new': customer_id})
        field_diffs.append({'field': 'customer_name', 'old': project.customer_name, 'new': new_customer_name})
        project.customer_id = customer_id
        project.customer_name = new_customer_name

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
    """
    await _ensure_project_exists(db, project_id)

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


async def upload_project_image(
    db: AsyncSession,
    project_id: int,
    *,
    content: bytes,
    original_filename: str,
    content_type: str | None = None,
    user_id: int | None = None,
) -> dict:
    """上传产品图片

    - 复用 storage_service.save_upload
    - 更新 project.product_image_file_id
    - 文件类型限制 image/jpeg|png|webp，大小 ≤ 10MB（storage_service 安全策略）
    """
    from fastapi_app.services.storage_service import save_upload

    # 校验项目存在
    await _ensure_project_exists(db, project_id)

    # 文件类型校验
    allowed_types = {'image/jpeg', 'image/png', 'image/webp'}
    if content_type and content_type not in allowed_types:
        raise BusinessError('图片格式不支持，仅支持 JPEG/PNG/WebP')

    # 文件大小校验（≤ 10MB）
    max_size = 10 * 1024 * 1024
    if len(content) > max_size:
        raise BusinessError('图片大小不能超过 10MB')

    # 复用 storage_service 保存文件（同步生成 400px WebP 缩略图供列表使用）
    upload_result = await save_upload(
        content=content,
        original_filename=original_filename,
        db=db,
        uploader_id=user_id,
        prefix='customer-sampling/',
        generate_thumbnail=True,
    )

    # 更新项目的 product_image_file_id
    result = await db.execute(
        select(CustomerSamplingProject).where(CustomerSamplingProject.id == project_id)
    )
    project = result.scalar_one_or_none()
    if project is None:
        raise NotFoundError('打样项目不存在')
    project.product_image_file_id = upload_result['id']
    await db.flush()

    # 写审计日志
    operator_name = await _get_user_name(db, user_id)
    await _write_change_log(
        db, project_id, 'upload_image', user_id, operator_name,
    )

    logger.info(
        '上传产品图片: project_id=%s, file_id=%s, url=%s',
        project_id, upload_result['id'], upload_result['url'],
    )
    return {
        'file_id': upload_result['id'],
        'url': upload_result['url'],
        'thumbnail_url': upload_result.get('thumbnail_url'),
    }


# ==================== T06b: 角色 CRUD ====================

async def list_roles(db: AsyncSession, project_id: int) -> dict:
    """列出项目所有角色（按 sort_order 升序）"""
    await _ensure_project_exists(db, project_id)
    result = await db.execute(
        select(CustomerSamplingRole)
        .where(CustomerSamplingRole.project_id == project_id)
        .order_by(CustomerSamplingRole.sort_order)
    )
    roles = result.scalars().all()
    return {
        'success': True,
        'items': [r.to_dict() for r in roles],
    }


async def create_role(
    db: AsyncSession,
    project_id: int,
    *,
    role_name: str,
    user_id: int | None = None,
) -> dict:
    """新增角色（项目内 role_name 唯一，默认角色不可重复创建）

    - 新角色 sort_order = 当前最大 sort_order + 1
    - 新角色 current_version='T1'，但不会自动创建 T1 版本快照（与项目级 T1 不同）
      —— 用户在该角色下录入部位/创建版本时再生成快照
    """
    await _ensure_project_exists(db, project_id)

    # 唯一性校验（应用层 + DB 唯一约束双重保障）
    existing = await db.execute(
        select(CustomerSamplingRole.id).where(
            CustomerSamplingRole.project_id == project_id,
            CustomerSamplingRole.role_name == role_name,
        )
    )
    if existing.scalar_one_or_none() is not None:
        raise BusinessError(f'角色名 "{role_name}" 在该项目中已存在')

    # 计算 sort_order
    max_sort_result = await db.execute(
        select(func.max(CustomerSamplingRole.sort_order))
        .where(CustomerSamplingRole.project_id == project_id)
    )
    max_sort = max_sort_result.scalar_one_or_none() or 0

    role = CustomerSamplingRole(
        project_id=project_id,
        role_name=role_name,
        sort_order=max_sort + 1,
        is_default=False,
        current_version='T1',
    )
    db.add(role)
    await db.flush()

    # 写审计日志
    operator_name = await _get_user_name(db, user_id)
    await _write_change_log(
        db, project_id, 'create_role', user_id, operator_name,
        part_name=role_name,
    )

    logger.info('新增角色: project_id=%s, role_id=%s, role_name=%s', project_id, role.id, role_name)
    return {'id': role.id}


async def update_role(
    db: AsyncSession,
    role_id: int,
    *,
    role_name: str | None = None,
    current_version: str | None = None,
    version: int,
    user_id: int | None = None,
) -> dict:
    """编辑角色（乐观锁校验，is_default 不可改）

    - role_name 修改时仍需保证项目内唯一
    - current_version 修改用于"设置最终版本"场景
    """
    result = await db.execute(
        select(CustomerSamplingRole).where(CustomerSamplingRole.id == role_id)
    )
    role = result.scalar_one_or_none()
    if role is None:
        raise NotFoundError('角色不存在')

    # 乐观锁校验
    if role.version != version:
        raise ConflictError('该角色已被他人更新，请刷新后重试')

    field_diffs: list[dict] = []

    if role_name is not None and role_name != role.role_name:
        # 唯一性校验（排除自身）
        existing = await db.execute(
            select(CustomerSamplingRole.id).where(
                CustomerSamplingRole.project_id == role.project_id,
                CustomerSamplingRole.role_name == role_name,
                CustomerSamplingRole.id != role_id,
            )
        )
        if existing.scalar_one_or_none() is not None:
            raise BusinessError(f'角色名 "{role_name}" 在该项目中已存在')
        field_diffs.append({'field': 'role_name', 'old': role.role_name, 'new': role_name})
        role.role_name = role_name

    if current_version is not None and current_version != role.current_version:
        field_diffs.append({'field': 'current_version', 'old': role.current_version, 'new': current_version})
        role.current_version = current_version

    role.version += 1
    await db.flush()

    # 写审计日志
    operator_name = await _get_user_name(db, user_id)
    await _write_change_log(
        db, role.project_id, 'update_role', user_id, operator_name,
        field_diffs=field_diffs,
    )

    logger.info('编辑角色: role_id=%s, field_diffs=%s', role_id, field_diffs)
    return {'id': role.id}


async def delete_role(
    db: AsyncSession,
    role_id: int,
    *,
    user_id: int | None = None,
) -> dict:
    """删除角色（级联删 part + version + change_log 中关联该 role 的记录）

    - 默认角色不可删除（is_default=True）
    - 删除后变更日志 project_id 仍保留（SET NULL 行为不变）
    """
    result = await db.execute(
        select(CustomerSamplingRole).where(CustomerSamplingRole.id == role_id)
    )
    role = result.scalar_one_or_none()
    if role is None:
        raise NotFoundError('角色不存在')

    if role.is_default:
        raise BusinessError('默认角色不可删除')

    project_id = role.project_id
    role_name = role.role_name

    # 级联删除（ORM cascade='all, delete-orphan' 自动删 part + fabric_version）
    await db.delete(role)
    await db.flush()

    # 写审计日志
    operator_name = await _get_user_name(db, user_id)
    await _write_change_log(
        db, project_id, 'delete_role', user_id, operator_name,
        part_name=role_name,
    )

    logger.info('删除角色: role_id=%s, role_name=%s', role_id, role_name)
    return {'id': role_id}


# ==================== T07: 版本创建 + 版本详情 + 变更日志 ====================

async def list_versions(db: AsyncSession, project_id: int) -> dict:
    """版本列表查询（按 version_no 升序）"""
    await _ensure_project_exists(db, project_id)

    result = await db.execute(
        select(CustomerSamplingFabricVersion)
        .where(CustomerSamplingFabricVersion.project_id == project_id)
        .order_by(CustomerSamplingFabricVersion.version_no)
    )
    versions = result.scalars().all()
    return {
        'success': True,
        'items': [
            {
                'id': v.id,
                'version_no': v.version_no,
                'created_at': v.created_at.strftime('%Y-%m-%d %H:%M:%S') if v.created_at else '',
                'reason': v.reason or '',
            }
            for v in versions
        ],
    }


async def create_version(
    db: AsyncSession,
    project_id: int,
    *,
    reason: str | None = None,
    role_id: int | None = None,
    user_id: int | None = None,
) -> dict:
    """创建新版本（角色维度独立）

    流程（design.md 2.1.3.2 + 角色维度）：
    1. 加载角色（FOR UPDATE 行锁），未传 role_id 时默认指向项目的默认角色
    2. 获取该角色当前最大版本号 T_n，生成下一版本号 T_{n+1}
    3. 快照该角色当前所有部位布料信息（序列化为 JSONB）
    4. 计算 T_{n+1} 相对 T_n 的字段级 diff
    5. 写入 customer_sampling_fabric_version（snapshot_data + change_summary + role_id）
    6. 写入 customer_sampling_change_log（审计记录）
    7. 更新 role.current_version = T_{n+1}，role.version 乐观锁 +1
    """
    await _ensure_project_exists(db, project_id)
    if role_id is None:
        role_id = await _get_default_role_id(db, project_id)
    else:
        await _ensure_role_belongs_to_project(db, role_id, project_id)

    # FOR UPDATE 锁角色行，防止并发创建版本冲突
    role_result = await db.execute(
        select(CustomerSamplingRole)
        .where(CustomerSamplingRole.id == role_id)
        .with_for_update()
    )
    role = role_result.scalar_one_or_none()
    if role is None:
        raise NotFoundError('角色不存在')

    # 获取该角色当前最大版本号
    current_version = role.current_version or 'T1'
    new_version_no = _next_version(current_version)

    # 快照该角色当前所有部位布料信息
    parts_result = await db.execute(
        select(CustomerSamplingPart)
        .where(
            CustomerSamplingPart.project_id == project_id,
            CustomerSamplingPart.role_id == role_id,
        )
        .order_by(CustomerSamplingPart.sort_order)
    )
    parts = parts_result.scalars().all()
    snapshot_data = [p.to_snapshot_dict() for p in parts]

    # 加载前一版本快照（T_n）用于 diff 计算
    prev_version_result = await db.execute(
        select(CustomerSamplingFabricVersion)
        .where(
            CustomerSamplingFabricVersion.role_id == role_id,
            CustomerSamplingFabricVersion.version_no == current_version,
        )
    )
    prev_version = prev_version_result.scalar_one_or_none()

    # 计算 diff
    if prev_version is not None and prev_version.snapshot_data is not None:
        change_summary = _compute_diff(snapshot_data, prev_version.snapshot_data)
    else:
        # 前一版本不存在（理论上不应发生，因 T1 在创建项目时自动创建）
        change_summary = None

    # 写入新版本快照
    new_version = CustomerSamplingFabricVersion(
        project_id=project_id,
        role_id=role_id,
        version_no=new_version_no,
        snapshot_data=snapshot_data,
        change_summary=change_summary,
        reason=reason,
        created_by=user_id,
    )
    db.add(new_version)
    await db.flush()

    # 更新角色 current_version，乐观锁 +1
    role.current_version = new_version_no
    role.version += 1
    await db.flush()

    # 写审计日志
    operator_name = await _get_user_name(db, user_id)
    await _write_change_log(
        db, project_id, 'create_version', user_id, operator_name,
        target_version=new_version_no,
    )

    logger.info(
        '创建新版本: project_id=%s, role_id=%s, version_no=%s, parts_count=%d, diff_count=%s',
        project_id, role_id, new_version_no, len(snapshot_data),
        len(change_summary) if change_summary else 0,
    )
    return {'version_id': new_version.id, 'version_no': new_version_no}


async def get_version_detail(db: AsyncSession, version_id: int) -> dict:
    """版本详情查询

    - T1（is_baseline=True）：返回 full_snapshot，change_summary=null
    - T2+ 正常：返回 change_summary（预计算 diff），full_snapshot=null
    - 降级策略：若 T_{n-1} 快照缺失/损坏（change_summary 为 null 但非 T1），
      返回 T_n 完整快照 + degraded=true
    """
    result = await db.execute(
        select(CustomerSamplingFabricVersion)
        .options(selectinload(CustomerSamplingFabricVersion.creator))
        .where(CustomerSamplingFabricVersion.id == version_id)
    )
    version = result.scalar_one_or_none()
    if version is None:
        raise NotFoundError('版本不存在')

    is_baseline = version.version_no == 'T1'
    snapshot_data = version.snapshot_data or []

    # 判断是否降级：非 T1 但 change_summary 为 null（前一版本快照缺失/损坏）
    degraded = not is_baseline and version.change_summary is None

    if is_baseline or degraded:
        # T1 或降级：返回完整快照
        full_snapshot = snapshot_data
        change_summary = None
    else:
        # T2+ 正常：返回预计算 diff
        full_snapshot = None
        change_summary = version.change_summary

    return {
        'id': version.id,
        'project_id': version.project_id,
        'version_no': version.version_no,
        'created_at': version.created_at.strftime('%Y-%m-%d %H:%M:%S') if version.created_at else '',
        'is_baseline': is_baseline,
        'degraded': degraded,
        'full_snapshot': full_snapshot,
        'change_summary': change_summary,
    }


async def get_parts_by_version(
    db: AsyncSession,
    project_id: int,
    *,
    role_id: int | None = None,
) -> dict:
    """获取指定角色所有版本的部位布料数据（跨版本二维表数据源）

    数据来源两级合并：
    1. `customer_sampling_part` 表 — 该角色所有版本号实时数据（优先，保证新增/编辑/删除立即可见）
    2. `customer_sampling_fabric_version.snapshot_data` — 该角色历史快照（补充 part 表未覆盖的版本）

    按 part_name → version_no 排序后返回扁平列表。

    Args:
        role_id: 角色ID筛选；未传时自动解析项目的默认角色

    Returns:
        {
            'success': True,
            'items': [PartDetail + version_no, ...],
            'versions': ['T1', 'T2', ...],
            'final_version': role.current_version,
        }
    """
    await _ensure_project_exists(db, project_id)
    if role_id is None:
        role_id = await _get_default_role_id(db, project_id)
    else:
        await _ensure_role_belongs_to_project(db, role_id, project_id)

    # 1. 从 part 表读取该角色所有版本化部件（带 supplier 关联）
    parts_result = await db.execute(
        select(CustomerSamplingPart)
        .options(selectinload(CustomerSamplingPart.supplier))
        .where(
            CustomerSamplingPart.project_id == project_id,
            CustomerSamplingPart.role_id == role_id,
        )
        .order_by(CustomerSamplingPart.sort_order)
    )
    all_parts = parts_result.scalars().all()

    # 从 part 表构建 (part_name, version_no) → dict 的索引
    seen_keys: set[tuple[str, str]] = set()
    items: list[dict] = []
    version_set: set[str] = set()

    for part in all_parts:
        key = (part.part_name, part.version_no)
        if key in seen_keys:
            continue
        seen_keys.add(key)
        version_set.add(part.version_no)
        part_copy = {**part.to_snapshot_dict(), 'version_no': part.version_no}
        items.append(part_copy)

    # 2. 从该角色历史版本快照补充 part 表未覆盖的版本
    versions_result = await db.execute(
        select(CustomerSamplingFabricVersion)
        .where(
            CustomerSamplingFabricVersion.project_id == project_id,
            CustomerSamplingFabricVersion.role_id == role_id,
        )
        .order_by(CustomerSamplingFabricVersion.id.asc())
    )
    versions = versions_result.scalars().all()

    for ver in versions:
        version_set.add(ver.version_no)
        snapshot: list[dict] = ver.snapshot_data or []
        for part in snapshot:
            key = (part.get('part_name', ''), ver.version_no)
            if key in seen_keys:
                continue  # part 表已有此版本数据，跳过快照
            seen_keys.add(key)
            part_copy = {**part, 'version_no': ver.version_no}
            items.append(part_copy)

    version_list = sorted(version_set, key=lambda v: (len(v), v))

    # 加载角色 current_version 作为「最终版本」
    role_result = await db.execute(
        select(CustomerSamplingRole.current_version).where(CustomerSamplingRole.id == role_id)
    )
    final_version = role_result.scalar_one_or_none() or 'T1'

    return {
        'success': True,
        'items': items,
        'versions': version_list,
        'final_version': final_version,
    }


async def list_change_logs(
    db: AsyncSession,
    project_id: int,
    *,
    page: int = 1,
    per_page: int = 50,
) -> dict:
    """变更日志查询（按 created_at 倒序分页）"""
    await _ensure_project_exists(db, project_id)

    # 计算总数
    count_query = (
        select(func.count())
        .select_from(CustomerSamplingChangeLog)
        .where(CustomerSamplingChangeLog.project_id == project_id)
    )
    total = (await db.execute(count_query)).scalar_one()

    pages = max(1, (total + per_page - 1) // per_page)
    page = max(1, min(page, pages))

    result = await db.execute(
        select(CustomerSamplingChangeLog)
        .options(selectinload(CustomerSamplingChangeLog.operator))
        .where(CustomerSamplingChangeLog.project_id == project_id)
        .order_by(CustomerSamplingChangeLog.created_at.desc())
        .offset((page - 1) * per_page)
        .limit(per_page)
    )
    logs = result.scalars().all()

    return {
        'success': True,
        'items': [log.to_dict() for log in logs],
        'total': total,
        'pages': pages,
        'current_page': page,
    }


# ==================== 内部校验函数 ====================

async def _ensure_project_exists(db: AsyncSession, project_id: int) -> None:
    """校验项目存在，不存在抛 NotFoundError"""
    result = await db.execute(
        select(CustomerSamplingProject.id).where(CustomerSamplingProject.id == project_id)
    )
    if result.scalar_one_or_none() is None:
        raise NotFoundError('打样项目不存在')


async def _ensure_part_name_unique(
    db: AsyncSession,
    project_id: int,
    part_name: str,
    *,
    role_id: int | None = None,
    version_no: str = 'T1',
    exclude_id: int | None = None,
) -> None:
    """校验部位名称同角色 + 同版本下唯一

    Args:
        role_id: 角色ID；未传时自动解析项目的默认角色
        version_no: 版本号，同一角色同一版本内部位名称唯一
        exclude_id: 编辑时排除自身 ID
    """
    if role_id is None:
        role_id = await _get_default_role_id(db, project_id)
    query = select(CustomerSamplingPart.id).where(
        CustomerSamplingPart.project_id == project_id,
        CustomerSamplingPart.role_id == role_id,
        CustomerSamplingPart.part_name == part_name,
        CustomerSamplingPart.version_no == version_no,
    )
    if exclude_id is not None:
        query = query.where(CustomerSamplingPart.id != exclude_id)
    result = await db.execute(query)
    if result.scalar_one_or_none() is not None:
        raise BusinessError(f'部位名称 "{part_name}" 在当前版本中已存在')


async def _get_default_role_id(db: AsyncSession, project_id: int) -> int:
    """获取项目的默认角色 ID（is_default=True）

    若项目尚无默认角色（仅迁移前的旧项目可能发生，迁移已确保存在），
    则主动创建一个默认角色并返回其 ID（防御性兜底）。
    """
    result = await db.execute(
        select(CustomerSamplingRole.id).where(
            CustomerSamplingRole.project_id == project_id,
            CustomerSamplingRole.is_default == True,  # noqa: E712
        )
    )
    role_id = result.scalar_one_or_none()
    if role_id is not None:
        return role_id

    # 防御性兜底：旧库未跑迁移时主动补一个默认角色
    role = CustomerSamplingRole(
        project_id=project_id,
        role_name='默认',
        sort_order=0,
        is_default=True,
        current_version='T1',
    )
    db.add(role)
    await db.flush()
    return role.id


async def _ensure_role_belongs_to_project(db: AsyncSession, role_id: int, project_id: int) -> None:
    """校验 role_id 属于指定 project_id，否则抛 NotFoundError"""
    result = await db.execute(
        select(CustomerSamplingRole.id).where(
            CustomerSamplingRole.id == role_id,
            CustomerSamplingRole.project_id == project_id,
        )
    )
    if result.scalar_one_or_none() is None:
        raise NotFoundError('角色不存在或不属于该打样项目')