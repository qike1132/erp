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

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from fastapi_app.core.exceptions import BusinessError, NotFoundError
from fastapi_app.shared_models import (
    CustomerSamplingProject,
    FileRecord,
)

logger = logging.getLogger(__name__)

# 版本快照中参与 diff 计算的布料业务字段
_SNAPSHOT_FIELDS = (
    'part_name', 'sort_order', 'fabric_name', 'fabric_spec',
    'supplier_id', 'supplier_name', 'contact_person', 'contact_phone',
    'unit_price', 'delivery_days', 'remark',
)

from .common import _ensure_project_exists, _get_user_name, _write_change_log


async def upload_project_image(
    db: AsyncSession,
    project_id: int,
    *,
    content: bytes,
    original_filename: str,
    content_type: str | None = None,
    user_id: int | None = None,
) -> dict:
    """上传产品图片

    - 复用 storage_service.save_upload
    - 更新 project.product_image_file_id
    - 文件类型限制 image/jpeg|png|webp，大小 ≤ 10MB（storage_service 安全策略）
    """
    from fastapi_app.services.storage_service import save_upload

    # 校验项目存在
    await _ensure_project_exists(db, project_id)

    # 文件类型校验
    allowed_types = {'image/jpeg', 'image/png', 'image/webp'}
    if content_type and content_type not in allowed_types:
        raise BusinessError('图片格式不支持，仅支持 JPEG/PNG/WebP')

    # 文件大小校验（≤ 10MB）
    max_size = 10 * 1024 * 1024
    if len(content) > max_size:
        raise BusinessError('图片大小不能超过 10MB')

    # 复用 storage_service 保存文件（同步生成 400px WebP 缩略图供列表使用）
    upload_result = await save_upload(
        content=content,
        original_filename=original_filename,
        db=db,
        uploader_id=user_id,
        prefix='customer-sampling/',
        generate_thumbnail=True,
    )

    # 更新项目的 product_image_file_id
    result = await db.execute(
        select(CustomerSamplingProject).where(CustomerSamplingProject.id == project_id)
    )
    project = result.scalar_one_or_none()
    if project is None:
        raise NotFoundError('打样项目不存在')
    project.product_image_file_id = upload_result['id']
    await db.flush()

    # 写审计日志
    operator_name = await _get_user_name(db, user_id)
    await _write_change_log(
        db, project_id, 'upload_image', user_id, operator_name,
    )

    logger.info(
        '上传产品图片: project_id=%s, file_id=%s, url=%s',
        project_id, upload_result['id'], upload_result['url'],
    )
    return {
        'file_id': upload_result['id'],
        'url': upload_result['url'],
        'thumbnail_url': upload_result.get('thumbnail_url'),
    }


# ==================== T06b: 角色 CRUD ====================



async def _batch_get_image_urls(db: AsyncSession, file_ids: list[int]) -> dict[int, dict]:
    """批量获取文件存储 URL（单次 IN 查询，替代逐个查询，消除列表页 N+1）

    Args:
        db: 数据库会话。
        file_ids: FileRecord ID 列表（可含重复，内部去重）。

    Returns:
        {file_id: {"url": ..., "thumbnail_url": ..., "blur_url": ...}} 映射；存储后端异常或单条失败时对应条目缺失。
        thumbnail_url / blur_url 通过 storage_key 派生固定后缀，前端加载失败时回退到 url（兼容历史无变体文件）。
    """
    if not file_ids:
        return {}
    from fastapi_app.services.storage_service import get_blur_key, get_storage, get_thumbnail_key
    result = await db.execute(
        select(FileRecord.id, FileRecord.storage_key).where(FileRecord.id.in_(set(file_ids)))
    )
    rows = result.all()
    if not rows:
        return {}
    try:
        storage = get_storage()
    except Exception as e:  # broad-except: 服务层容错，记录异常并返回安全默认值
        logger.warning('获取存储后端失败: %s', e)
        return {}
    url_map: dict[int, dict] = {}
    for fid, storage_key in rows:
        if not storage_key:
            continue
        try:
            url_map[fid] = {
                'url': storage.get_url(storage_key),
                'thumbnail_url': storage.get_url(get_thumbnail_key(storage_key)),
                'blur_url': storage.get_url(get_blur_key(storage_key)),
            }
        except Exception as e:  # broad-except: 服务层容错，记录异常并返回安全默认值
            logger.warning('获取产品图片 URL 失败: file_id=%s, error=%s', fid, e)
    return url_map



async def _get_product_image_urls(db: AsyncSession, file_id: int | None) -> dict | None:
    """通过 FileRecord.storage_key 拼接产品图片访问 URL（单条场景，复用批量实现）

    返回 {"url": ..., "thumbnail_url": ..., "blur_url": ...} 或 None
    """
    if file_id is None:
        return None
    url_map = await _batch_get_image_urls(db, [file_id])
    return url_map.get(file_id)
