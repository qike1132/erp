"""打样项目 CRUD（创建/更新/删除/状态/详情/列表）

自 crud.py 拆分（批次2-3），函数原文零改动。"""
# ruff: noqa: F401 - 拆分过渡期沿用完整导入块
from __future__ import annotations

import logging
from datetime import UTC, datetime
from enum import Enum

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import noload, selectinload

from fastapi_app.core.exceptions import ConflictError, NotFoundError
from fastapi_app.services.numbering import generate_customer_sampling_number
from fastapi_app.shared_models import (
    CustomerSamplingFabricVersion,
    CustomerSamplingPart,
    CustomerSamplingProject,
    CustomerSamplingRole,
)

logger = logging.getLogger(__name__)

class _UnsetType(Enum):
    """"未传参"哨兵类型（枚举字面量便于类型收窄）。

    成员名用 MARKER 而非 TOKEN：原名 TOKEN 会触发 bandit 的 S105「硬编码口令」
    误报（值是 'unset'，与凭据无关），且名字本身也容易误读成认证令牌。
    """

    MARKER = 'unset'


# 可空字段的"未传参"哨兵：区分「显式传 null = 清空」与「未传 = 不修改」。
# 仅 update_project 签名内部使用，调用方经 endpoint 的 model_fields_set 判定后传参。
_UNSET = _UnsetType.MARKER

from .common import (
    _ensure_part_name_unique,
    _ensure_project_exists,
    _ensure_role_belongs_to_project,
    _escape_like,
    _get_primary_role_id,
    _get_user_name,
    _resolve_pattern_maker_name,
    _resolve_supplier_name,
    _write_change_log,
)
from .grouping import _project_to_summary
from .upload import _batch_get_image_urls, _get_product_image_urls, _register_project_image_cleanup
from .version_diff import _version_num


async def create_project(
    db: AsyncSession,
    *,
    product_name: str,
    pattern_maker_id: int | None = None,
    remark: str | None = None,
    initial_roles: list[str] | None = None,
    user_id: int | None = None,
) -> dict:
    """新增打样项目

    - 自动生成序列号 CS-YYYYMMDD-XXXX
    - 角色：传入 initial_roles 时按用户指定创建（去重、去空白），
      未传入时才创建一个名为「默认」的兜底角色
    - 自动创建 T1 基线版本挂在首个角色下（snapshot_data=[], change_summary=null）
    - 校验 pattern_maker_id 存在性，冗余存储 pattern_maker_name
    """
    # 校验版师存在性
    pattern_maker_name = ''
    if pattern_maker_id is not None:
        pattern_maker_name = await _resolve_pattern_maker_name(db, pattern_maker_id)
        if not pattern_maker_name:
            raise NotFoundError('所选版师不存在')

    # 生成序列号
    sequence_no = await generate_customer_sampling_number(db)

    # 创建项目
    project = CustomerSamplingProject(
        sequence_no=sequence_no,
        product_name=product_name,
        pattern_maker_id=pattern_maker_id,
        pattern_maker_name=pattern_maker_name,
        remark=remark,
        created_by=user_id,
    )
    db.add(project)
    await db.flush()

    # 创建角色：填了自定义角色名就只建这些（不额外插「默认」），否则建一个「默认」角色
    roles = await _create_project_roles(db, project.id, initial_roles)
    first_role = roles[0]

    # 自动创建 T1 基线版本挂在首个角色下（快照初始为空数组）
    t1_version = CustomerSamplingFabricVersion(
        project_id=project.id,
        role_id=first_role.id,
        version_no='T1',
        snapshot_data=[],
        change_summary=None,
        reason='T1 基线版本（自动创建）',
        created_by=user_id,
    )
    db.add(t1_version)
    await db.flush()

    # 写审计日志
    operator_name = await _get_user_name(db, user_id)
    await _write_change_log(
        db, project.id, 'create_project', user_id, operator_name,
        target_version='T1',
    )

    logger.info(
        '创建打样项目: id=%s, sequence_no=%s, roles_count=%d',
        project.id, sequence_no, len(roles),
    )
    return {'id': project.id, 'sequence_no': sequence_no}

