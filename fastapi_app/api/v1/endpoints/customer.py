"""客户管理接口"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from fastapi_app.core.database import get_async_db, get_async_read_db
from fastapi_app.core.deps import get_current_user_id, require_permission
from fastapi_app.schemas.customer import (
    CustomerActionResponse,
    CustomerCreate,
    CustomerListResponse,
    CustomerResponse,
    CustomerToggleResponse,
    CustomerUpdate,
)
from fastapi_app.services import customer_service
from fastapi_app.shared_models import User
from utils.redis_cache import redis_cache

router = APIRouter()
CUSTOMER_LIST_CACHE_KEY = 'customer:list:all'
CUSTOMER_LIST_CACHE_TTL = 300

def _customer_to_resp(c) -> CustomerResponse:
    return CustomerResponse(id=c.id, customer_code=c.customer_code, name=c.name, contact=c.contact, phone=c.phone, address=c.address, note=c.note, status=c.status, create_time=c.create_time.strftime('%Y-%m-%d %H:%M') if c.create_time else None)

@router.get('/list', response_model=CustomerListResponse)
async def list_customers(status: str | None=Query(None, description='状态筛选: active/inactive'), page: int=Query(1, ge=1, description='页码'), per_page: int=Query(50, ge=1, le=200, description='每页数量'), search: str=Query('', max_length=100, description='搜索关键词'), user: User=Depends(require_permission('customer_manage')), db: AsyncSession=Depends(get_async_read_db)):
    """客户列表（带缓存，支持分页和搜索）"""
    if not search and page == 1:
        cache_key = f"{CUSTOMER_LIST_CACHE_KEY}:{status or 'all'}:{per_page}"
        cached = await redis_cache.get(cache_key)
        if cached is not None:
            return CustomerListResponse(customers=[CustomerResponse(**c) for c in cached['items']], total=cached['total'])
    result = await customer_service.get_customers(db, status, page=page, per_page=per_page, search=search)
    customer_dicts = [_customer_to_resp(c).model_dump() for c in result['items']]
    if not search and page == 1:
        cache_key = f"{CUSTOMER_LIST_CACHE_KEY}:{status or 'all'}:{per_page}"
        await redis_cache.set(cache_key, {'items': customer_dicts, 'total': result['total']}, CUSTOMER_LIST_CACHE_TTL)
    return CustomerListResponse(customers=[_customer_to_resp(c) for c in result['items']], total=result['total'])

@router.get('/search')
async def search_customers(q: str=Query('', description='搜索关键词'), user: User=Depends(require_permission('customer_manage')), db: AsyncSession=Depends(get_async_read_db)):
    """客户搜索"""
    if not q.strip():
        return []
    customers = await customer_service.search_customers(db, q.strip())
    return [_customer_to_resp(c) for c in customers]

@router.get('/active-names')
async def active_names(user: User=Depends(require_permission('customer_manage')), db: AsyncSession = Depends(get_async_read_db)):
    """获取所有启用客户名称列表（用于下拉选择）"""
    return await customer_service.get_active_customer_names(db)

@router.get('/{customer_id}', response_model=CustomerResponse)
async def get_customer(customer_id: int, user: User=Depends(require_permission('customer_manage')), db: AsyncSession=Depends(get_async_read_db)):
    """获取单个客户"""
    customer = await customer_service.get_customer(db, customer_id)
    if not customer:
        raise HTTPException(status_code=404, detail='客户不存在')
    return _customer_to_resp(customer)

@router.post('/create', response_model=CustomerActionResponse)
async def create_customer(data: CustomerCreate, user: User=Depends(require_permission('customer_manage')), db: AsyncSession=Depends(get_async_db)):
    """添加客户"""
    try:
        await customer_service.create_customer(db, data.name, data.contact, data.phone, data.address, data.note)
        await db.commit()
        await redis_cache.delete_pattern(CUSTOMER_LIST_CACHE_KEY + '*')
        return CustomerActionResponse(message='客户添加成功')
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

@router.put('/edit/{customer_id}', response_model=CustomerActionResponse)
async def edit_customer(customer_id: int, data: CustomerUpdate, user: User=Depends(require_permission('customer_manage')), db: AsyncSession=Depends(get_async_db)):
    """编辑客户"""
    try:
        await customer_service.update_customer(db, customer_id, data.name, data.contact, data.phone, data.address, data.note, data.status)
        await db.commit()
        await redis_cache.delete_pattern(CUSTOMER_LIST_CACHE_KEY + '*')
        return CustomerActionResponse(message='客户编辑成功')
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

@router.delete('/delete/{customer_id}', response_model=CustomerActionResponse)
async def delete_customer(customer_id: int, user: User=Depends(require_permission('customer_manage')), db: AsyncSession=Depends(get_async_db)):
    """删除客户"""
    try:
        await customer_service.delete_customer(db, customer_id)
        await db.commit()
        await redis_cache.delete_pattern(CUSTOMER_LIST_CACHE_KEY + '*')
        return CustomerActionResponse(message='客户删除成功')
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=400, detail='该客户已有相关单据，无法删除！建议禁用该客户。') from None

@router.post('/toggle-status/{customer_id}', response_model=CustomerToggleResponse)
async def toggle_status(customer_id: int, user: User=Depends(require_permission('customer_manage')), db: AsyncSession=Depends(get_async_db)):
    """切换客户状态"""
    try:
        customer = await customer_service.toggle_customer_status(db, customer_id)
        await db.commit()
        await redis_cache.delete_pattern(CUSTOMER_LIST_CACHE_KEY + '*')
        status_text = '启用' if customer.status else '禁用'
        return CustomerToggleResponse(status=customer.status, message=f'客户已{status_text}')
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
