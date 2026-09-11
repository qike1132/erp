"""版师管理接口

前缀: /api/v1/pattern-maker/pattern-makers
提供版师列表查询与新增（供打样项目弹窗下拉与内联添加）。
权限: 需登录 + customer_sampling_manage
"""
import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from fastapi_app.core.database import get_async_db as get_db
from fastapi_app.core.database import get_async_read_db as get_read_db
from fastapi_app.core.deps import require_permission
from fastapi_app.core.exceptions import db_transaction
from fastapi_app.schemas.pattern_maker import (
    PatternMakerActionResponse,
    PatternMakerCreateRequest,
    PatternMakerListResponse,
)
from fastapi_app.services import pattern_maker_service as svc
from fastapi_app.shared_models import User

logger = logging.getLogger(__name__)
router = APIRouter()

PERM = 'customer_sampling_manage'


@router.get('/pattern-makers', response_model=PatternMakerListResponse)
async def api_list_pattern_makers(
    _current_user: User = Depends(require_permission(PERM)),
    db: AsyncSession = Depends(get_read_db),
) -> dict:
    """版师列表（按姓名升序，供打样弹窗下拉）"""
    try:
        return await svc.list_pattern_makers(db)
    except SQLAlchemyError as e:
        logger.exception('查询版师列表失败')
        raise HTTPException(status_code=500, detail='查询失败') from e


@router.post('/pattern-makers', response_model=PatternMakerActionResponse)
async def api_create_pattern_maker(
    data: PatternMakerCreateRequest,
    _current_user: User = Depends(require_permission(PERM)),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """新增版师（姓名唯一）"""
    try:
        async with db_transaction(db):
            result = await svc.create_pattern_maker(db, data.name)
        return {'success': True, 'message': '版师添加成功', 'id': result['id']}
    except HTTPException:
        raise
    except SQLAlchemyError as e:
        logger.exception('新增版师失败')
        raise HTTPException(status_code=500, detail='创建失败') from e


@router.delete('/pattern-makers/{maker_id}', response_model=PatternMakerActionResponse)
async def api_delete_pattern_maker(
    maker_id: int,
    _current_user: User = Depends(require_permission(PERM)),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """删除版师（关联项目 pattern_maker_id 自动 SET NULL）"""
    try:
        async with db_transaction(db):
            await svc.delete_pattern_maker(db, maker_id)
        return {'success': True, 'message': '版师删除成功'}
    except HTTPException:
        raise
    except SQLAlchemyError as e:
        logger.exception('删除版师失败')
        raise HTTPException(status_code=500, detail='删除失败') from e