async def _create_project_roles(
    db: AsyncSession,
    project_id: int,
    initial_roles: list[str] | None,
) -> list[CustomerSamplingRole]:
    """创建项目角色，返回按创建顺序排列的角色列表

    - initial_roles 去重、去空白后作为自定义角色（逐个 is_default=false），
      不再额外创建「默认」角色
    - 未传 initial_roles 时创建名为「默认」的角色
    - 所有角色一律可删除，不存在不可删的兜底角色
    抽为独立函数以控制 create_project 长度（质量门禁：单函数 ≤80 行）。
    """
    # 去重、去空白后的用户指定角色名
    custom_role_names: list[str] = []
    seen: set[str] = set()
    if initial_roles:
        for name in initial_roles:
            n = (name or '').strip()
            if n and n not in seen:
                seen.add(n)
                custom_role_names.append(n)

    roles: list[CustomerSamplingRole] = []
    if custom_role_names:
        for idx, role_name in enumerate(custom_role_names):
            role = CustomerSamplingRole(
                project_id=project_id,
                role_name=role_name,
                sort_order=idx,
                is_default=False,
                current_version='T1',
            )
            db.add(role)
            await db.flush()
            roles.append(role)
    else:
        default_role = CustomerSamplingRole(
            project_id=project_id,
            role_name='默认',
            sort_order=0,
            is_default=True,
            current_version='T1',
        )
        db.add(default_role)
        await db.flush()
        roles.append(default_role)
    return roles

async def _sync_primary_role_current_version(
    db: AsyncSession,
    project_id: int,
    current_version: str,
) -> None:
    """同步基准角色的 current_version（保持向后兼容）

    旧端点仍调 update_project 设置最终版本时，基准角色（首个角色）同步生效；
    项目已无角色时跳过。抽为独立函数以控制 update_project 长度（质量门禁：单函数 ≤80 行）。
    """
    primary_role_id = await _get_primary_role_id(db, project_id)
    if primary_role_id is None:
        return
    primary_role = (await db.execute(
        select(CustomerSamplingRole).where(CustomerSamplingRole.id == primary_role_id)
    )).scalar_one_or_none()
    if primary_role is not None and primary_role.current_version != current_version:
        primary_role.current_version = current_version


async def update_project(
    db: AsyncSession,
    project_id: int,
    *,
    product_name: str | None = None,
    pattern_maker_id: int | _UnsetType | None = _UNSET,
    remark: str | None = None,
    product_image_file_id: int | _UnsetType | None = _UNSET,
    current_version: str | None = None,
    version: int,
    user_id: int | None = None,
) -> dict:
    """编辑打样项目

    - 乐观锁校验（version 不匹配抛 ConflictError 409，SELECT ... FOR UPDATE 行锁防并发丢失更新）
    - 可修改：product_name、pattern_maker_id、pattern_maker_name、remark、product_image_file_id
    - pattern_maker_id / product_image_file_id 为三态语义：
      缺省（_UNSET）= 不修改；显式传 None = 清空；传值 = 设置
    - 序列号与历史版本快照不可修改
    - 返回更新后的乐观锁版本号，供前端局部回写
    """
    result = await db.execute(
        select(CustomerSamplingProject)
        .where(CustomerSamplingProject.id == project_id)
        .with_for_update()
    )
    project = result.scalar_one_or_none()
    if project is None:
        raise NotFoundError('打样项目不存在')

    # 乐观锁校验
    if project.version != version:
        raise ConflictError('该打样项目已被他人更新，请刷新后重试')

    # 收集字段变更用于审计
    field_diffs: list[dict[str, object]] = []
    old_image_file_id = project.product_image_file_id

    if product_name is not None and product_name != project.product_name:
        field_diffs.append({'field': 'product_name', 'old': project.product_name, 'new': product_name})
        project.product_name = product_name

    if pattern_maker_id is not _UNSET and pattern_maker_id != project.pattern_maker_id:
        if pattern_maker_id is None:
            # 显式传 null：清除版师关联
            field_diffs.append({'field': 'pattern_maker_id', 'old': project.pattern_maker_id, 'new': None})
            field_diffs.append({'field': 'pattern_maker_name', 'old': project.pattern_maker_name, 'new': ''})
            project.pattern_maker_id = None
            project.pattern_maker_name = ''
        else:
            # 传新值：校验新版师存在性
            new_pattern_maker_name = await _resolve_pattern_maker_name(db, pattern_maker_id)
            if not new_pattern_maker_name:
                raise NotFoundError('所选版师不存在')
            field_diffs.append({'field': 'pattern_maker_id', 'old': project.pattern_maker_id, 'new': pattern_maker_id})
            field_diffs.append({'field': 'pattern_maker_name', 'old': project.pattern_maker_name, 'new': new_pattern_maker_name})
            project.pattern_maker_id = pattern_maker_id
            project.pattern_maker_name = new_pattern_maker_name

    if remark is not None and remark != (project.remark or ''):
        field_diffs.append({'field': 'remark', 'old': project.remark, 'new': remark})
        project.remark = remark

    if product_image_file_id is not _UNSET and product_image_file_id != project.product_image_file_id:
        # 显式传 null = 清除图片；传值 = 替换图片（旧图统一走下方清理）
        field_diffs.append({'field': 'product_image_file_id', 'old': project.product_image_file_id, 'new': product_image_file_id})
        project.product_image_file_id = product_image_file_id

    if current_version is not None and current_version != project.current_version:
        field_diffs.append({'field': 'current_version', 'old': project.current_version, 'new': current_version})
        project.current_version = current_version
        # 同步更新基准角色的 current_version（保持向后兼容）
        await _sync_primary_role_current_version(db, project_id, current_version)

    # 乐观锁 +1
    project.version += 1
    await db.flush()

    # 旧图片不再被引用时清理（FileRecord 行事务内删除，存储对象 commit 后删除）
    if old_image_file_id is not None and old_image_file_id != project.product_image_file_id:
        await _register_project_image_cleanup(db, old_image_file_id)

    # 写审计日志
    operator_name = await _get_user_name(db, user_id)
    await _write_change_log(
        db, project.id, 'update_project', user_id, operator_name,
        field_diffs=field_diffs,
    )

    logger.info('编辑打样项目: id=%s, field_diffs=%s', project_id, field_diffs)
    return {'id': project.id, 'version': project.version}

