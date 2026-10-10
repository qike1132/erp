"""BOM 角色解析器（bom_role_resolver）。

把 ``save_bom`` 的角色段解析从 ``bom_service`` 抽出，避免该文件继续膨胀。

**角色为产品私有**（迁移 088/089 起）：解析完全基于 ``product_role`` 本表，
不再涉及全局角色字典。支持三种入参：

- ``id``：**既有**关联行（属于本产品的 ``product_role.id``）；改名时只改本行
  ``role_name`` 并写一条审计日志（**不再**跨产品同步——各 SKU 互相独立）；
- ``role_key``：**新建**角色（客户端临时键），落一条本产品 ``product_role`` 行，
  并映射为真实 id 存入 ``temp_role_map``，供物料行的 ``role_id`` 归属解析；
- 仅名称：按 ``lower(trim(name))`` 在本产品既有行中**同名复用**，否则新建。

唯一性：**同一产品内**角色名（``lower(trim)``）必须唯一，冲突抛 ``BusinessError``（→400）。
DB 侧另有 ``uq_product_role_product_name_lower (product_id, lower(role_name))`` 兜底并发写入。

设计约束：本模块所有函数内**不得**出现「循环体内 ``await execute/scalar/scalars``」
（N+1 静态门禁）。本实现循环体内除 ``db.flush()`` 外无任何查询——既有行由调用方
（``product.roles``）一次性传入。
"""
from __future__ import annotations

import logging
from typing import NamedTuple

from sqlalchemy.ext.asyncio import AsyncSession

from fastapi_app.core.exceptions import BusinessError
from fastapi_app.services.product.role_service import _name_key, _normalize_name
from fastapi_app.shared_models import ModificationLog, ProductRole

logger = logging.getLogger(__name__)


class RoleResolution(NamedTuple):
    """角色段解析结果。"""
    role_ids: list[int]              # 本产品最终保留/新建的关联行 id（用于删除未提交行）
    temp_role_map: dict[str, int]    # 客户端 role_key -> 关联行 id
    logs: list[dict]                 # 审计日志明细（便于可观测/测试）


def _prepare_items(payload_roles: list) -> list[dict]:
    """归一化 payload 角色项，计算名称比较键。

    空/非法名（``_normalize_name`` 抛错）→ 名称置空，后续按「无名即跳过」处理
    （与既有行为一致：前端已做非空校验，此处仅兜底不建角色）。
    """
    prepared: list[dict] = []
    for item in payload_roles or []:
        raw_name = item.get('role_name') or item.get('name') or ''
        try:
            name = _normalize_name(raw_name)
        except BusinessError:
            name = ''
        prepared.append({
            'role_name': name,
            'key': _name_key(name),
            'rid': item.get('id'),
            'role_key': item.get('role_key'),
        })
    return prepared


def _assert_unique_names(prepared: list[dict], existing_by_id: dict) -> None:
    """同一产品内角色名唯一（``lower(trim)``），冲突抛 ``BusinessError``。

    两处冲突都要拦，否则会撞 DB 唯一索引变成 500：
    1. payload 内部重名（含「把 A 改名成已存在的 B」）；
    2. payload 的名字与**未提交**的既有行重名。

    已知取舍（刻意拒绝）：「删除旧角色 + 同轮新建同名角色」也落入第 2 类被拒——
    保存时先建新行、后删旧行，同名会在唯一索引上炸成 500，故宁可在解析期拒绝。
    用户需先保存一次删除、再新建同名角色。
    """
    seen: dict[str, dict] = {}
    submitted_ids = {p['rid'] for p in prepared if p['rid'] is not None}
    for p in prepared:
        if not p['key']:
            continue
        if p['key'] in seen:
            raise BusinessError(
                f'角色名「{p["role_name"]}」在本产品中重复，请改用不同名称'
            )
        seen[p['key']] = p
    for row in existing_by_id.values():
        if row.id in submitted_ids:
            continue
        key = _name_key(row.role_name or '')
        if key and key in seen:
            raise BusinessError(
                f'角色名「{row.role_name}」已存在（或为已删除的同名角色）：'
                '如需重建同名角色，请先保存一次使删除生效，再新建'
            )


async def resolve_role_rows(
    *,
    payload_roles: list,
    existing_product_roles: list,
    db: AsyncSession,
    product_id: int,
    username: str = 'system',
) -> RoleResolution:
    """解析 BOM payload 的角色段，落库 ``product_role`` 行并返回解析结果。"""
    prepared = _prepare_items(payload_roles)
    existing_by_id = {r.id: r for r in existing_product_roles}
    existing_by_key = {
        _name_key(r.role_name or ''): r
        for r in existing_product_roles
        if r.role_name
    }

    _assert_unique_names(prepared, existing_by_id)

    role_ids: list[int] = []
    temp_role_map: dict[str, int] = {}
    logs: list[dict] = []

    for p in prepared:
        if not p['role_name'] and p['rid'] is None:
            continue  # 无名又无引用：跳过
        if p['rid'] is not None:
            assoc = existing_by_id.get(p['rid'])
            if assoc is None:
                # 陈旧 id（客户端提交了不属于该产品的关联行 id）→ 明确 400
                raise BusinessError(f'角色 {p["rid"]} 不属于该产品')
        else:
            # 无 id：本产品同名既有行复用（各 SKU 互相独立，只在本产品内找）
            assoc = existing_by_key.get(p['key'])

        if assoc is not None:
            if p['role_name'] and assoc.role_name != p['role_name']:
                old_name = assoc.role_name
                assoc.role_name = p['role_name']
                db.add(ModificationLog(
                    target_type='role', target_id=assoc.id, field_name='role_name',
                    old_value=old_name, new_value=p['role_name'], modifier_name=username,
                ))
                logs.append({'role_id': assoc.id, 'old_name': old_name, 'new_name': p['role_name']})
            role_ids.append(assoc.id)
            if p['role_key']:
                temp_role_map[p['role_key']] = assoc.id
            continue

        new_role = ProductRole(product_id=product_id, role_name=p['role_name'])
        db.add(new_role)
        await db.flush()
        role_ids.append(new_role.id)
        existing_by_id[new_role.id] = new_role
        existing_by_key[p['key']] = new_role
        if p['role_key']:
            temp_role_map[p['role_key']] = new_role.id

    return RoleResolution(role_ids=role_ids, temp_role_map=temp_role_map, logs=logs)
