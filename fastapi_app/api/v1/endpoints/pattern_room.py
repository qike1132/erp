"""板房模块 API 路由

前缀: /api/v1/pattern-room
权限: 所有端点需登录（router 级 dependencies），写操作需 pattern_room_manage 权限
"""
import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from fastapi_app.core.database import get_async_db as get_db
from fastapi_app.core.database import get_async_read_db as get_read_db
from fastapi_app.core.deps import require_permission
from fastapi_app.core.exceptions import db_transaction
from fastapi_app.core.logger import logger
from fastapi_app.schemas.pattern_room import (
    BomActionResponse,
    BomCreateRequest,
    BomDetailResponse,
    BomItemsSaveRequest,
    BomListResponse,
    BomUpdateRequest,
    ChangeLogDetailResponse,
    ChangeLogListResponse,
    VersionCompareResponse,
    VersionCreateRequest,
    VersionListResponse,
)
from fastapi_app.services import pattern_room_service as svc
from fastapi_app.shared_models import User

router = APIRouter()

# 板房模块权限码：与 nav 配置 scripts/add_pattern_room_nav.py 中的 code 一致
PERM = 'pattern_room_manage'


# ==================== BOM 列表 ====================

@router.get('/bom', response_model=BomListResponse)
async def api_list_boms(
    page: int = Query(1, ge=1, description='页码'),
    per_page: int = Query(20, ge=1, le=100, description='每页数量'),
    keyword: str | None = Query(None, description='产品名/编号/客户关键字'),
    status: str | None = Query(None, description='状态'),
    current_version: str | None = Query(None, description='当前版本'),
    customer_id: int | None = Query(None, description='客户ID'),
    db: AsyncSession = Depends(get_read_db),
    _current_user: User = Depends(require_permission(PERM)),
) -> dict[str, Any]:
    """分页查询 BOM 列表"""
    try:
        return await svc.list_boms(
            db,
            page=page,
            per_page=per_page,
            keyword=keyword,
            status=status,
            current_version=current_version,
            customer_id=customer_id,
        )
    except SQLAlchemyError as e:
        logger.exception('查询板房 BOM 列表失败')
        raise HTTPException(status_code=500, detail='查询失败') from e


# ==================== BOM 详情 ====================

@router.get('/bom/{bom_id}', response_model=BomDetailResponse)
async def api_get_bom_detail(
    bom_id: int,
    db: AsyncSession = Depends(get_read_db),
    _current_user: User = Depends(require_permission(PERM)),
) -> dict[str, Any]:
    """获取 BOM 详情（含完整树形结构）"""
    try:
        return await svc.get_bom_detail(db, bom_id, include_logs=False)
    except SQLAlchemyError as e:
        logger.exception('查询 BOM 详情失败')
        raise HTTPException(status_code=500, detail='查询失败') from e


# ==================== 创建 BOM ====================

@router.post('/bom', response_model=BomActionResponse)
async def api_create_bom(
    data: BomCreateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission(PERM)),
) -> dict[str, Any]:
    """创建 BOM（含初始节点）"""
    try:
        async with db_transaction(db):
            result = await svc.create_bom(
                db,
                product_name=data.product_name,
                customer_id=data.customer_id,
                customer_name=data.customer_name,
                remark=data.remark,
                items=[item.model_dump() for item in data.items],
                operator=current_user,
            )
        return {'success': True, **result, 'message': '创建成功'}
    except HTTPException:
        raise
    except SQLAlchemyError as e:
        logger.exception('创建 BOM 失败')
        raise HTTPException(status_code=500, detail='创建失败') from e


# ==================== 更新 BOM 元信息 ====================

@router.put('/bom/{bom_id}', response_model=BomActionResponse)
async def api_update_bom(
    bom_id: int,
    data: BomUpdateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission(PERM)),
) -> dict[str, Any]:
    """更新 BOM 元信息（不含节点）"""
    try:
        async with db_transaction(db):
            result = await svc.update_bom(
                db,
                bom_id,
                product_name=data.product_name,
                customer_id=data.customer_id,
                customer_name=data.customer_name,
                remark=data.remark,
                status=data.status,
                operator=current_user,
            )
        return {'success': True, **result, 'message': '更新成功'}
    except HTTPException:
        raise
    except SQLAlchemyError as e:
        logger.exception('更新 BOM 失败')
        raise HTTPException(status_code=500, detail='更新失败') from e


# ==================== 删除 BOM ====================

@router.delete('/bom/{bom_id}', response_model=BomActionResponse)
async def api_delete_bom(
    bom_id: int,
    db: AsyncSession = Depends(get_db),
    _current_user: User = Depends(require_permission(PERM)),
) -> dict[str, Any]:
    """删除 BOM（级联删除节点、版本、日志）"""
    try:
        async with db_transaction(db):
            result = await svc.delete_bom(db, bom_id)
        return {'success': True, **result, 'message': '删除成功'}
    except HTTPException:
        raise
    except SQLAlchemyError as e:
        logger.exception('删除 BOM 失败')
        raise HTTPException(status_code=500, detail='删除失败') from e


