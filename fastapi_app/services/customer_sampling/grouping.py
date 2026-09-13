"""分组聚合查询：按版师分组的打样项目列表、分组分页与项目摘要构建。

对应需求规格：.codeartsdoer/specs/customer_sampling/spec.md
"""
from __future__ import annotations

import logging
from datetime import datetime

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import noload, selectinload

from fastapi_app.shared_models import (
    CustomerSamplingProject,
)

logger = logging.getLogger(__name__)

_GROUPED_LIST_MAX_PROJECTS = 5000


from .upload import _batch_get_image_urls

# 列表查询统一 noload 选项：抑制 CustomerSamplingProject 模型 relationship 的
# 惰性加载（parts/roles/fabric_versions/change_logs/product_image/creator，
# 含 Role→parts/fabric_versions 二级链；async 会话下未预加载即访问会抛错）。
# 列表页只输出摘要字段，pattern_maker 单独 selectinload（分组与名称兜底需要）。
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
    - page/per_page 按"分组"分页（每页返回完整分组，组内项目不拆分）：
      先对全部匹配项目按版师全量分组，再对分组列表分页

    Returns:
        GroupedListResponse dict
    """
    # status 缺省时默认按"进行中"过滤（兜底），显式传 'all' 可返回全部状态
    if status is None:
        status = 'in_progress'

    # 构建查询条件
    conditions = []
    if keyword:
        # 关键词作为绑定参数，通配符由 SQL 侧 concat 拼接（不在 Python 侧拼 SQL 片段）
        kw_pattern = func.concat('%', keyword, '%')
        conditions.append(
            or_(
                CustomerSamplingProject.sequence_no.ilike(kw_pattern),
                CustomerSamplingProject.product_name.ilike(kw_pattern),
            )
        )
    if pattern_maker_id is not None:
        conditions.append(CustomerSamplingProject.pattern_maker_id == pattern_maker_id)
    if status != 'all':
        conditions.append(CustomerSamplingProject.status == status)

    # 统计符合筛选条件的项目总数（供前端展示统计信息）
    count_query = select(func.count()).select_from(CustomerSamplingProject)
    for cond in conditions:
        count_query = count_query.where(cond)
    total_projects = (await db.execute(count_query)).scalar_one()

    # 两段式查询：先仅取分组/排序所需轻量列（id/pattern_maker_id/updated_at）做全量分组
    # 与分组级分页，再只对当前页分组的项目取完整明细（避免全量实例化 ORM + 全量图片查询）
    light_result = await db.execute(
        select(
            CustomerSamplingProject.id,
            CustomerSamplingProject.pattern_maker_id,
            CustomerSamplingProject.updated_at,
        )
        .where(*conditions)
        .order_by(CustomerSamplingProject.updated_at.desc())
        .limit(_GROUPED_LIST_MAX_PROJECTS)
    )
    light_rows = light_result.all()

    # 命中上限截断时告警，便于定位分组统计与项目总数不一致的问题
    if len(light_rows) < total_projects:
        logger.warning(
            "Grouped list truncated: total_projects=%s, loaded=%s, max_limit=%s",
            total_projects, len(light_rows), _GROUPED_LIST_MAX_PROJECTS,
        )

    # 应用层按 pattern_maker_id 全量分组（同一版师的项目不再被分页拆散），
    # 组内保持 updated_at 倒序（轻量查询的返回顺序）
    groups_map: dict[int | None, list[int]] = {}
    latest_map: dict[int | None, datetime] = {}
    for pid, pmid, updated_at in light_rows:
        groups_map.setdefault(pmid, []).append(pid)
        prev = latest_map.get(pmid)
        if prev is None or (updated_at is not None and updated_at > prev):
            latest_map[pmid] = updated_at

    # 分组间按组内最新更新时间倒序（datetime 比较；"未分类"分组最后单独追加）
    all_groups_meta = [
        {'pattern_maker_id': pmid, 'latest': latest_map[pmid], 'project_ids': pid_list}
        for pmid, pid_list in groups_map.items()
        if pmid is not None
    ]
    all_groups_meta.sort(key=lambda g: g['latest'], reverse=True)

    unclassified_ids = groups_map.get(None, [])
    if unclassified_ids:
        all_groups_meta.append({
            'pattern_maker_id': None,
            'latest': latest_map.get(None),
            'project_ids': unclassified_ids,
        })

    # 分组级分页：分页单位是"版师分组"而非项目，保证每个分组完整、不跨页拆散
    total_groups = len(all_groups_meta)
    pages = max(1, (total_groups + per_page - 1) // per_page)
    page = max(1, min(page, pages))
    start = (page - 1) * per_page
    page_meta = all_groups_meta[start:start + per_page]

    # 仅对当前页分组的项目取完整明细（含版师关联），构建摘要与图片 URL
    page_ids: list[int] = []
    for meta in page_meta:
        page_ids.extend(meta['project_ids'])
    by_id: dict[int, CustomerSamplingProject] = {}
    if page_ids:
        heavy_conditions = [CustomerSamplingProject.id.in_(page_ids)]
        heavy_result = await db.execute(
            select(CustomerSamplingProject)
            .options(selectinload(CustomerSamplingProject.pattern_maker), *_LIST_NOLOAD)
            .where(*heavy_conditions)
        )
        for p in heavy_result.scalars().all():
            by_id[p.id] = p

    image_url_map = await _batch_get_image_urls(
        db, [p.product_image_file_id for p in by_id.values() if p.product_image_file_id]
    )
    summary_map = {pid: _project_to_summary(p, image_url_map) for pid, p in by_id.items()}

    groups = []
    for meta in page_meta:
        proj_list = [by_id[pid] for pid in meta['project_ids'] if pid in by_id]
        first = proj_list[0] if proj_list else None
        # 获取版师姓名（优先用冗余字段，降级用关联查询）
        pattern_maker_name = (first.pattern_maker_name or '') if first else ''
        if not pattern_maker_name and first is not None and first.pattern_maker:
            pattern_maker_name = first.pattern_maker.name
        latest = meta['latest']
        groups.append({
            'pattern_maker_id': meta['pattern_maker_id'],
            'pattern_maker_name': pattern_maker_name or ('未分类' if meta['pattern_maker_id'] is None else '未命名版师'),
            'project_count': len(proj_list),
            'latest_update_time': latest.strftime('%Y-%m-%d %H:%M:%S') if latest else '',
            'projects': [summary_map[pid] for pid in meta['project_ids'] if pid in summary_map],
        })

    return {
        'success': True,
        'groups': groups,
        'total_projects': total_projects,
        'total': total_groups,
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
        # 详情页 parts 数量由 get_project_detail 单独统计
        'parts_count': 0,
        'updated_at': project.updated_at.strftime('%Y-%m-%d %H:%M:%S') if project.updated_at else '',
    }
