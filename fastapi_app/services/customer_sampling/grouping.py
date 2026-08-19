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

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import noload, selectinload

from fastapi_app.shared_models import (
    CustomerSamplingChangeLog,
    CustomerSamplingPart,
    CustomerSamplingProject,
)

logger = logging.getLogger(__name__)

# 版本快照中参与 diff 计算的布料业务字段
_SNAPSHOT_FIELDS = (
    'part_name', 'sort_order', 'fabric_name', 'fabric_spec',
    'supplier_id', 'supplier_name', 'contact_person', 'contact_phone',
    'unit_price', 'delivery_days', 'remark',
)

_GROUPED_LIST_MAX_PROJECTS = 2000


from .upload import _batch_get_image_urls

# 列表查询统一 noload 选项：抑制 CustomerSamplingProject 模型默认 lazy='selectin'
# 的级联加载（parts/roles/fabric_versions/change_logs/product_image/creator，
# 含 Role→parts/fabric_versions 二级链）。列表页只输出摘要字段，pattern_maker
# 单独 selectinload（分组与名称兜底需要）。
_LIST_NOLOAD = (
    noload(CustomerSamplingProject.parts),
    noload(CustomerSamplingProject.roles),
    noload(CustomerSamplingProject.fabric_versions),
    noload(CustomerSamplingProject.change_logs),
    noload(CustomerSamplingProject.product_image),
    noload(CustomerSamplingProject.creator),
)


