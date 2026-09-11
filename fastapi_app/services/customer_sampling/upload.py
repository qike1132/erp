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

from sqlalchemy import func, select
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

# 产品图片大小上限（与 storage_service 安全策略一致）
_IMAGE_MAX_SIZE = 10 * 1024 * 1024

# 允许的图片格式（PIL format 名称 → 声明 content-type 映射）
_IMAGE_FORMATS = {'JPEG', 'PNG', 'WEBP'}


def validate_project_image(content: bytes, content_type: str | None = None) -> None:
    """产品图片内容校验（魔数 + 解码 + 大小），在进入事务前快速失败。

    仅校验 Content-Type 可被伪造绕过（curl 自定义 header 即可上传任意内容，
    借 image/* content-type 被浏览器内联执行），因此必须用 PIL 实际解码验证：
    - Image.open 依据文件头魔数识别真实格式（JPEG/PNG/WebP）
    - verify() 完整性校验，拦截截断/损坏文件
    """
    from io import BytesIO

    if not content:
        raise BusinessError('图片内容为空')

    if content_type and content_type not in {'image/jpeg', 'image/png', 'image/webp'}:
        raise BusinessError('图片格式不支持，仅支持 JPEG/PNG/WebP')

    if len(content) > _IMAGE_MAX_SIZE:
        raise BusinessError('图片大小不能超过 10MB')

    from PIL import Image, UnidentifiedImageError

    try:
        # 与 storage_service 保持一致的解压炸弹阈值（受信用户上传）
        Image.MAX_IMAGE_PIXELS = 200_000_000
        with Image.open(BytesIO(content)) as im:
            fmt = (im.format or '').upper()
            if fmt not in _IMAGE_FORMATS:
                raise BusinessError('图片格式不支持，仅支持 JPEG/PNG/WebP')
            im.verify()
    except UnidentifiedImageError:
        raise BusinessError('文件内容不是有效的图片') from None
    except BusinessError:
        raise
    except Exception as e:  # broad-except: verify() 对损坏文件抛出的各类 PIL 异常统一转为业务错误
        raise BusinessError(f'图片校验失败: {e}') from e


async def _register_project_image_cleanup(db: AsyncSession, file_id: int | None) -> None:
    """注册产品图片清理（配合 db_transaction 的 post-commit 回调机制）

    - 引用检查：FileRecord 仍被其他打样项目引用时跳过（产品图片理论上单项目独占，
      防御同一 file_id 被多处引用的极端情况）
    - FileRecord 行在当前事务内删除（事务回滚时一并回滚）
    - 存储对象（原图 + 缩略图 + 模糊占位图）在 commit 成功后异步删除，
      避免事务持有期间执行网络 IO，也避免回滚后存储对象被误删
    """
    if file_id is None:
        return

    result = await db.execute(
        select(FileRecord.storage_key).where(FileRecord.id == file_id)
    )
    storage_key = result.scalar_one_or_none()
    if storage_key is None:
        return

    refs = await db.execute(
        select(func.count()).select_from(CustomerSamplingProject).where(
            CustomerSamplingProject.product_image_file_id == file_id,
        )
    )
    if refs.scalar_one() > 0:
        return

    record = await db.get(FileRecord, file_id)
    if record is not None:
        await db.delete(record)
        await db.flush()

    async def _delete_storage_objects() -> None:
        from fastapi_app.services.storage_service import (
            get_blur_key,
            get_storage,
            get_thumbnail_key,
        )
        storage = get_storage()
        for key in (storage_key, get_thumbnail_key(storage_key), get_blur_key(storage_key)):
            try:
                await storage.delete(key)
            except Exception as e:  # broad-except: 清理失败仅记录，不影响主流程
                logger.warning('清理产品图片存储对象失败: key=%s, error=%s', key, e)

    # TODO(P3): 此处使用项目约定的 db.info['post_commit_callbacks'] 回调机制，
    # 在 core/exceptions.py 的 db_transaction commit 成功后统一执行。
    # 迁移到 SQLAlchemy event.listen(session, 'after_commit', ...) 需同步改造
    # purchase_plan_common.py 等所有调用方，且 AsyncSession 的 after_commit
    # 事件回调为同步执行，无法直接处理 async 回调，暂保留现有机制。
    callbacks = db.info.setdefault('post_commit_callbacks', [])
    callbacks.append(_delete_storage_objects)


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
    old_image_file_id = project.product_image_file_id
    project.product_image_file_id = upload_result['id']
    await db.flush()

    # 旧图片不再被引用时清理（FileRecord 行事务内删除，存储对象 commit 后删除）
    if old_image_file_id is not None and old_image_file_id != upload_result['id']:
        await _register_project_image_cleanup(db, old_image_file_id)

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
