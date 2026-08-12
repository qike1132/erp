"""按客户分类打样信息模块 API 路由

前缀: /api/v1/pattern-room（保持路径不变，用户无感切换）
权限: 所有端点需登录（router 级 dependencies），写操作需 customer_sampling_manage 权限

对应 design.md 2.2.2 的 15 个接口端点。
"""
import logging
from typing import Any

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from fastapi_app.core.database import get_async_db as get_db
from fastapi_app.core.database import get_async_read_db as get_read_db
from fastapi_app.core.deps import require_permission
from fastapi_app.core.exceptions import db_transaction
from fastapi_app.core.logger import logger
from fastapi_app.schemas.customer_sampling import (
    ActionResponse,
    BatchPartCreateRequest,
    ChangeLogListResponse,
    GroupedListResponse,
    PartCreateRequest,
    PartListResponse,
    PartUpdateRequest,
    PartsByVersionResponse,
    ProjectCreateRequest,
    ProjectDetailResponse,
    ProjectListResponse,
    ProjectUpdateRequest,
    VersionCreateRequest,
    VersionDetailResponse,
    VersionListResponse,
)
from fastapi_app.services import customer_sampling_service as svc
from fastapi_app.shared_models import User

router = APIRouter()

# 按客户分类打样模块权限码（替换旧 pattern_room_manage）
PERM = 'customer_sampling_manage'


# ==================== 1. 按客户分组聚合查询 ====================

@router.get('/grouped-list', response_model=GroupedListResponse)
async def api_get_grouped_list(
    keyword: str | None = Query(None, description='关键词(序列号/产品名)'),
    customer_id: int | None = Query(None, description='客户ID筛选'),
    db: AsyncSession = Depends(get_read_db),
) -> dict[str, Any]:
    """按客户分组聚合查询打样项目列表"""
    try:
        return await svc.get_grouped_list(db, keyword=keyword, customer_id=customer_id)
    except SQLAlchemyError as e:
        logger.exception('查询分组列表失败')
        raise HTTPException(status_code=500, detail='查询失败') from e


# ==================== 2. 打样项目列表 ====================

@router.get('/projects', response_model=ProjectListResponse)
async def api_list_projects(
    page: int = Query(1, ge=1, description='页码'),
    per_page: int = Query(20, ge=1, le=100, description='每页数量'),
    keyword: str | None = Query(None, description='关键词(序列号/产品名)'),
    customer_id: int | None = Query(None, description='客户ID筛选'),
    db: AsyncSession = Depends(get_read_db),
) -> dict[str, Any]:
    """分页查询打样项目列表"""
    try:
        return await svc.list_projects(
            db, page=page, per_page=per_page, keyword=keyword, customer_id=customer_id,
        )
    except SQLAlchemyError as e:
        logger.exception('查询打样项目列表失败')
        raise HTTPException(status_code=500, detail='查询失败') from e


# ==================== 3. 打样项目详情 ====================

@router.get('/projects/{project_id}', response_model=ProjectDetailResponse)
async def api_get_project_detail(
    project_id: int,
    db: AsyncSession = Depends(get_read_db),
) -> dict[str, Any]:
    """获取打样项目详情（含部位布料 + 版本列表）"""
    try:
        return await svc.get_project_detail(db, project_id)
    except SQLAlchemyError as e:
        logger.exception('查询打样项目详情失败')
        raise HTTPException(status_code=500, detail='查询失败') from e


# ==================== 4. 新增打样项目 ====================

@router.post('/projects', response_model=ActionResponse)
async def api_create_project(
    data: ProjectCreateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission(PERM)),
) -> dict[str, Any]:
    """新增打样项目（自动生成序列号 + T1 基线版本）"""
    try:
        async with db_transaction(db):
            result = await svc.create_project(
                db,
                product_name=data.product_name,
                customer_id=data.customer_id,
                remark=data.remark,
                user_id=current_user.id,
            )
        return {'success': True, 'message': '创建成功', **result}
    except HTTPException:
        raise
    except SQLAlchemyError as e:
        logger.exception('创建打样项目失败')
        raise HTTPException(status_code=500, detail='创建失败') from e


# ==================== 5. 编辑打样项目 ====================

@router.put('/projects/{project_id}', response_model=ActionResponse)
async def api_update_project(
    project_id: int,
    data: ProjectUpdateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission(PERM)),
) -> dict[str, Any]:
    """编辑打样项目（乐观锁校验）"""
    try:
        async with db_transaction(db):
            await svc.update_project(
                db,
                project_id,
                product_name=data.product_name,
                customer_id=data.customer_id,
                remark=data.remark,
                product_image_file_id=data.product_image_file_id,
                current_version=data.current_version,
                version=data.version,
                user_id=current_user.id,
            )
        return {'success': True, 'message': '更新成功'}
    except HTTPException:
        raise
    except SQLAlchemyError as e:
        logger.exception('编辑打样项目失败')
        raise HTTPException(status_code=500, detail='更新失败') from e


