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

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from fastapi_app.core.exceptions import BusinessError, ConflictError, NotFoundError
from fastapi_app.shared_models import (
    CustomerSamplingRole,
)

logger = logging.getLogger(__name__)

# 版本快照中参与 diff 计算的布料业务字段
_SNAPSHOT_FIELDS = (
    'part_name', 'sort_order', 'fabric_name', 'fabric_spec',
    'supplier_id', 'supplier_name', 'contact_person', 'contact_phone',
    'unit_price', 'delivery_days', 'remark',
)

from .common import _ensure_project_exists, _get_user_name, _write_change_log


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
