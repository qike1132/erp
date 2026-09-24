"""customer_sampling 公共工具：存在性校验、冗余名称解析、基准角色与审计日志。

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

# 版本快照中参与 diff 计算的布料业务字段（唯一定义点，version_diff 等模块从此导入）
_SNAPSHOT_FIELDS = (
    'part_name', 'sort_order', 'fabric_name', 'fabric_spec',
    'supplier_id', 'supplier_name', 'contact_person', 'contact_phone',
    'unit_price', 'delivery_days', 'remark',
)


def _escape_like(keyword: str) -> str:
    r"""转义 LIKE/ILIKE 通配符（% _ \），使关键词按字面匹配。

    使用 ESCAPE '\' 子句；keyword 中的 % 不会被误当作"任意字符串"导致全量匹配。
    """
    return keyword.replace('\\', '\\\\').replace('%', r'\%').replace('_', r'\_')

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
        role_id: 角色ID；未传时自动解析项目的基准角色（sort_order 最小的角色）
        version_no: 版本号，同一角色同一版本内部位名称唯一
        exclude_id: 编辑时排除自身 ID
    """
    if role_id is None:
        role_id = await _get_primary_role_id(db, project_id)
        # 项目已无任何角色（可被全部删除）：没有可比对的部位，直接放行
        if role_id is None:
            return
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



async def _get_primary_role_id(db: AsyncSession, project_id: int) -> int | None:
    """获取项目的基准角色 ID（sort_order 最小的角色）

    用于调用方未指定 role_id 的场景（部位归属/版本对比等）。
    角色一律可删除，项目可能一个角色都不剩，此时返回 None，
    由调用方决定降级行为（读路径返回空数据、写路径提示先创建角色）。
    """
    result = await db.execute(
        select(CustomerSamplingRole.id)
        .where(CustomerSamplingRole.project_id == project_id)
        .order_by(CustomerSamplingRole.sort_order, CustomerSamplingRole.id)
        .limit(1)
    )
    return result.scalar_one_or_none()


async def _resolve_role_id(db: AsyncSession, project_id: int, role_id: int | None) -> int:
    """解析写路径的角色归属：显式传入时校验归属，未传时取基准角色

    角色一律可删除，项目可能一个角色都不剩；部位必须归属于某个角色，
    此时抛业务错误而非落到 NOT NULL 约束报错。
    """
    if role_id is not None:
        await _ensure_role_belongs_to_project(db, role_id, project_id)
        return role_id
    primary_role_id = await _get_primary_role_id(db, project_id)
    if primary_role_id is None:
        raise BusinessError('该项目暂无角色，请先新增角色')
    return primary_role_id



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



async def _get_user_name(db: AsyncSession, user_id: int | None) -> str:
    """获取用户名（用于审计日志冗余存储）"""
    if user_id is None:
        return ''
    result = await db.execute(select(User.username).where(User.id == user_id))
    row = result.scalar_one_or_none()
    return row or ''
