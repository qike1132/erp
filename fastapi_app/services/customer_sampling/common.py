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

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from fastapi_app.core.exceptions import BusinessError, NotFoundError
from fastapi_app.shared_models import (
    CustomerSamplingChangeLog,
    CustomerSamplingPart,
    CustomerSamplingProject,
    CustomerSamplingRole,
    PatternMaker,
    Supplier,
    User,
)

logger = logging.getLogger(__name__)

# 版本快照中参与 diff 计算的布料业务字段
_SNAPSHOT_FIELDS = (
    'part_name', 'sort_order', 'fabric_name', 'fabric_spec',
    'supplier_id', 'supplier_name', 'contact_person', 'contact_phone',
    'unit_price', 'delivery_days', 'remark',
)

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



async def _resolve_supplier_name(db: AsyncSession, supplier_id: int | None) -> str:
    """解析供应商名称（冗余存储）"""
    if supplier_id is None:
        return ''
    result = await db.execute(select(Supplier.name).where(Supplier.id == supplier_id))
    row = result.scalar_one_or_none()
    return row or ''



async def _ensure_project_exists(db: AsyncSession, project_id: int) -> None:
    """校验项目存在，不存在抛 NotFoundError"""
    result = await db.execute(
        select(CustomerSamplingProject.id).where(CustomerSamplingProject.id == project_id)
    )
    if result.scalar_one_or_none() is None:
        raise NotFoundError('打样项目不存在')



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



async def _resolve_pattern_maker_name(db: AsyncSession, pattern_maker_id: int | None) -> str:
    """解析版师姓名（冗余存储）

    版师不存在时返回空字符串（降级展示）
    """
    if pattern_maker_id is None:
        return ''
    result = await db.execute(select(PatternMaker.name).where(PatternMaker.id == pattern_maker_id))
    row = result.scalar_one_or_none()
    return row or ''



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



async def _get_user_name(db: AsyncSession, user_id: int | None) -> str:
    """获取用户名（用于审计日志冗余存储）"""
    if user_id is None:
        return ''
    result = await db.execute(select(User.username).where(User.id == user_id))
    row = result.scalar_one_or_none()
    return row or ''
