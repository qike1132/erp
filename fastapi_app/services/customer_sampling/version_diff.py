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
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from fastapi_app.core.exceptions import NotFoundError
from fastapi_app.shared_models import (
    CustomerSamplingChangeLog,
    CustomerSamplingFabricVersion,
    CustomerSamplingPart,
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
    _ensure_project_exists,
    _ensure_role_belongs_to_project,
    _get_default_role_id,
    _get_user_name,
    _write_change_log,
)


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



def _version_num(version_no: str | None) -> int:
    """解析版本号数值部分：T1 -> 1，解析失败返回 0"""
    try:
        return int((version_no or '').lstrip('Tt'))
    except (ValueError, AttributeError):
        return 0



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

    # part 表中仍存在的部位名：快照补充仅为「该部位仍存在、但某版本列未复制到
    # part 表」的情况服务；已删除的部位不因历史快照而复活（spec 5.5.1.6 删除级联）
    live_part_names = {p.part_name for p in all_parts}

    for ver in versions:
        version_set.add(ver.version_no)
        snapshot: list[dict] = ver.snapshot_data or []
        for part in snapshot:
            key = (part.get('part_name', ''), ver.version_no)
            if key in seen_keys:
                continue  # part 表已有此版本数据，跳过快照
            if part.get('part_name', '') not in live_part_names:
                continue  # 部位已从 part 表删除，快照不复活
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



def _next_version(current: str) -> str:
    """T1 -> T2, T2 -> T3, ..."""
    n = _version_num(current)
    return f'T{n + 1}' if n else 'T1'



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
