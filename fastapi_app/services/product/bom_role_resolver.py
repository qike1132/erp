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
    hidden_role_id: int | None = None  # 归一化后唯一的隐藏款角色 id（未提交该字段时原样保留）


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
            'is_hidden': bool(item.get('is_hidden')),
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
    # 隐藏款归一化只在该字段**真正被提交**时执行：旧客户端/其他调用方
    # 不传 is_hidden 时不得清掉已保存的标记。
    # 判定口径必须是「非 None」而不是「键存在」：RoleItem.is_hidden 是三态，
    # 端点用 model_dump() 序列化后键恒在（未提交时为 None），用键存在判断会让
    # 旧客户端的保存也走归一化分支、清掉已保存的标记（OCR 评审 H1）。
    hidden_field_submitted = any(
        (item or {}).get('is_hidden') is not None for item in payload_roles or []
    )
    resolved_hidden_candidates: list[tuple[bool, int]] = []

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
            resolved_hidden_candidates.append((p['is_hidden'], assoc.id))
            if p['role_key']:
                temp_role_map[p['role_key']] = assoc.id
            continue

        new_role = ProductRole(product_id=product_id, role_name=p['role_name'])
        db.add(new_role)
        await db.flush()
        role_ids.append(new_role.id)
        resolved_hidden_candidates.append((p['is_hidden'], new_role.id))
        existing_by_id[new_role.id] = new_role
        existing_by_key[p['key']] = new_role
        if p['role_key']:
            temp_role_map[p['role_key']] = new_role.id

    hidden_role_id = await _normalize_hidden_flags(
        db, existing_by_id, resolved_hidden_candidates, logs, username,
        submitted=hidden_field_submitted,
    )
    return RoleResolution(
        role_ids=role_ids, temp_role_map=temp_role_map, logs=logs,
        hidden_role_id=hidden_role_id,
    )


async def _normalize_hidden_flags(
    db: AsyncSession,
    roles_by_id: dict,
    candidates: list[tuple[bool, int]],
    logs: list[dict],
    username: str,
    *,
    submitted: bool,
) -> int | None:
    """把「每产品至多一个隐藏款」落到本产品角色行（重复指定 = 后者覆盖前者）。

    ``submitted=False``（payload 完全没带 ``is_hidden``）时**原样返回当前标记**，
    不写任何行——旧客户端保存 BOM 不得清掉用户已指定的隐藏款。

    两次 flush 是有意为之：先把所有行置 false 并落库，再把目标置 true，
    避免部分唯一索引（``uq_product_role_hidden_per_product``）在中间态
    同时看到两个 true 而报唯一冲突。
    """
    if not submitted:
        current = next(
            (rid for rid, role in roles_by_id.items()
             if getattr(role, 'is_hidden', False) is True),
            None,
        )
        return current

    target_id = None
    for wanted, rid in candidates:  # 顺序遍历：最后一个 true 生效
        if wanted:
            target_id = rid

    changed = False
    for rid, role in roles_by_id.items():
        if getattr(role, 'is_hidden', False) is True and rid != target_id:
            role.is_hidden = False
            changed = True
            db.add(ModificationLog(
                target_type='role', target_id=rid, field_name='is_hidden',
                old_value='true', new_value='false', modifier_name=username,
            ))
            logs.append({'role_id': rid, 'old_hidden': True, 'new_hidden': False})
    if changed:
        await db.flush()

    if target_id is not None:
        target = roles_by_id.get(target_id)
        if target is not None and getattr(target, 'is_hidden', False) is not True:
            target.is_hidden = True
            db.add(ModificationLog(
                target_type='role', target_id=target_id, field_name='is_hidden',
                old_value='false', new_value='true', modifier_name=username,
            ))
            logs.append({'role_id': target_id, 'old_hidden': False, 'new_hidden': True})
            await db.flush()
    return target_id
