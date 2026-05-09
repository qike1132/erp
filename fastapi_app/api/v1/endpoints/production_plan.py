"""
采购计划管理 API 端点

提供排产计划的增删改查、批量上传预览、库存对比、出货进度、时间轴等功能。
"""
from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from sqlalchemy.exc import DisconnectionError, OperationalError
from sqlalchemy.ext.asyncio import AsyncSession

from fastapi_app.core.config import settings
from fastapi_app.core.database import get_async_db, get_async_read_db
from fastapi_app.core.deps import get_user_identity, require_permission
from fastapi_app.schemas.production_plan import (
    BarcodeValidationResponse,
    ProductionPlanActionResponse,
    ProductionPlanCreate,
    ProductionPlanListResponse,
    ProductionPlanUpdate,
)
from fastapi_app.services import production_plan_service
from fastapi_app.shared_models import User

router = APIRouter()

@router.get('/list', response_model=ProductionPlanListResponse)
async def list_plans(year: int=Query(..., description='年份'), month: int=Query(..., ge=1, le=12, description='月份'), customer: str=Query('', description='客户名称筛选'), db: AsyncSession=Depends(get_async_read_db), _user: User=Depends(require_permission('production_plan_view'))):
    """排产计划列表（含库存对比+出货进度数据）"""
    try:
        result = await production_plan_service.get_plans_with_inventory(db, year, month, customer)
        return ProductionPlanListResponse(plans=result['plans'], monthly_summary=result['monthly_summary'], total=result['total'])
    except (OperationalError, DisconnectionError) as e:
        raise HTTPException(status_code=500, detail=f'获取排产计划失败: {settings.sanitize_error(e)}') from e

@router.post('/create', response_model=ProductionPlanActionResponse)
async def create_plan(data: ProductionPlanCreate, db: AsyncSession=Depends(get_async_db), user: User=Depends(require_permission('production_plan_manage'))):
    """创建排产计划"""
    try:
        _, created_by = get_user_identity(user)
        await production_plan_service.create_plan(db, customer_name=data.customer_name, product_name=data.product_name, barcode=data.barcode, quantity=data.quantity, plan_date_str=data.plan_date, remark=data.remark or '', created_by=created_by)
        return ProductionPlanActionResponse(success=True, message='排产计划创建成功！')
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

@router.put('/edit/{plan_id}', response_model=ProductionPlanActionResponse)
async def update_plan(plan_id: int, data: ProductionPlanUpdate, db: AsyncSession=Depends(get_async_db), user: User=Depends(require_permission('production_plan_manage'))):
    """编辑排产计划"""
    try:
        update_data = data.model_dump(exclude_unset=True)
        _, created_by = get_user_identity(user)
        await production_plan_service.update_plan(db, plan_id, created_by=created_by, **update_data)
        return ProductionPlanActionResponse(success=True, message='排产计划更新成功！')
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

@router.delete('/delete/{plan_id}', response_model=ProductionPlanActionResponse)
async def delete_plan(plan_id: int, db: AsyncSession=Depends(get_async_db), user: User=Depends(require_permission('production_plan_manage'))):
    """删除排产计划"""
    try:
        _, operator = get_user_identity(user)
        await production_plan_service.delete_plan(db, plan_id, operator=operator)
        return ProductionPlanActionResponse(success=True, message='排产计划删除成功！')
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

@router.get('/timeline')
async def timeline(year: int=Query(..., description='年份'), month: int=Query(..., ge=1, le=12, description='月份'), customer: str=Query('', description='客户名称筛选'), db: AsyncSession=Depends(get_async_read_db), _user: User=Depends(require_permission('production_plan_view'))):
    """时间轴数据（按日期+客户维度，用于日历热力图）"""
    try:
        return await production_plan_service.get_timeline(db, year, month, customer)
    except (OperationalError, DisconnectionError) as e:
        raise HTTPException(status_code=500, detail=f'获取时间轴数据失败: {settings.sanitize_error(e)}') from e

@router.get('/customer-summary')
async def customer_summary(year: int=Query(..., description='年份'), month: int=Query(..., ge=1, le=12, description='月份'), db: AsyncSession=Depends(get_async_read_db), _user: User=Depends(require_permission('production_plan_view'))):
    """客户汇总统计"""
    try:
        return await production_plan_service.get_customer_summary(db, year, month)
    except (OperationalError, DisconnectionError) as e:
        raise HTTPException(status_code=500, detail=f'获取汇总数据失败: {settings.sanitize_error(e)}') from e

@router.get('/validate-barcode', response_model=BarcodeValidationResponse)
async def validate_barcode(q: str=Query(..., min_length=1, description='69码'), db: AsyncSession=Depends(get_async_read_db), _user: User=Depends(require_permission('production_plan_manage'))):
    """验证69码，返回关联的产品信息"""
    result = await production_plan_service.validate_barcode(db, q)
    return BarcodeValidationResponse(**result)

@router.post('/upload')
async def upload_excel(file: UploadFile=File(..., description='Excel文件'), db: AsyncSession=Depends(get_async_db), _user: User=Depends(require_permission('production_plan_manage'))):
    """上传Excel文件，解析到暂存表"""
    if not file.filename.endswith('.xlsx'):
        raise HTTPException(status_code=400, detail='仅支持 .xlsx 格式文件，.xls 已不再支持')
    try:
        content = await file.read()
    except (OSError, ValueError) as e:
        raise HTTPException(status_code=400, detail=f'文件读取失败: {settings.sanitize_error(e)}') from e
    if len(content) > 10 * 1024 * 1024:
        raise HTTPException(status_code=400, detail='文件大小不能超过10MB')
    session_id, _ = get_user_identity(_user)
    try:
        result = await production_plan_service.upload_excel(db, content, session_id)
        return {'success': True, **result}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

@router.get('/staging/list')
async def staging_list(db: AsyncSession=Depends(get_async_read_db), _user: User=Depends(require_permission('production_plan_manage'))):
    """获取暂存区预览数据"""
    session_id, _ = get_user_identity(_user)
    records = await production_plan_service.get_staging_list(db, session_id)
    return {'success': True, 'data': records, 'total': len(records)}

@router.post('/staging/validate')
async def staging_validate(db: AsyncSession=Depends(get_async_db), _user: User=Depends(require_permission('production_plan_manage'))):
    """触发暂存数据验证"""
    session_id, _ = get_user_identity(_user)
    result = await production_plan_service.validate_staging(db, session_id)
    return {'success': True, **result}

@router.post('/staging/confirm')
async def staging_confirm(batch_id: str=Query('', description='批次ID，空则确认该会话全部'), db: AsyncSession=Depends(get_async_db), user: User=Depends(require_permission('production_plan_manage'))):
    """确认暂存数据，批量写入正式表"""
    session_id, created_by = get_user_identity(user)
    try:
        result = await production_plan_service.confirm_staging(db, session_id, batch_id=batch_id, created_by=created_by)
        return {'success': True, **result}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

@router.delete('/staging/clear')
async def staging_clear(db: AsyncSession=Depends(get_async_db), _user: User=Depends(require_permission('production_plan_manage'))):
    """清空暂存区"""
    session_id, _ = get_user_identity(_user)
    await production_plan_service.clear_staging(db, session_id)
    return {'success': True, 'message': '暂存区已清空'}
