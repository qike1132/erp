"""全局角色字典服务（role_service）。

提供全局角色（`role` 表，跨产品复用）的最小维护能力：列表 / 新建 / 改名 / 删除，
并落实两条关键保护（REQ-P0-01 / REQ-P0-02 / Q-02）：

1. **名称唯一性按 `lower(trim(name))` 校验**：冲突返回明确错误
   （``RoleNameConflictError``），绝不静默改名；
2. **禁止删除被任意产品引用的角色**：``delete_role`` 返回可区分的
   ``RoleReferencedError``（文案含引用数），端点映射为 **409**；DB 级另有
   `ON DELETE RESTRICT` 双保险。

改名的「镜像同步」：改名只改显示名，物料按 id 关联不受影响；同时把
``product_role.role_name``（回滚兼容镜像列）同步为新名，保证回滚后旧代码显示正确名（风险 M5）。
"""
from __future__ import annotations

import logging

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from fastapi_app.shared_models import ModificationLog, ProductRole, Role

logger = logging.getLogger(__name__)

_MAX_NAME_LEN = 100


class RoleNotFoundError(ValueError):
    """角色不存在（端点映射 404）。"""


class RoleNameConflictError(ValueError):
    """角色名冲突（按 lower(trim(name)) 比对，端点映射 400）。"""


class RoleReferencedError(ValueError):
    """角色被产品引用、禁止删除（端点映射 409）。"""


def _normalize_name(name: str | None) -> str:
    """trim 角色名并做基础校验。"""
    normalized = (name or '').strip()
    if not normalized:
        raise RoleNameConflictError('角色名不能为空')
    if len(normalized) > _MAX_NAME_LEN:
        raise RoleNameConflictError(f'角色名长度不能超过 {_MAX_NAME_LEN} 字符')
    return normalized


def _name_key(name: str | None) -> str:
    """大小写不敏感比较键（与 DB 的 lower(name) 唯一索引口径一致，另含 trim）。"""
    return (name or '').strip().lower()


def _to_item(role: Role) -> dict:
    return {'id': role.id, 'global_role_id': None, 'name': role.name}


async def list_roles(db: AsyncSession) -> list[dict]:
    """列出全部全局角色（按 lower(name) 稳定升序）。"""
    result = await db.execute(
        select(Role).order_by(func.lower(Role.name), Role.id)
    )
    return [_to_item(role) for role in result.scalars().all()]


async def _find_by_key(db: AsyncSession, key: str, exclude_id: int | None = None) -> Role | None:
    """按 lower(trim(name)) 查找全局角色；``exclude_id`` 用于改名排除自身。"""
    stmt = select(Role).where(func.lower(func.btrim(Role.name)) == key)
    if exclude_id is not None:
        stmt = stmt.where(Role.id != exclude_id)
    result = await db.execute(stmt.limit(1))
    return result.scalars().first()


async def create_role(db: AsyncSession, name: str, username: str = 'system') -> dict:
    """新建全局角色；名称冲突抛 ``RoleNameConflictError``。"""
    normalized = _normalize_name(name)
    if await _find_by_key(db, _name_key(normalized)) is not None:
        raise RoleNameConflictError(f'角色「{normalized}」已存在（名称比较不区分大小写）')
    role = Role(name=normalized)
    db.add(role)
    try:
        await db.flush()
    except IntegrityError as exc:
        # 并发窗口下的兜底：唯一索引 lower(name) 冲突
        raise RoleNameConflictError(f'角色「{normalized}」已存在（名称比较不区分大小写）') from exc
    db.add(ModificationLog(
        target_type='role', target_id=role.id, field_name='created',
        old_value='', new_value=normalized, modifier_name=username,
    ))
    return _to_item(role)


async def apply_global_rename(db: AsyncSession, role: Role, new_name: str) -> None:
    """改全局角色名 + 同步 ``product_role.role_name`` 镜像列（不写审计日志）。

    供 ``rename_role``（端点改名）与 ``bom_role_resolver``（保存 BOM 时改名）复用。
    """
    normalized = _normalize_name(new_name)
    role.name = normalized
    # 同步全部引用该全局角色的产品的镜像列（回滚兼容）
    await db.execute(
        update(ProductRole)
        .where(ProductRole.global_role_id == role.id)
        .values(role_name=normalized)
    )


async def rename_role(
    db: AsyncSession, role_id: int, new_name: str, username: str = 'system',
) -> dict:
    """重命名全局角色；冲突抛 ``RoleNameConflictError``，不存在抛 ``RoleNotFoundError``。"""
    normalized = _normalize_name(new_name)
    role = await db.get(Role, role_id)
    if role is None:
        raise RoleNotFoundError(f'角色 {role_id} 不存在')
    if _name_key(role.name) == _name_key(normalized):
        if role.name != normalized:
            await apply_global_rename(db, role, normalized)
        return _to_item(role)
    if await _find_by_key(db, _name_key(normalized), exclude_id=role_id) is not None:
        raise RoleNameConflictError(f'角色「{normalized}」已存在（名称比较不区分大小写）')
    old_name = role.name
    await apply_global_rename(db, role, normalized)
    db.add(ModificationLog(
        target_type='role', target_id=role.id, field_name='role_name',
        old_value=old_name, new_value=normalized, modifier_name=username,
    ))
    return _to_item(role)


async def delete_role(db: AsyncSession, role_id: int, username: str = 'system') -> str:
    """删除全局角色；被任意产品引用时抛 ``RoleReferencedError``（文案含引用数）。"""
    role = await db.get(Role, role_id)
    if role is None:
        raise RoleNotFoundError(f'角色 {role_id} 不存在')
    ref_count = int(
        await db.scalar(
            select(func.count()).select_from(ProductRole).where(
                ProductRole.global_role_id == role_id
            )
        ) or 0
    )
    if ref_count > 0:
        raise RoleReferencedError(
            f'角色「{role.name}」已被 {ref_count} 个产品关联，无法删除；请先在相关产品中解绑'
        )
    name = role.name
    await db.delete(role)
    db.add(ModificationLog(
        target_type='role', target_id=role_id, field_name='deleted',
        old_value=name, new_value='(已删除)', modifier_name=username,
    ))
    return f'角色「{name}」已删除'