# ==================== 整树保存 BOM 节点 ====================

@router.put('/bom/{bom_id}/items', response_model=BomActionResponse)
async def api_save_bom_items(
    bom_id: int,
    data: BomItemsSaveRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission(PERM)),
) -> dict[str, Any]:
    """整树保存 BOM 节点（替换式，自动 diff + 写日志）"""
    try:
        async with db_transaction(db):
            result = await svc.save_bom_items(
                db,
                bom_id,
                items=[item.model_dump() for item in data.items],
                operator=current_user,
            )
        return {'success': True, **result, 'message': f'保存成功（{result.get("changes", 0)} 项变更）'}
    except HTTPException:
        raise
    except SQLAlchemyError as e:
        logger.exception('保存 BOM 节点失败')
        raise HTTPException(status_code=500, detail='保存失败') from e


# ==================== 复制 BOM ====================

@router.post('/bom/{bom_id}/copy', response_model=BomActionResponse)
async def api_copy_bom(
    bom_id: int,
    data: dict | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission(PERM)),
) -> dict[str, Any]:
    """复制 BOM（含节点 + 版本快照）"""
    try:
        product_name = (data or {}).get('product_name') if data else None
        async with db_transaction(db):
            result = await svc.copy_bom(db, bom_id, product_name=product_name, operator=current_user)
        return {'success': True, **result, 'message': '复制成功'}
    except HTTPException:
        raise
    except SQLAlchemyError as e:
        logger.exception('复制 BOM 失败')
        raise HTTPException(status_code=500, detail='复制失败') from e


# ==================== 版本列表 ====================

@router.get('/bom/{bom_id}/versions', response_model=VersionListResponse)
async def api_list_versions(
    bom_id: int,
    db: AsyncSession = Depends(get_read_db),
    _current_user: User = Depends(require_permission(PERM)),
) -> dict[str, Any]:
    """获取 BOM 的所有版本号"""
    try:
        return await svc.list_versions(db, bom_id)
    except SQLAlchemyError as e:
        logger.exception('查询版本列表失败')
        raise HTTPException(status_code=500, detail='查询失败') from e

# ==================== 创建新版本 ====================

@router.post('/bom/{bom_id}/versions', response_model=BomActionResponse)
async def api_create_version(
    bom_id: int,
    data: VersionCreateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission(PERM)),
) -> dict[str, Any]:
    """创建新版本（自动快照当前数据 + 写日志）"""
    try:
        async with db_transaction(db):
            result = await svc.create_version(db, bom_id, reason=data.reason, operator=current_user)
        return {'success': True, **result, 'message': f'已创建版本 {result["to_version"]}'}
    except HTTPException:
        raise
    except SQLAlchemyError as e:
        logger.exception('创建版本失败')
        raise HTTPException(status_code=500, detail='创建失败') from e


# ==================== 版本对比 ====================

@router.get('/bom/{bom_id}/compare', response_model=VersionCompareResponse)
async def api_compare_versions(
    bom_id: int,
    from_version: str = Query(..., description='原版本号 T1'),
    to_version: str = Query(..., description='新版本号 T2'),
    db: AsyncSession = Depends(get_read_db),
    _current_user: User = Depends(require_permission(PERM)),
) -> dict[str, Any]:
    """对比两个版本"""
    try:
        return await svc.compare_versions(db, bom_id, from_version=from_version, to_version=to_version)
    except SQLAlchemyError as e:
        logger.exception('版本对比失败')
        raise HTTPException(status_code=500, detail='对比失败') from e


# ==================== 变更日志列表 ====================

@router.get('/bom/{bom_id}/change-logs', response_model=ChangeLogListResponse)
async def api_list_change_logs(
    bom_id: int,
    change_type: str | None = Query(None, description='变更类型'),
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_read_db),
    _current_user: User = Depends(require_permission(PERM)),
) -> dict[str, Any]:
    """获取变更日志列表"""
    try:
        return await svc.list_change_logs(
            db, bom_id, change_type=change_type, page=page, per_page=per_page
        )
    except SQLAlchemyError as e:
        logger.exception('查询变更日志失败')
        raise HTTPException(status_code=500, detail='查询失败') from e


# ==================== 变更日志详情 ====================

@router.get('/change-logs/{log_id}', response_model=ChangeLogDetailResponse)
async def api_get_change_log_detail(
    log_id: int,
    db: AsyncSession = Depends(get_read_db),
    _current_user: User = Depends(require_permission(PERM)),
) -> dict[str, Any]:
    """获取单条变更日志详情"""
    try:
        return await svc.get_change_log_detail(db, log_id)
    except SQLAlchemyError as e:
        logger.exception('查询变更日志详情失败')
        raise HTTPException(status_code=500, detail='查询失败') from e
