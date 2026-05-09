"""
采购中心 — 供应商相关路由
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.exc import DisconnectionError, OperationalError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from fastapi_app.api.v1.endpoints.purchase_center.schemas import SupplierCreateRequest, SupplierUpdateRequest
from fastapi_app.core.database import get_async_db as get_db, get_async_read_db as get_read_db
from fastapi_app.core.deps import require_permission
from fastapi_app.core.logger import logger
from fastapi_app.services import purchase_center_service as svc

router = APIRouter()

@router.get('/suppliers')
async def api_get_suppliers(with_stats: str=Query('0'), db: AsyncSession=Depends(get_read_db), _user=Depends(require_permission('product_manage'))):
    try:
        suppliers = await svc.get_suppliers(db, with_stats=with_stats == '1')
        return {'success': True, 'suppliers': suppliers}
    except (OperationalError, DisconnectionError, ValueError) as e:
        logger.exception(f'获取供应商列表失败: {str(e)}')
        raise HTTPException(status_code=500, detail='操作失败，请稍后重试') from e

@router.post('/suppliers')
async def api_create_supplier(data: SupplierCreateRequest, db: AsyncSession=Depends(get_db), _user=Depends(require_permission('product_manage'))):
    try:
        result = await svc.create_supplier(db, data.model_dump())
        return {'success': True, 'supplier': result}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except (SQLAlchemyError, RuntimeError):
        raise HTTPException(status_code=500, detail='操作失败，请稍后重试') from None

@router.put('/suppliers/{supplier_id}')
async def api_update_supplier(supplier_id: int, data: SupplierUpdateRequest, db: AsyncSession=Depends(get_db), _user=Depends(require_permission('product_manage'))):
    try:
        result = await svc.update_supplier(db, supplier_id, data.model_dump())
        return {'success': True, 'supplier': result}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except (SQLAlchemyError, RuntimeError):
        raise HTTPException(status_code=500, detail='操作失败，请稍后重试') from None

@router.get('/suppliers/{supplier_id}/materials')
async def api_get_supplier_materials(supplier_id: int, db: AsyncSession=Depends(get_read_db), _user=Depends(require_permission('product_manage'))):
    try:
        materials = await svc.get_supplier_materials(db, supplier_id)
        return {'success': True, 'materials': materials}
    except (OperationalError, DisconnectionError, ValueError) as e:
        logger.exception(f'获取供应商物料失败: {str(e)}')
        raise HTTPException(status_code=500, detail='操作失败，请稍后重试') from e
