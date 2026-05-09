"""
采购中心 — 修改日志 / 保存查询 / 状态日志等辅助路由
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from fastapi_app.api.v1.endpoints.purchase_center.schemas import SaveQueryRequest
from fastapi_app.core.database import get_async_db as get_db, get_async_read_db as get_read_db
from fastapi_app.core.deps import require_permission
from fastapi_app.services import purchase_center_service as svc

router = APIRouter()

@router.get('/modification-logs')
async def api_get_modification_logs(target_type: str=Query(''), target_id: int=Query(0), page: int=Query(1, ge=1), per_page: int=Query(20, ge=1), db: AsyncSession=Depends(get_read_db), _user=Depends(require_permission('product_manage'))):
    result = await svc.get_modification_logs(db, target_type=target_type, target_id=target_id, page=page, per_page=per_page)
    return {'success': True, **result}

@router.get('/saved-queries')
async def api_get_saved_queries(query_type: str=Query('purchase_order'), db: AsyncSession=Depends(get_read_db), _user=Depends(require_permission('product_manage'))):
    queries = await svc.get_saved_queries(db, query_type=query_type, user_id=_user.id)
    return {'success': True, 'queries': queries}

@router.post('/saved-queries')
async def api_save_query(data: SaveQueryRequest, db: AsyncSession=Depends(get_db), _user=Depends(require_permission('product_manage'))):
    try:
        result = await svc.save_query(db, data.model_dump(), _user.id, _user.username)
        return {'success': True, 'query': result}
    except (SQLAlchemyError, ValueError, RuntimeError):
        raise HTTPException(status_code=500, detail='操作失败，请稍后重试') from None

@router.delete('/saved-queries/{query_id}')
async def api_delete_saved_query(query_id: int, db: AsyncSession=Depends(get_db), _user=Depends(require_permission('product_manage'))):
    result = await svc.delete_saved_query(db, query_id)
    if not result:
        raise HTTPException(status_code=404, detail='查询不存在')
    return {'success': True, 'message': result}

@router.post('/saved-queries/{query_id}/use')
async def api_use_saved_query(query_id: int, db: AsyncSession=Depends(get_db), _user=Depends(require_permission('product_manage'))):
    result = await svc.use_saved_query(db, query_id)
    if not result:
        raise HTTPException(status_code=404, detail='查询不存在')
    return {'success': True, 'query': result}

@router.get('/status-logs')
async def api_get_status_logs(target_type: str=Query(''), target_id: int=Query(0), order_no: str=Query(''), page: int=Query(1, ge=1), per_page: int=Query(20, ge=1), db: AsyncSession=Depends(get_read_db), _user=Depends(require_permission('product_manage'))):
    result = await svc.get_status_logs(db, target_type=target_type, target_id=target_id, order_no=order_no, page=page, per_page=per_page)
    return {'success': True, **result}