# ==================== 6. 删除打样项目 ====================

@router.delete('/projects/{project_id}', response_model=ActionResponse)
async def api_delete_project(
    project_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission(PERM)),
) -> dict[str, Any]:
    """删除打样项目（级联删除部位/版本/日志，先写审计日志）"""
    try:
        async with db_transaction(db):
            await svc.delete_project(db, project_id, user_id=current_user.id)
        return {'success': True, 'message': '删除成功'}
    except HTTPException:
        raise
    except SQLAlchemyError as e:
        logger.exception('删除打样项目失败')
        raise HTTPException(status_code=500, detail='删除失败') from e


# ==================== 7. 上传产品图片 ====================

@router.post('/projects/{project_id}/image', response_model=ActionResponse)
async def api_upload_project_image(
    project_id: int,
    file: UploadFile = File(..., description='产品图片文件'),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission(PERM)),
) -> dict[str, Any]:
    """上传产品图片（复用 storage_service，限制 JPEG/PNG/WebP ≤ 10MB）"""
    try:
        content = await file.read()
        async with db_transaction(db):
            result = await svc.upload_project_image(
                db,
                project_id,
                content=content,
                original_filename=file.filename or 'upload.bin',
                content_type=file.content_type,
                user_id=current_user.id,
            )
        return {'success': True, 'message': '上传成功', **result}
    except HTTPException:
        raise
    except SQLAlchemyError as e:
        logger.exception('上传产品图片失败')
        raise HTTPException(status_code=500, detail='上传失败') from e


# ==================== 8. 部位列表 ====================

@router.get('/projects/{project_id}/parts', response_model=PartListResponse)
async def api_list_parts(
    project_id: int,
    db: AsyncSession = Depends(get_read_db),
) -> dict[str, Any]:
    """查询项目下所有部位（按 sort_order 升序，含布料信息）"""
    try:
        return await svc.list_parts(db, project_id)
    except SQLAlchemyError as e:
        logger.exception('查询部位列表失败')
        raise HTTPException(status_code=500, detail='查询失败') from e


# ==================== 9. 新增部位 ====================

@router.post('/projects/{project_id}/parts', response_model=ActionResponse)
async def api_create_part(
    project_id: int,
    data: PartCreateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission(PERM)),
) -> dict[str, Any]:
    """新增部位（部位名称同项目下唯一）"""
    try:
        async with db_transaction(db):
            result = await svc.create_part(
                db,
                project_id,
                part_name=data.part_name,
                sort_order=data.sort_order,
                fabric_name=data.fabric_name,
                fabric_spec=data.fabric_spec,
                fabric_color_no=data.fabric_color_no,
                supplier_id=data.supplier_id,
                contact_person=data.contact_person,
                contact_phone=data.contact_phone,
                unit_price=data.unit_price,
                delivery_days=data.delivery_days,
                remark=data.remark,
                user_id=current_user.id,
            )
        return {'success': True, 'message': '创建成功', **result}
    except HTTPException:
        raise
    except SQLAlchemyError as e:
        logger.exception('新增部位失败')
        raise HTTPException(status_code=500, detail='创建失败') from e


# ==================== 9b. 批量新增部位 ====================

@router.post('/projects/{project_id}/parts/batch', response_model=ActionResponse)
async def api_batch_create_parts(
    project_id: int,
    data: BatchPartCreateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission(PERM)),
) -> dict[str, Any]:
    """批量新增部位（一次事务中创建多条）"""
    try:
        items = [item.model_dump() for item in data.items]
        async with db_transaction(db):
            result = await svc.batch_create_parts(db, project_id, items=items, user_id=current_user.id)
        return {'success': True, 'message': f"已创建 {result['count']} 个部位", **result}
    except HTTPException:
        raise
    except SQLAlchemyError as e:
        logger.exception('批量新增部位失败')
        raise HTTPException(status_code=500, detail='批量创建失败') from e


# ==================== 9c. 复制部位版本 ====================

@router.post('/parts/{part_id}/copy-version', response_model=ActionResponse)
async def api_copy_part_version(
    part_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission(PERM)),
) -> dict[str, Any]:
    """复制部位版本 — 在该部位名称下新增一个版本号 +1 的空白记录"""
    try:
        async with db_transaction(db):
            result = await svc.copy_part_version(db, part_id, user_id=current_user.id)
        return {
            'success': True,
            'message': f"已创建版本 {result['version_no']}",
            **result,
        }
    except HTTPException:
        raise
    except SQLAlchemyError as e:
        logger.exception('复制部位版本失败')
        raise HTTPException(status_code=500, detail='复制失败') from e


