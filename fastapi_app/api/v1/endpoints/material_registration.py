"""来料登记接口"""
from fastapi import APIRouter, Depends, HTTPException, Query

from fastapi_app.core.deps import require_permission
from fastapi_app.core.database import get_async_db
from fastapi_app.shared_models import User
from fastapi_app.schemas.material_registration import (
    MaterialRegistrationCreate, MaterialRegistrationUpdate,
    ReceiveMaterialRequest, RegistrationListResponse, RegistrationDetailResponse,
    StatsOverviewResponse, TrendResponse, ActionResponse,
)
from fastapi_app.services import material_registration_service as mr_service
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter()


@router.get("/registrations", response_model=RegistrationListResponse)
async def list_registrations(
    page: int = Query(1, ge=1), per_page: int = Query(20, ge=1, le=100),
    status: str = Query(''), order_no: str = Query(''), supplier: str = Query(''),
    start_date: str = Query(''), end_date: str = Query(''),
    user: User = Depends(require_permission("product_manage")),
    db: AsyncSession = Depends(get_async_db),
):
    """获取来料登记列表"""
    return await mr_service.get_registrations(
        db, page, per_page, status, order_no, supplier, start_date, end_date
    )


@router.get("/registrations/{reg_id}", response_model=RegistrationDetailResponse)
async def get_registration(
    reg_id: int,
    user: User = Depends(require_permission("product_manage")),
    db: AsyncSession = Depends(get_async_db),
):
    """获取来料登记详情"""
    try:
        return await mr_service.get_registration(db, reg_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/registrations", response_model=RegistrationDetailResponse)
async def create_registration(
    data: MaterialRegistrationCreate,
    user: User = Depends(require_permission("product_manage")),
    db: AsyncSession = Depends(get_async_db),
):
    """创建来料登记"""
    try:
        result = await mr_service.create_registration(
            db, data.purchase_order_id, user.id, user.username,
            data.remark, [item.model_dump() for item in data.items]
        )
        await db.commit()
        return RegistrationDetailResponse(registration=result['registration'])
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.put("/registrations/{reg_id}", response_model=RegistrationDetailResponse)
async def update_registration(
    reg_id: int,
    data: MaterialRegistrationUpdate,
    user: User = Depends(require_permission("product_manage")),
    db: AsyncSession = Depends(get_async_db),
):
    """更新来料登记"""
    try:
        result = await mr_service.update_registration(
            db, reg_id, data.status, data.remark, data.items
        )
        await db.commit()
        return RegistrationDetailResponse(registration=result['registration'])
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.delete("/registrations/{reg_id}", response_model=ActionResponse)
async def delete_registration(
    reg_id: int,
    user: User = Depends(require_permission("product_manage")),
    db: AsyncSession = Depends(get_async_db),
):
    """删除来料登记"""
    try:
        result = await mr_service.delete_registration(db, reg_id)
        await db.commit()
        return ActionResponse(message=result['message'])
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/purchase-orders/available")
async def available_purchase_orders(
    status: str = Query('pending'),
    user: User = Depends(require_permission("product_manage")),
    db: AsyncSession = Depends(get_async_db),
):
    """获取可用采购订单列表"""
    return await mr_service.get_available_purchase_orders(db, status)


@router.get("/stats/overview", response_model=StatsOverviewResponse)
async def stats_overview(
    user: User = Depends(require_permission("product_manage")),
    db: AsyncSession = Depends(get_async_db),
):
    """统计概览"""
    return await mr_service.get_stats_overview(db)


@router.get("/stats/trend", response_model=TrendResponse)
async def stats_trend(
    days: int = Query(30, ge=1, le=365),
    user: User = Depends(require_permission("product_manage")),
    db: AsyncSession = Depends(get_async_db),
):
    """趋势数据"""
    return await mr_service.get_stats_trend(db, days)


@router.post("/items/{item_id}/receive", response_model=RegistrationDetailResponse)
async def receive_material(
    item_id: int,
    data: ReceiveMaterialRequest,
    user: User = Depends(require_permission("product_manage")),
    db: AsyncSession = Depends(get_async_db),
):
    """物料收货登记"""
    try:
        result = await mr_service.receive_material(db, item_id, data.received_quantity, data.remark)
        await db.commit()
        return {'success': True, 'message': '收货登记成功', 'registration': {}}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/purchase-orders/{order_id}/items")
async def get_purchase_order_items(
    order_id: int,
    user: User = Depends(require_permission("product_manage")),
    db: AsyncSession = Depends(get_async_db),
):
    """获取采购订单物料明细"""
    try:
        return await mr_service.get_purchase_order_items(db, order_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/purchase-orders/preview/{order_no}")
async def preview_purchase_order(
    order_no: str,
    user: User = Depends(require_permission("product_manage")),
    db: AsyncSession = Depends(get_async_db),
):
    """采购订单快速预览"""
    try:
        return await mr_service.preview_purchase_order(db, order_no)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/export")
async def export_registrations(
    order_no: str = '', supplier: str = '',
    start_date: str = '', end_date: str = '',
    user: User = Depends(require_permission("product_manage")),
    db: AsyncSession = Depends(get_async_db),
):
    """导出来料登记数据"""
    try:
        return await mr_service.export_registrations(db, order_no, supplier, start_date, end_date)
    except Exception as e:
        raise HTTPException(status_code=500, detail="导出来料登记失败")


@router.get("/history")
async def get_history(
    page: int = Query(1, ge=1), per_page: int = Query(20, ge=1, le=100),
    order_no: str = Query(''), supplier: str = Query(''),
    customer_name: str = Query(''), material_category: str = Query(''),
    start_date: str = Query(''), end_date: str = Query(''),
    user: User = Depends(require_permission("product_manage")),
    db: AsyncSession = Depends(get_async_db),
):
    """获取来料登记历史记录"""
    return await mr_service.get_history(
        db, page, per_page, order_no, supplier, customer_name,
        material_category, start_date, end_date
    )


@router.get("/suggestions")
async def get_suggestions(
    field: str = Query(''), keyword: str = Query(''), limit: int = Query(10, ge=1, le=50),
    user: User = Depends(require_permission("product_manage")),
    db: AsyncSession = Depends(get_async_db),
):
    """获取搜索联想建议"""
    return await mr_service.get_suggestions(db, field, keyword, limit)


@router.get("/stats/distribution")
async def stats_distribution(
    user: User = Depends(require_permission("product_manage")),
    db: AsyncSession = Depends(get_async_db),
):
    """获取来料登记状态分布"""
    return await mr_service.get_stats_distribution(db)