async def get_grouped_list(
    db: AsyncSession,
    *,
    keyword: str | None = None,
    pattern_maker_id: int | None = None,
    status: str | None = None,
    page: int = 1,
    per_page: int = 20,
) -> dict:
    """按版师分组聚合查询打样项目列表（分页）

    - 未关联版师的项目归入"未分类"分组
    - 分组间按组内最新 updated_at 倒序，"未分类"始终最后
    - 组内项目按 updated_at 倒序
    - status 缺省（None）时默认仅返回"进行中"项目（前端漏传状态时的兜底）
    - 显式传 'all' 返回全部状态的项目；传 in_progress/completed/cancelled 按对应状态过滤
    - page/per_page 控制分页，对全部项目全局分页后再按版师分组

    Returns:
        GroupedListResponse dict
    """
    # status 缺省时默认按"进行中"过滤（兜底），显式传 'all' 可返回全部状态
    if status is None:
        status = 'in_progress'

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
    if pattern_maker_id is not None:
        conditions.append(CustomerSamplingProject.pattern_maker_id == pattern_maker_id)
    if status != 'all':
        conditions.append(CustomerSamplingProject.status == status)

    # 计算总数
    count_query = select(func.count()).select_from(CustomerSamplingProject)
    for cond in conditions:
        count_query = count_query.where(cond)
    total = (await db.execute(count_query)).scalar_one()

    # 分页
    pages = max(1, (total + per_page - 1) // per_page)
    page = max(1, min(page, pages))

    # 查询当前页项目（含版师关联，避免 N+1）
    query = select(CustomerSamplingProject).options(
        selectinload(CustomerSamplingProject.pattern_maker),
        *_LIST_NOLOAD,
    )
    for cond in conditions:
        query = query.where(cond)
    query = query.order_by(CustomerSamplingProject.updated_at.desc()).offset((page - 1) * per_page).limit(per_page)

    result = await db.execute(query)
    projects = result.scalars().all()

    # 批量预取产品图片 URL（单次 SQL，消除逐项目查询的 N+1）
    image_url_map = await _batch_get_image_urls(
        db, [p.product_image_file_id for p in projects if p.product_image_file_id]
    )
    summary_map = {p.id: _project_to_summary(p, image_url_map) for p in projects}

    # 应用层按 pattern_maker_id 分组
    groups_map: dict[int | None, list[CustomerSamplingProject]] = {}
    for p in projects:
        key = p.pattern_maker_id
        groups_map.setdefault(key, []).append(p)

    # 构建分组响应
    groups = []
    for pmid, proj_list in groups_map.items():
        if pmid is None:
            # "未分类"分组最后处理
            continue
        # 获取版师姓名（优先用冗余字段，降级用关联查询）
        pattern_maker_name = proj_list[0].pattern_maker_name or ''
        if not pattern_maker_name and proj_list[0].pattern_maker:
            pattern_maker_name = proj_list[0].pattern_maker.name
        latest_update = max(p.updated_at for p in proj_list)
        groups.append({
            'pattern_maker_id': pmid,
            'pattern_maker_name': pattern_maker_name or '未命名版师',
            'project_count': len(proj_list),
            'latest_update_time': latest_update.strftime('%Y-%m-%d %H:%M:%S') if latest_update else '',
            'projects': [summary_map[p.id] for p in proj_list],
        })

    # 分组间按组内最新更新时间倒序
    groups.sort(key=lambda g: g['latest_update_time'], reverse=True)

    # "未分类"分组始终最后
    unclassified = groups_map.get(None, [])
    if unclassified:
        latest_update = max(p.updated_at for p in unclassified)
        groups.append({
            'pattern_maker_id': None,
            'pattern_maker_name': '未分类',
            'project_count': len(unclassified),
            'latest_update_time': latest_update.strftime('%Y-%m-%d %H:%M:%S') if latest_update else '',
            'projects': [summary_map[p.id] for p in unclassified],
        })

    return {
        'success': True,
        'groups': groups,
        'total_projects': len(projects),
        'total': total,
        'pages': pages,
        'current_page': page,
    }



def _project_to_summary(project: CustomerSamplingProject, image_url_map: dict[int, dict]) -> dict:
    """将项目 ORM 对象转为 ProjectSummary dict（纯函数，图片 URL 由批量映射提供）"""
    image_info = (
        image_url_map.get(project.product_image_file_id)
        if project.product_image_file_id else None
    )
    return {
        'id': project.id,
        'sequence_no': project.sequence_no,
        'product_name': project.product_name,
        'product_image_url': image_info.get('url') if image_info else None,
        'product_image_thumbnail_url': image_info.get('thumbnail_url') if image_info else None,
        'product_image_blur_url': image_info.get('blur_url') if image_info else None,
        'current_version': project.current_version,
        'status': project.status,
        'completed_at': project.completed_at.strftime('%Y-%m-%d %H:%M:%S') if project.completed_at else None,
        # 列表查询已 noload(parts)（访问会触发 async lazy load 报错），恒为 0；
        # 详情页 parts 数量由 get_project_detail / get_completed_table 单独统计
        'parts_count': 0,
        'updated_at': project.updated_at.strftime('%Y-%m-%d %H:%M:%S') if project.updated_at else '',
    }



async def get_completed_table(
    db: AsyncSession,
    *,
    keyword: str | None = None,
    pattern_maker_id: int | None = None,
    page: int = 1,
    per_page: int = 20,
) -> dict:
    """查询已完成打样项目表格数据（含部位数量统计与操作人）

    返回按 updated_at 倒序的已完成项目列表（分页），每行含：
    - 项目基本信息（id, sequence_no, product_name, pattern_maker_name）
    - completed_at（完成时间）
    - parts_count（该项目所有角色的部位总数）
    - operator_name（最近一次标记为完成的操作人）

    Args:
        keyword: 关键词（序列号/产品名 ILIKE）
        pattern_maker_id: 版师 ID 筛选
        page: 页码（从 1 开始）
        per_page: 每页条数
    """
    # 构建查询条件
    conditions = [CustomerSamplingProject.status == 'completed']
    if keyword:
        like = f'%{keyword}%'
        conditions.append(
            or_(
                CustomerSamplingProject.sequence_no.ilike(like),
                CustomerSamplingProject.product_name.ilike(like),
            )
        )
    if pattern_maker_id is not None:
        conditions.append(CustomerSamplingProject.pattern_maker_id == pattern_maker_id)

    # 统计总条数（用于分页）
    count_query = select(func.count()).select_from(CustomerSamplingProject).where(*conditions)
    total = (await db.execute(count_query)).scalar_one()
    if total == 0:
        return {'success': True, 'items': [], 'total': 0, 'pages': 0, 'current_page': page}

    # 查询项目（含版师关联），按页码分页
    # 同 get_grouped_list：noload 抑制无关 relationship 的级联 selectin 加载
    query = (
        select(CustomerSamplingProject)
        .options(selectinload(CustomerSamplingProject.pattern_maker), *_LIST_NOLOAD)
        .where(*conditions)
        .order_by(CustomerSamplingProject.updated_at.desc())
        .offset((page - 1) * per_page)
        .limit(per_page)
    )
    result = await db.execute(query)
    projects = result.scalars().all()
    pages = (total + per_page - 1) // per_page

    # 统计部位数量：按 project_id 聚合 count
    project_ids = [p.id for p in projects]
    parts_count_query = (
        select(CustomerSamplingPart.project_id, func.count().label('cnt'))
        .where(CustomerSamplingPart.project_id.in_(project_ids))
        .group_by(CustomerSamplingPart.project_id)
    )
    parts_result = await db.execute(parts_count_query)
    parts_count_map = {row.project_id: row.cnt for row in parts_result}

    # 查询操作人：取每个项目最近一次状态更新（update_project_status）的操作人
    # 已完成项目最近一次状态更新通常即标记完成操作，符合报表口径
    operator_query = (
        select(CustomerSamplingChangeLog.project_id, CustomerSamplingChangeLog.operator_name)
        .where(
            CustomerSamplingChangeLog.project_id.in_(project_ids),
            CustomerSamplingChangeLog.action == 'update_project_status',
        )
        .order_by(CustomerSamplingChangeLog.created_at.desc())
    )
    op_result = await db.execute(operator_query)
    operator_map: dict[int, str] = {}
    for row in op_result:
        if row.project_id not in operator_map:
            operator_map[row.project_id] = row.operator_name or ''

    # 构建响应
    items = []
    for p in projects:
        pattern_maker_name = (p.pattern_maker_name or
                              (p.pattern_maker.name if p.pattern_maker else ''))
        items.append({
            'id': p.id,
            'sequence_no': p.sequence_no,
            'product_name': p.product_name,
            'pattern_maker_name': pattern_maker_name,
            'completed_at': p.completed_at.strftime('%Y-%m-%d %H:%M:%S') if p.completed_at else None,
            'parts_count': parts_count_map.get(p.id, 0),
            'operator_name': operator_map.get(p.id, ''),
            'status': 'completed',
        })

    return {
        'success': True,
        'items': items,
        'total': total,
        'pages': pages,
        'current_page': page,
    }
