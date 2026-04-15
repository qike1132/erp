"""客户管理接口"""
from fastapi import APIRouter, Depends, HTTPException, Query

from fastapi_app.core.deps import require_permission
from fastapi_app.core.database import get_async_db
from fastapi_app.shared_models import User
from fastapi_app.schemas.customer import (
    CustomerCreate, CustomerUpdate,
    CustomerResponse, CustomerListResponse, CustomerActionResponse, CustomerToggleResponse,
)
from fastapi_app.services import customer_service
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter()


def _customer_to_resp(c) -> CustomerResponse:
    return CustomerResponse(
        id=c.id,
        customer_code=c.customer_code,
        name=c.name,
        contact=c.contact,
        phone=c.phone,
        address=c.address,
        note=c.note,
        status=c.status,
        create_time=c.create_time.strftime('%Y-%m-%d %H:%M') if c.create_time else None,
    )


@router.get("/list", response_model=CustomerListResponse)
async def list_customers(
    status: str | None = Query(None, description="状态筛选: active/inactive"),
    user: User = Depends(require_permission("customer_manage")),
    db: AsyncSession = Depends(get_async_db),
):
    """客户列表"""
    customers = await customer_service.get_customers(db, status)
    return CustomerListResponse(
        customers=[_customer_to_resp(c) for c in customers],
        total=len(customers),
    )


@router.post("/create", response_model=CustomerActionResponse)
async def create_customer(
    data: CustomerCreate,
    user: User = Depends(require_permission("customer_manage")),
    db: AsyncSession = Depends(get_async_db),
):
    """添加客户"""
    try:
        await customer_service.create_customer(
            db, data.name, data.contact, data.phone, data.address, data.note
        )
        await db.commit()
        return CustomerActionResponse(message="客户添加成功")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.put("/edit/{customer_id}", response_model=CustomerActionResponse)
async def edit_customer(
    customer_id: int,
    data: CustomerUpdate,
    user: User = Depends(require_permission("customer_manage")),
    db: AsyncSession = Depends(get_async_db),
):
    """编辑客户"""
    try:
        await customer_service.update_customer(
            db, customer_id, data.name, data.contact, data.phone, data.address, data.note, data.status
        )
        await db.commit()
        return CustomerActionResponse(message="客户编辑成功")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/delete/{customer_id}", response_model=CustomerActionResponse)
async def delete_customer(
    customer_id: int,
    user: User = Depends(require_permission("customer_manage")),
    db: AsyncSession = Depends(get_async_db),
):
    """删除客户"""
    try:
        await customer_service.delete_customer(db, customer_id)
        await db.commit()
        return CustomerActionResponse(message="客户删除成功")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/toggle-status/{customer_id}", response_model=CustomerToggleResponse)
async def toggle_status(
    customer_id: int,
    user: User = Depends(require_permission("customer_manage")),
    db: AsyncSession = Depends(get_async_db),
):
    """切换客户状态"""
    try:
        customer = await customer_service.toggle_customer_status(db, customer_id)
        await db.commit()
        status_text = "启用" if customer.status else "禁用"
        return CustomerToggleResponse(
            status=customer.status,
            message=f"客户已{status_text}",
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/search")
async def search_customers(
    q: str = Query("", description="搜索关键词"),
    user: User = Depends(require_permission("customer_manage")),
    db: AsyncSession = Depends(get_async_db),
):
    """客户搜索"""
    if not q.strip():
        return []
    customers = await customer_service.search_customers(db, q.strip())
    return [_customer_to_resp(c) for c in customers]


@router.get("/active-names")
async def active_names(
    user: User = Depends(require_permission("customer_manage")),
    db: AsyncSession = Depends(get_async_db),
):
    """获取所有启用客户名称列表（用于下拉选择）"""
    return await customer_service.get_active_customer_names(db)
