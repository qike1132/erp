"""版本域：版本列表/详情、跨版本部位汇总（快照 + 字段级 diff）。

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

from .common import (
    _SNAPSHOT_FIELDS,
    _ensure_project_exists,
    _ensure_role_belongs_to_project,
    _get_primary_role_id,
)


async def list_versions(db: AsyncSession, project_id: int) -> dict:
    """版本列表查询（按 version_no 升序；仅取展示列，避免加载全量快照 JSON）"""
    await _ensure_project_exists(db, project_id)

    result = await db.execute(
        select(
            CustomerSamplingFabricVersion.id,
            CustomerSamplingFabricVersion.version_no,
            CustomerSamplingFabricVersion.created_at,
            CustomerSamplingFabricVersion.reason,
        )
        .where(CustomerSamplingFabricVersion.project_id == project_id)
        .order_by(CustomerSamplingFabricVersion.version_no)
    )
    rows = result.all()
    return {
        'success': True,
        'items': [
            {
                'id': vid,
                'version_no': vno,
                'created_at': created_at.strftime('%Y-%m-%d %H:%M:%S') if created_at else '',
                'reason': reason or '',
            }
            for vid, vno, created_at, reason in rows
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


def _next_version(version_no: str | None) -> str:
    """返回下一个版本号：T1 -> T2、t5 -> T6；无效输入降级为 T1

    由 _version_num 组合而来（板房拆分时从旧 facade 移除，此处恢复为
    可复用纯函数，避免调用方各自内联 f'T{max+1}'）。
    """
    num = _version_num(version_no)
    if num <= 0:
        return 'T1'
    return f'T{num + 1}'



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



def _version_sort_key(version_no: str | None) -> tuple[int, str]:
    """版本号排序键：与 `version_list` 一致，保证「最新版本」判定唯一"""
    v = version_no or ''
    return (len(v), v)


def _pick_final_or_latest_per_part(items: list[dict], final_version: str) -> list[dict]:
    """打印取数：逐部位名称挑一行 —— 有最终版本行取最终版本，否则取最新有数据的版本。

    打样单必须列出该角色已录入的每个部位名称。若整表按
    `version_no == final_version` 过滤，尚未「复制版本」到最终版本的部位
    （行仍停留在更早版本）会整条消失，打印预览的部位名称与页面录入不一致。
    """
    best: dict[str, dict] = {}
    for item in items:
        name = item.get('part_name') or ''
        cur = best.get(name)
        if cur is None:
            best[name] = item
            continue
        # 排序键：(是否最终版本行, 版本号)。最终版本行优先；同为最终/非最终时
        # 取版本号更大者（元组比较在标志相同时才比较版本号，正是所需语义）
        new_rank = (
            item.get('version_no') == final_version,
            _version_sort_key(item.get('version_no')),
        )
        cur_rank = (
            cur.get('version_no') == final_version,
            _version_sort_key(cur.get('version_no')),
        )
        if new_rank > cur_rank:
            best[name] = item
    # 保持首次出现顺序（与 part 表 sort_order 查询顺序一致），避免打样单行序漂移
    picked: list[dict] = []
    seen: set[str] = set()
    for item in items:
        name = item.get('part_name') or ''
        if name in seen:
            continue
        seen.add(name)
        picked.append(best[name])
    return picked


async def get_parts_by_version(
    db: AsyncSession,
    project_id: int,
    *,
    role_id: int | None = None,
    final_only: bool = False,
) -> dict:
    """获取指定角色所有版本的部位布料数据（跨版本二维表数据源）

    数据来源两级合并：
    1. `customer_sampling_part` 表 — 该角色所有版本号实时数据（优先，保证新增/编辑/删除立即可见）
    2. `customer_sampling_fabric_version.snapshot_data` — 该角色历史快照（补充 part 表未覆盖的版本）

    按 part_name → version_no 排序后返回扁平列表。

    Args:
        role_id: 角色ID筛选；未传时自动解析项目的默认角色
        final_only: 打印场景，逐部位名称只返回一行
            （选版规则见 `_pick_final_or_latest_per_part`），且不加载历史版本快照

    Returns:
        {
            'success': True,
            'items': [PartDetail + version_no, ...],
            'versions': ['T1', 'T2', ...],
            'final_version': role.current_version,
    }
    （读路径：项目无角色时返回空数据）
    """
    await _ensure_project_exists(db, project_id)
    if role_id is None:
        role_id = await _get_primary_role_id(db, project_id)
        if role_id is None:
            return {'success': True, 'items': [], 'versions': [], 'final_version': 'T1'}
    else:
        await _ensure_role_belongs_to_project(db, role_id, project_id)

    # 角色当前最终版本（final_only 过滤与返回值共用）
    role_result = await db.execute(
        select(CustomerSamplingRole.current_version).where(CustomerSamplingRole.id == role_id)
    )
    final_version = role_result.scalar_one_or_none() or 'T1'

    # 1. 从 part 表读取该角色所有版本化部件（带 supplier 关联）
    # 注意：final_only 不在此处按版本过滤 —— 版本选择按部位名称逐条进行
    # （见 `_pick_final_or_latest_per_part`），整表过滤会让部位整条消失。
    part_conditions = [
        CustomerSamplingPart.project_id == project_id,
        CustomerSamplingPart.role_id == role_id,
    ]
    parts_result = await db.execute(
        select(CustomerSamplingPart)
        .options(selectinload(CustomerSamplingPart.supplier))
        .where(*part_conditions)
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

    # part 表中仍存在的部位名（不限版本）：快照补充仅为「该部位仍存在、但某版本列
    # 未复制到 part 表」的情况服务；已删除的部位不因历史快照而复活（spec 5.5.1.6 删除级联）
    live_part_names = {p.part_name for p in all_parts}

    for ver in versions:
        if final_only and ver.version_no != final_version:
            continue  # 打印场景：历史版本快照不参与（避免 JSONB 全量读取）
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

    version_list = sorted(version_set, key=_version_sort_key)
    if final_only:
        # 打印场景：逐部位名称收敛为一行（最终版本优先，否则取最新有数据的版本）
        items = _pick_final_or_latest_per_part(items, final_version)

    return {
        'success': True,
        'items': items,
        'versions': version_list,
        'final_version': final_version,
    }

