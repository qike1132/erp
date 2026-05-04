"""供应商管理接口"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from fastapi_app.core.config import settings
from fastapi_app.core.database import get_async_db as get_db
from fastapi_app.core.deps import require_permission
from fastapi_app.shared_models import User
from fastapi_app.schemas.supplier import (
    SupplierActionResponse,
    SupplierCreate,
    SupplierListResponse,
    SupplierResponse,
    SupplierToggleResponse,
    SupplierUpdate,
)
from fastapi_app.services import purchase_supplier_service
from utils.redis_cache import redis_cache

router = APIRouter()
SUPPLIER_LIST_CACHE_KEY = 'supplier:list:all'
SUPPLIER_LIST_CACHE_TTL = 300

def _supplier_to_resp(s) -> SupplierResponse:
    return SupplierResponse(id=s.id, name=s.name, contact_person=s.contact_person, phone=s.phone, address=s.address, remark=s.remark, status=s.status, created_at=s.created_at.strftime('%Y-%m-%d %H:%M') if s.created_at else None)

@router.get('/list', response_model=SupplierListResponse)
async def list_suppliers(_user: User=Depends(require_permission('supplier_manage')), db: AsyncSession=Depends(get_db)):
    """供应商列表（带缓存）"""
    cached = await redis_cache.get(SUPPLIER_LIST_CACHE_KEY)
    if cached is not None:
        return SupplierListResponse(data=[SupplierResponse(**c) for c in cached], total=len(cached))
    from fastapi_app.shared_models import Supplier
    result = await db.execute(select(Supplier).order_by(Supplier.name))
    suppliers = result.scalars().all()
    supplier_dicts = [_supplier_to_resp(s).model_dump() for s in suppliers]
    await redis_cache.set(SUPPLIER_LIST_CACHE_KEY, supplier_dicts, SUPPLIER_LIST_CACHE_TTL)
    return SupplierListResponse(data=[_supplier_to_resp(s) for s in suppliers], total=len(suppliers))

@router.post('/create', response_model=SupplierActionResponse)
async def create_supplier(data: SupplierCreate, _user: User=Depends(require_permission('supplier_manage')), db: AsyncSession=Depends(get_db)):
    """添加供应商"""
    try:
        await purchase_supplier_service.create_supplier(db, {'name': data.name, 'contact_person': data.contact_person, 'phone': data.phone, 'address': data.address, 'remark': data.remark})
        await redis_cache.delete_pattern(SUPPLIER_LIST_CACHE_KEY + '*')
        return SupplierActionResponse(message='供应商添加成功')
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

@router.put('/edit/{supplier_id}', response_model=SupplierActionResponse)
async def edit_supplier(supplier_id: int, data: SupplierUpdate, _user: User=Depends(require_permission('supplier_manage')), db: AsyncSession=Depends(get_db)):
    """编辑供应商"""
    try:
        await purchase_supplier_service.update_supplier(db, supplier_id, {'name': data.name, 'contact_person': data.contact_person, 'phone': data.phone, 'address': data.address, 'remark': data.remark})
        await redis_cache.delete_pattern(SUPPLIER_LIST_CACHE_KEY + '*')
        return SupplierActionResponse(message='供应商编辑成功')
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

@router.delete('/delete/{supplier_id}', response_model=SupplierActionResponse)
async def delete_supplier(supplier_id: int, _user: User=Depends(require_permission('supplier_manage')), db: AsyncSession=Depends(get_db)):
    """删除供应商"""
    try:
        await purchase_supplier_service.delete_supplier(db, supplier_id)
        await redis_cache.delete_pattern(SUPPLIER_LIST_CACHE_KEY + '*')
        return SupplierActionResponse(message='供应商删除成功')
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

@router.post('/toggle-status/{supplier_id}', response_model=SupplierToggleResponse)
async def toggle_status(supplier_id: int, _user: User=Depends(require_permission('supplier_manage')), db: AsyncSession=Depends(get_db)):
    """切换供应商状态"""
    try:
        result = await db.execute(text('UPDATE supplier SET status = NOT status WHERE id = :id RETURNING status'), {'id': supplier_id})
        status = result.scalar_one()
        await db.commit()
        await redis_cache.delete_pattern(SUPPLIER_LIST_CACHE_KEY + '*')
        status_text = '启用' if status else '禁用'
        return SupplierToggleResponse(status=status, message=f'供应商已{status_text}')
    except (ValueError, TypeError, OSError) as e:
        raise HTTPException(status_code=400, detail=settings.sanitize_business_error(e)) from e

@router.get('/search')
async def search_suppliers(q: str=Query('', description='搜索关键词'), _user: User=Depends(require_permission('supplier_manage')), db: AsyncSession=Depends(get_db)):
    """供应商搜索"""
    if not q.strip():
        return []
    from fastapi_app.shared_models import Supplier
    result = await db.execute(select(Supplier).where(Supplier.name.ilike(f'%{q.strip()}%')).order_by(Supplier.name))
    suppliers = result.scalars().all()
    return [_supplier_to_resp(s) for s in suppliers]

@router.get('/active-names')
async def active_names(_user: User=Depends(require_permission('supplier_manage')), db: AsyncSession=Depends(get_db)):
    """获取所有启用供应商名称列表（用于下拉选择）"""
    from fastapi_app.shared_models import Supplier
    result = await db.execute(select(Supplier).where(Supplier.status).order_by(Supplier.name))
    suppliers = result.scalars().all()
    return [s.name for s in suppliers]