@router.put('/parts/{part_id}', response_model=ActionResponse)
async def api_update_part(
    part_id: int,
    data: PartUpdateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission(PERM)),
) -> dict[str, Any]:
    """编辑部位布料（乐观锁校验，历史版本快照不变）"""
    try:
        async with db_transaction(db):
            await svc.update_part(
                db,
                part_id,
                part_name=data.part_name,
                sort_order=data.sort_order,
                fabric_name=data.fabric_name,
                fabric_spec=data.fabric_spec,
                fabric_color_no=data.fabric_color_no,
                supplier_id=data.supplier_id,
                supplier_name=data.supplier_name,
                contact_person=data.contact_person,
                contact_phone=data.contact_phone,
                unit_price=data.unit_price,
                delivery_days=data.delivery_days,
                remark=data.remark,
                version=data.version,
                user_id=current_user.id,
            )
        return {'success': True, 'message': '更新成功'}
    except HTTPException:
        raise
    except SQLAlchemyError as e:
        logger.exception('编辑部位失败')
        raise HTTPException(status_code=500, detail='更新失败') from e


# ==================== 11. 删除部位 ====================

@router.delete('/parts/{part_id}', response_model=ActionResponse)
async def api_delete_part(
    part_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission(PERM)),
) -> dict[str, Any]:
    """删除部位（历史版本快照中该部位数据保留）"""
    try:
        async with db_transaction(db):
            await svc.delete_part(db, part_id, user_id=current_user.id)
        return {'success': True, 'message': '删除成功'}
    except HTTPException:
        raise
    except SQLAlchemyError as e:
        logger.exception('删除部位失败')
        raise HTTPException(status_code=500, detail='删除失败') from e


# ==================== 12. 版本列表 ====================

@router.get('/projects/{project_id}/versions', response_model=VersionListResponse)
async def api_list_versions(
    project_id: int,
    db: AsyncSession = Depends(get_read_db),
) -> dict[str, Any]:
    """查询项目所有版本（按 version_no 升序）"""
    try:
        return await svc.list_versions(db, project_id)
    except SQLAlchemyError as e:
        logger.exception('查询版本列表失败')
        raise HTTPException(status_code=500, detail='查询失败') from e


# ==================== 13. 创建新版本 ====================

@router.post('/projects/{project_id}/versions', response_model=ActionResponse)
async def api_create_version(
    project_id: int,
    data: VersionCreateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission(PERM)),
) -> dict[str, Any]:
    """创建新版本（快照当前部位布料 + 计算相对前一版本 diff）"""
    try:
        async with db_transaction(db):
            result = await svc.create_version(
                db,
                project_id,
                reason=data.reason,
                user_id=current_user.id,
            )
        return {
            'success': True,
            'message': f"已创建版本 {result['version_no']}",
            **result,
        }
    except HTTPException:
        raise
    except SQLAlchemyError as e:
        logger.exception('创建新版本失败')
        raise HTTPException(status_code=500, detail='创建失败') from e


# ==================== 14. 版本详情 ====================

@router.get('/versions/{version_id}', response_model=VersionDetailResponse)
async def api_get_version_detail(
    version_id: int,
    db: AsyncSession = Depends(get_read_db),
) -> dict[str, Any]:
    """版本详情（T1 完整快照 / T2+ 变更 diff / 降级完整快照）"""
    try:
        return await svc.get_version_detail(db, version_id)
    except SQLAlchemyError as e:
        logger.exception('查询版本详情失败')
        raise HTTPException(status_code=500, detail='查询失败') from e


# ==================== 15. 变更日志列表 ====================

@router.get('/projects/{project_id}/change-logs', response_model=ChangeLogListResponse)
async def api_list_change_logs(
    project_id: int,
    page: int = Query(1, ge=1, description='页码'),
    per_page: int = Query(50, ge=1, le=200, description='每页数量'),
    db: AsyncSession = Depends(get_read_db),
) -> dict[str, Any]:
    """查询项目变更日志（按时间倒序分页）"""
    try:
        return await svc.list_change_logs(db, project_id, page=page, per_page=per_page)
    except SQLAlchemyError as e:
        logger.exception('查询变更日志失败')
        raise HTTPException(status_code=500, detail='查询失败') from e


# ==================== 16. 部位跨版本汇总 ====================

@router.get('/projects/{project_id}/parts-by-version', response_model=PartsByVersionResponse)
async def api_get_parts_by_version(
    project_id: int,
    db: AsyncSession = Depends(get_read_db),
) -> dict[str, Any]:
    """获取项目所有版本的部位布料数据（跨版本二维表数据源）"""
    try:
        return await svc.get_parts_by_version(db, project_id)
    except SQLAlchemyError as e:
        logger.exception('查询部位跨版本数据失败')
        raise HTTPException(status_code=500, detail='查询失败') from e