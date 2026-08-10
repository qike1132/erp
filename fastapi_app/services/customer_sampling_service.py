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


def _next_version(current: str) -> str:
    """T1 -> T2, T2 -> T3, ..."""
    try:
        n = int(current.lstrip('Tt'))
        return f'T{n + 1}'
    except (ValueError, AttributeError):
        return 'T1'


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


async def _get_product_image_url(db: AsyncSession, file_id: int | None) -> str | None:
    """通过 FileRecord.storage_key 拼接产品图片访问 URL"""
    if file_id is None:
        return None
    from fastapi_app.services.storage_service import get_storage
    result = await db.execute(select(FileRecord.storage_key).where(FileRecord.id == file_id))
    storage_key = result.scalar_one_or_none()
    if not storage_key:
        return None
    try:
        storage = get_storage()
        return storage.get_url(storage_key)
    except Exception as e:
        logger.warning('获取产品图片 URL 失败: file_id=%s, error=%s', file_id, e)
        return None


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
    query = query.order_by(CustomerSamplingProject.updated_at.desc())

    result = await db.execute(query)
    projects = result.scalars().all()

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
            'projects': [await _project_to_summary(db, p) for p in proj_list],
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
            'projects': [await _project_to_summary(db, p) for p in unclassified],
        })

    return {
        'success': True,
        'groups': groups,
        'total_projects': len(projects),
    }


async def _project_to_summary(db: AsyncSession, project: CustomerSamplingProject) -> dict:
    """将项目 ORM 对象转为 ProjectSummary dict"""
    image_url = await _get_product_image_url(db, project.product_image_file_id)
    return {
        'id': project.id,
        'sequence_no': project.sequence_no,
        'product_name': project.product_name,
        'product_image_url': image_url,
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

    return {
        'success': True,
        'items': [await _project_to_summary(db, p) for p in rows],
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
        )
        .where(CustomerSamplingProject.id == project_id)
    )
    project = result.scalar_one_or_none()
    if project is None:
        raise NotFoundError('打样项目不存在')

    image_url = await _get_product_image_url(db, project.product_image_file_id)

    # 部位按 sort_order 升序（relationship 已配置 order_by，但显式排序更安全）
    parts_sorted = sorted(project.parts or [], key=lambda p: p.sort_order)
    # 版本按 version_no 升序
    versions_sorted = sorted(project.fabric_versions or [], key=lambda v: v.version_no)

    return {
        'id': project.id,
        'sequence_no': project.sequence_no,
        'product_name': project.product_name,
        'product_image_url': image_url,
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
    }