async def delete_project(
    db: AsyncSession,
    project_id: int,
    *,
    user_id: int | None = None,
) -> dict:
    """删除打样项目

    - 先写审计日志（确保删除操作可追溯；因 project_id 外键 SET NULL，
      日志中冗余记录 sequence_no/product_name，删除后仍可辨识被删项目）
    - ORM cascade 级联删除部位/版本
    - 变更日志不级联删除：project_id 外键 SET NULL，日志保留可追溯
    - 产品图片文件随项目删除一并清理（不再有引用时）
    """
    result = await db.execute(
        select(CustomerSamplingProject).where(CustomerSamplingProject.id == project_id)
    )
    project = result.scalar_one_or_none()
    if project is None:
        raise NotFoundError('打样项目不存在')

    image_file_id = project.product_image_file_id

    # 先写审计日志（在级联删除前，含被删项目标识信息）
    operator_name = await _get_user_name(db, user_id)
    await _write_change_log(
        db, project_id, 'delete_project', user_id, operator_name,
        field_diffs=[
            {'field': 'sequence_no', 'old': project.sequence_no, 'new': None},
            {'field': 'product_name', 'old': project.product_name, 'new': None},
        ],
    )
    await db.flush()

    # 级联删除（ORM cascade='all, delete-orphan'）
    # 注：change_logs relationship 已去掉 cascade，日志不级联删除（project_id SET NULL）
    await db.delete(project)
    await db.flush()

    # 产品图片不再被引用时清理（FileRecord 行事务内删除，存储对象 commit 后删除）
    if image_file_id is not None:
        await _register_project_image_cleanup(db, image_file_id)

    logger.info('删除打样项目: id=%s', project_id)
    return {'id': project_id}

async def update_project_status(
    db: AsyncSession,
    project_id: int,
    *,
    status: str,
    user_id: int | None = None,
) -> dict:
    """更新打样项目状态（in_progress / completed / cancelled）

    - 不参与乐观锁（独立的状态标记操作，最后写入为准）
    - 写审计日志
    """
    result = await db.execute(
        select(CustomerSamplingProject).where(CustomerSamplingProject.id == project_id)
    )
    project = result.scalar_one_or_none()
    if project is None:
        raise NotFoundError('打样项目不存在')

    old_status = project.status
    project.status = status
    # 标记完成时记录完成时间；取消完成/改为进行中时清空
    if status == 'completed' and old_status != 'completed':
        project.completed_at = datetime.now(UTC)
    elif status != 'completed':
        project.completed_at = None
    await db.flush()

    # 写审计日志
    operator_name = await _get_user_name(db, user_id)
    await _write_change_log(
        db, project.id, 'update_project_status', user_id, operator_name,
        field_diffs=[{'field': 'status', 'old': old_status, 'new': status}],
    )

    logger.info('更新打样项目状态: id=%s, %s → %s', project_id, old_status, status)
    return {'id': project.id}

