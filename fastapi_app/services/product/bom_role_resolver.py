"""BOM 角色解析器（bom_role_resolver）。

把 ``save_bom`` 的角色段解析从 ``bom_service``（实测 958 行，已超「服务文件 ≤800 行」
规范）中抽出，避免该文件继续膨胀（风险 M2）。

支持三种入参（见 §3.2 / §4.2 时序图）：

- ``global_role_id``：关联**已有**全局角色（同产品重复关联幂等复用）；
- ``role_key``：**新建**全局角色（客户端临时键），并映射为关联行 id 存入 ``temp_role_map``，
  供物料行的 ``role_id`` 归属解析；
- ``id``：**既有**关联行（改名时同步全局角色名与 ``product_role.role_name`` 镜像列）。

设计约束：本模块所有函数内**不得**出现「循环体内 ``await execute/scalar/scalars``」
（N+1 静态门禁），故全局角色一律批量预取后走内存映射；改名的镜像同步（可能跨产品）
委托 ``role_service.apply_global_rename`` 完成。
"""
from __future__ import annotations

import logging
from typing import NamedTuple

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from fastapi_app.services.product.role_service import (
    _name_key,
    _normalize_name,
    apply_global_rename,
)
from fastapi_app.shared_models import ModificationLog, ProductRole, Role

logger = logging.getLogger(__name__)


class RoleResolution(NamedTuple):
    """角色段解析结果。"""
    role_ids: list[int]              # 本产品最终保留/新建的关联行 id（用于删除未提交行）
    temp_role_map: dict[str, int]    # 客户端 role_key -> 关联行 id
    logs: list[dict]                 # 审计日志明细（便于可观测/测试）


def _prepare_items(payload_roles: list) -> list[dict]:
    """归一化 payload 角色项，计算名称比较键。"""
    prepared: list[dict] = []
    for item in payload_roles or []:
        raw_name = item.get('role_name') or item.get('name') or ''
        try:
            name = _normalize_name(raw_name)
        except ValueError:
            name = ''  # 空/非法名：跳过（与原实现一致，不建角色）
        prepared.append({
            'role_name': name,
            'key': _name_key(name),
            'rid': item.get('id'),
            'role_key': item.get('role_key'),
            'global_role_id': item.get('global_role_id'),
        })
    return prepared


async def _load_global_roles_by_key(db: AsyncSession, keys: set[str]) -> dict[str, Role]:
    """批量预取全局角色，按 lower(trim(name)) 建索引（一次查询，避免 N+1）。"""
    if not keys:
        return {}
    result = await db.execute(
        select(Role).where(func.lower(func.btrim(Role.name)).in_(keys))
    )
    return {_name_key(role.name): role for role in result.scalars().all()}


def _ensure_new_globals(
    db: AsyncSession, prepared: list[dict], by_key: dict[str, Role],
) -> list[Role]:
    """为「全新角色」（无 id、无 global_role_id、有名称）创建全局角色（未 flush）。"""
    created: list[Role] = []
    for p in prepared:
        if p['rid'] is None and p['global_role_id'] is None and p['key']:
            if p['key'] not in by_key:
                role = Role(name=p['role_name'])
                db.add(role)
                by_key[p['key']] = role
                created.append(role)
    return created


def _resolve_target_global_id(p: dict, existing_by_id: dict, by_key: dict) -> int | None:
    """解析该角色项应指向的 global_role_id。"""
    if p['global_role_id'] is not None:
        return p['global_role_id']
    if p['rid'] is not None:
        assoc = existing_by_id.get(p['rid'])
        return assoc.global_role_id if assoc is not None else None
    role = by_key.get(p['key'])
    return role.id if role is not None else None


def _assoc_name_for_new(p: dict, gid: int | None, by_id: dict) -> str:
    """新建关联行的 role_name（镜像列）取值。"""
    if p['role_name']:
        return p['role_name']
    role = by_id.get(gid) if gid is not None else None
    return role.name if role is not None else ''


async def _apply_existing_assoc(
    db: AsyncSession, assoc: ProductRole, p: dict, username: str,
    logs: list[dict], by_id: dict,
) -> None:
    """既有关系行：按需改名。

    有 ``global_role_id`` 时，先改全局角色名（``apply_global_rename`` 会同步该角色
    在**所有产品**下的 ``role_name`` 镜像列，M5），再同步本行内存态；无全局角色
    （历史遗留）时仅改本行镜像列。两者都写一条角色改名审计日志。
    """
    if not p['role_name'] or assoc.role_name == p['role_name']:
        return
    old_name = assoc.role_name
    global_role = by_id.get(assoc.global_role_id) if assoc.global_role_id is not None else None
    if global_role is not None:
        await apply_global_rename(db, global_role, p['role_name'])
    assoc.role_name = p['role_name']
    db.add(ModificationLog(
        target_type='role', target_id=assoc.id, field_name='role_name',
        old_value=old_name, new_value=p['role_name'], modifier_name=username,
    ))
    logs.append({'role_id': assoc.id, 'old_name': old_name, 'new_name': p['role_name']})


async def resolve_role_rows(
    *,
    payload_roles: list,
    existing_product_roles: list,
    db: AsyncSession,
    product_id: int,
    username: str = 'system',
) -> RoleResolution:
    """解析 BOM payload 的角色段，落库关联行并返回 (role_ids, temp_role_map, logs)。"""
    prepared = _prepare_items(payload_roles)
    keys = {p['key'] for p in prepared if p['key']}
    by_key = await _load_global_roles_by_key(db, keys)

    # 预取 payload 显式引用的全局角色（供新建关联行取镜像名）
    gids = {p['global_role_id'] for p in prepared if p['global_role_id'] is not None}
    by_id = {role.id: role for role in by_key.values() if role.id is not None}
    if gids:
        result = await db.execute(select(Role).where(Role.id.in_(gids)))
        for role in result.scalars().all():
            by_id[role.id] = role

    created_globals = _ensure_new_globals(db, prepared, by_key)
    if created_globals:
        await db.flush()
        for role in created_globals:
            by_id[role.id] = role

    existing_by_id = {r.id: r for r in existing_product_roles}
    existing_by_global = {
        r.global_role_id: r for r in existing_product_roles if r.global_role_id is not None
    }

    role_ids: list[int] = []
    temp_role_map: dict[str, int] = {}
    logs: list[dict] = []

    for p in prepared:
        if not p['role_name'] and p['global_role_id'] is None and p['rid'] is None:
            continue  # 无名又无任何引用：跳过
        gid = _resolve_target_global_id(p, existing_by_id, by_key)
        assoc = existing_by_id.get(p['rid']) if p['rid'] is not None else None
        if assoc is None and gid is not None:
            assoc = existing_by_global.get(gid)
        if assoc is not None:
            await _apply_existing_assoc(db, assoc, p, username, logs, by_id)
            role_ids.append(assoc.id)
            if p['role_key']:
                temp_role_map[p['role_key']] = assoc.id
            continue
        new_role = ProductRole(
            product_id=product_id, global_role_id=gid,
            role_name=_assoc_name_for_new(p, gid, by_id),
        )
        db.add(new_role)
        await db.flush()
        role_ids.append(new_role.id)
        existing_by_id[new_role.id] = new_role
        if gid is not None:
            existing_by_global[gid] = new_role
        if p['role_key']:
            temp_role_map[p['role_key']] = new_role.id

    return RoleResolution(role_ids=role_ids, temp_role_map=temp_role_map, logs=logs)