async def create_project(
    db: AsyncSession,
    *,
    product_name: str,
    customer_id: int | None = None,
    remark: str | None = None,
    user_id: int | None = None,
) -> dict:
    """新增打样项目

    - 自动生成序列号 CS-YYYYMMDD-XXXX
    - 自动创建 T1 基线版本（snapshot_data=[], change_summary=null）
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

    # 自动创建 T1 基线版本（快照当前部位布料，初始为空数组）
    t1_version = CustomerSamplingFabricVersion(
        project_id=project.id,
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

    logger.info('创建打样项目: id=%s, sequence_no=%s', project.id, sequence_no)
    return {'id': project.id, 'sequence_no': sequence_no}


async def update_project(
    db: AsyncSession,
    project_id: int,
    *,
    product_name: str | None = None,
    customer_id: int | None = None,
    remark: str | None = None,
    product_image_file_id: int | None = None,
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

async def list_parts(db: AsyncSession, project_id: int) -> dict:
    """部位列表查询（按 sort_order 升序，含布料信息）"""
    # 校验项目存在
    await _ensure_project_exists(db, project_id)

    result = await db.execute(
        select(CustomerSamplingPart)
        .options(selectinload(CustomerSamplingPart.supplier))
        .where(CustomerSamplingPart.project_id == project_id)
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
    supplier_id: int | None = None,
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

    # 校验部位名称同项目下唯一（排除自身）
    if part_name is not None and part_name != part.part_name:
        await _ensure_part_name_unique(db, part.project_id, part_name, exclude_id=part_id)
        part.part_name = part_name

    # 解析供应商名称
    if supplier_id is not None and supplier_id != part.supplier_id:
        supplier_name = ''
        if supplier_id is not None:
            supplier_name = await _resolve_supplier_name(db, supplier_id)
            if not supplier_name:
                raise NotFoundError('所选供应商不存在')
        part.supplier_id = supplier_id
        part.supplier_name = supplier_name

    # 更新可选字段
    if sort_order is not None:
        part.sort_order = sort_order
    if fabric_name is not None:
        part.fabric_name = fabric_name
    if fabric_spec is not None:
        part.fabric_spec = fabric_spec
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

    # 复用 storage_service 保存文件
    upload_result = await save_upload(
        content=content,
        original_filename=original_filename,
        db=db,
        uploader_id=user_id,
        prefix='customer-sampling/',
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
    return {'file_id': upload_result['id'], 'url': upload_result['url']}


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
    user_id: int | None = None,
) -> dict:
    """创建新版本

    流程（design.md 2.1.3.2）：
    1. 加载打样项目（FOR UPDATE 行锁）
    2. 获取当前最大版本号 T_n，生成下一版本号 T_{n+1}
    3. 快照当前所有部位布料信息（序列化为 JSONB）
    4. 计算 T_{n+1} 相对 T_n 的字段级 diff
    5. 写入 customer_sampling_fabric_version（snapshot_data + change_summary）
    6. 写入 customer_sampling_change_log（审计记录）
    7. 更新项目 current_version = T_{n+1}，version 乐观锁 +1
    """
    # FOR UPDATE 锁项目行，防止并发创建版本冲突
    result = await db.execute(
        select(CustomerSamplingProject)
        .where(CustomerSamplingProject.id == project_id)
        .with_for_update()
    )
    project = result.scalar_one_or_none()
    if project is None:
        raise NotFoundError('打样项目不存在')

    # 获取当前最大版本号
    current_version = project.current_version or 'T1'
    new_version_no = _next_version(current_version)

    # 快照当前所有部位布料信息
    parts_result = await db.execute(
        select(CustomerSamplingPart)
        .where(CustomerSamplingPart.project_id == project_id)
        .order_by(CustomerSamplingPart.sort_order)
    )
    parts = parts_result.scalars().all()
    snapshot_data = [p.to_snapshot_dict() for p in parts]

    # 加载前一版本快照（T_n）用于 diff 计算
    prev_version_result = await db.execute(
        select(CustomerSamplingFabricVersion)
        .where(
            CustomerSamplingFabricVersion.project_id == project_id,
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
        version_no=new_version_no,
        snapshot_data=snapshot_data,
        change_summary=change_summary,
        reason=reason,
        created_by=user_id,
    )
    db.add(new_version)
    await db.flush()

    # 更新项目 current_version，乐观锁 +1
    project.current_version = new_version_no
    project.version += 1
    await db.flush()

    # 写审计日志
    operator_name = await _get_user_name(db, user_id)
    await _write_change_log(
        db, project_id, 'create_version', user_id, operator_name,
        target_version=new_version_no,
    )

    logger.info(
        '创建新版本: project_id=%s, version_no=%s, parts_count=%d, diff_count=%s',
        project_id, new_version_no, len(snapshot_data),
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
    exclude_id: int | None = None,
) -> None:
    """校验部位名称同项目下唯一

    Args:
        exclude_id: 编辑时排除自身 ID
    """
    query = select(CustomerSamplingPart.id).where(
        CustomerSamplingPart.project_id == project_id,
        CustomerSamplingPart.part_name == part_name,
    )
    if exclude_id is not None:
        query = query.where(CustomerSamplingPart.id != exclude_id)
    result = await db.execute(query)
    if result.scalar_one_or_none() is not None:
        raise BusinessError(f'部位名称 "{part_name}" 已存在')