async def get_project_detail(db: AsyncSession, project_id: int) -> dict:
    """查询打样项目详情（含部位布料 + 版本列表）

    - 部位按 sort_order 升序
    - 版本按 version_no 升序
    - 拼接 product_image_url
    """
    result = await db.execute(
        select(CustomerSamplingProject)
        .options(
            selectinload(CustomerSamplingProject.parts).selectinload(CustomerSamplingPart.supplier),
            selectinload(CustomerSamplingProject.creator),
            selectinload(CustomerSamplingProject.roles),
        )
        .where(CustomerSamplingProject.id == project_id)
    )
    project = result.scalar_one_or_none()
    if project is None:
        raise NotFoundError('打样项目不存在')

    image_info = await _get_product_image_urls(db, project.product_image_file_id)

    # 版本列表仅取展示列（id/version_no/created_at/reason），
    # 避免为三个展示字段加载全部版本的 snapshot_data/change_summary JSON
    versions_result = await db.execute(
        select(
            CustomerSamplingFabricVersion.id,
            CustomerSamplingFabricVersion.version_no,
            CustomerSamplingFabricVersion.created_at,
            CustomerSamplingFabricVersion.reason,
        )
        .where(CustomerSamplingFabricVersion.project_id == project_id)
        .order_by(CustomerSamplingFabricVersion.version_no)
    )
    version_rows = versions_result.all()

    # 部位按 sort_order 升序（relationship 已配置 order_by，但显式排序更安全）
    parts_sorted = sorted(project.parts or [], key=lambda p: p.sort_order)
    # 角色按 sort_order 升序
    roles_sorted = sorted(project.roles or [], key=lambda r: r.sort_order)

    return {
        'id': project.id,
        'sequence_no': project.sequence_no,
        'product_name': project.product_name,
        'product_image_url': image_info.get('url') if image_info else None,
        'product_image_thumbnail_url': image_info.get('thumbnail_url') if image_info else None,
        'product_image_blur_url': image_info.get('blur_url') if image_info else None,
        'product_image_file_id': project.product_image_file_id,
        'pattern_maker_id': project.pattern_maker_id,
        'pattern_maker_name': project.pattern_maker_name or '',
        'current_version': project.current_version,
        'status': project.status,
        'remark': project.remark or '',
        'created_by_name': project.creator.username if project.creator else None,
        'created_at': project.created_at.strftime('%Y-%m-%d %H:%M:%S') if project.created_at else '',
        'updated_at': project.updated_at.strftime('%Y-%m-%d %H:%M:%S') if project.updated_at else '',
        'version': project.version,
        'parts': [p.to_dict() for p in parts_sorted],
        'versions': [
            {
                'id': vid,
                'version_no': vno,
                'created_at': created_at.strftime('%Y-%m-%d %H:%M:%S') if created_at else '',
                'reason': reason or '',
            }
            for vid, vno, created_at, reason in version_rows
        ],
        'roles': [r.to_dict() for r in roles_sorted],
    }

async def list_projects(
    db: AsyncSession,
    *,
    page: int = 1,
    per_page: int = 20,
    keyword: str | None = None,
    pattern_maker_id: int | None = None,
    status: str | None = None,
) -> dict:
    """分页查询打样项目列表

    keyword 匹配序列号与产品名称（ILIKE），pattern_maker_id 筛选版师。
    status 缺省（None）时默认仅返回"进行中"项目（与 grouped-list 一致，前端漏传状态时的兜底）；
    显式传 'all' 返回全部状态的项目；传 in_progress/completed/cancelled 按对应状态过滤。
    """
    # status 缺省时默认按"进行中"过滤（兜底），显式传 'all' 可返回全部状态
    if status is None:
        status = 'in_progress'

    conditions = []
    if keyword:
        # 用户输入中的 % _ 先转义，避免"100%"这类词被当作通配符全量匹配
        like = f'%{_escape_like(keyword)}%'
        conditions.append(
            or_(
                CustomerSamplingProject.sequence_no.ilike(like, escape='\\'),
                CustomerSamplingProject.product_name.ilike(like, escape='\\'),
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

    # 分页查询
    pages = max(1, (total + per_page - 1) // per_page)
    page = max(1, min(page, pages))

    # noload 抑制模型默认 lazy='selectin' 级联加载（列表摘要无需任何关联对象，
    # 图片 URL 由下方 _batch_get_image_urls 单次批量查询提供）
    query = (
        select(CustomerSamplingProject)
        .options(
            noload(CustomerSamplingProject.parts),
            noload(CustomerSamplingProject.roles),
            noload(CustomerSamplingProject.fabric_versions),
            noload(CustomerSamplingProject.change_logs),
            noload(CustomerSamplingProject.pattern_maker),
            noload(CustomerSamplingProject.product_image),
            noload(CustomerSamplingProject.creator),
        )
    )
    for cond in conditions:
        query = query.where(cond)
    query = query.order_by(CustomerSamplingProject.updated_at.desc()).offset((page - 1) * per_page).limit(per_page)

    result = await db.execute(query)
    rows = result.scalars().all()

    # 批量预取产品图片 URL（单次 SQL，消除逐项目查询的 N+1）
    image_url_map = await _batch_get_image_urls(
        db, [p.product_image_file_id for p in rows if p.product_image_file_id]
    )

    return {
        'success': True,
        'items': [_project_to_summary(p, image_url_map) for p in rows],
        'total': total,
        'pages': pages,
        'current_page': page,
    }
