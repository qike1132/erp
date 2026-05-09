"""
采购计划管理 API 端点（重构版）

主从表结构路由，前缀 /api/v1/plans
"""
import asyncio
import calendar
import logging
from datetime import date as date_type

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import RedirectResponse
from sqlalchemy.exc import DisconnectionError, IntegrityError, OperationalError
from sqlalchemy.ext.asyncio import AsyncSession

from fastapi_app.core.config import settings
from fastapi_app.core.database import get_async_db, get_async_read_db
from fastapi_app.core.deps import get_user_identity, require_permission
from fastapi_app.schemas.purchase_plan import (
    AddDetailsRequest,
    BarcodeValidationResponse,
    ConfirmStagingRequest,
    CustomerSummaryResponse,
    InventoryCompareResponse,
    PlanListResponse,
    PurchasePlanActionResponse,
    PurchasePlanCreate,
    PurchasePlanDetailUpdate,
    PurchasePlanUpdate,
    ShipmentProgressResponse,
    SyncShipmentRequest,
)
from fastapi_app.services import purchase_plan_service
from fastapi_app.shared_models import Customer, User

router = APIRouter()
logger = logging.getLogger(__name__)

@router.get('/list', response_model=PlanListResponse)
async def list_plans(year: int=Query(..., description='年份'), month: int=Query(..., ge=1, le=12, description='月份'), customer_id: int=Query(0, description='客户ID筛选'), status: str=Query('', description='状态筛选'), db: AsyncSession=Depends(get_async_read_db), _user: User=Depends(require_permission('production_plan_view'))):
    """采购计划主单列表"""
    try:
        result = await purchase_plan_service.get_plan_list(db, year, month, customer_id, status)
        return PlanListResponse(plans=result['plans'], total=result['total'])
    except (OperationalError, DisconnectionError) as e:
        logger.error(f'获取计划列表失败: {e}', exc_info=True)
        raise HTTPException(status_code=500, detail=f'获取计划列表失败: {settings.sanitize_error(e)}') from e

@router.get('/detail/{plan_id}')
async def plan_detail(plan_id: int, db: AsyncSession=Depends(get_async_read_db), _user: User=Depends(require_permission('production_plan_view'))):
    """获取主单+明细（含库存对比+出货进度）"""
    try:
        return await purchase_plan_service.get_plan_detail(db, plan_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except (OperationalError, DisconnectionError) as e:
        logger.error(f'获取计划详情失败: {e}', exc_info=True)
        raise HTTPException(status_code=500, detail=f'获取计划详情失败: {settings.sanitize_error(e)}') from e

@router.post('/create')
async def create_plan(data: PurchasePlanCreate, db: AsyncSession=Depends(get_async_db), user: User=Depends(require_permission('production_plan_manage'))):
    """创建采购计划主单+明细"""
    try:
        _, created_by = get_user_identity(user)
        result = await purchase_plan_service.create_plan(db, customer_id=data.customer_id, customer_name=data.customer_name, plan_month=data.plan_month, details=[d.model_dump() for d in data.details], remark=data.remark, created_by=created_by)
        return {'success': True, 'data': result}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except IntegrityError as e:
        logger.error(f'创建计划单号冲突: {e}')
        raise HTTPException(status_code=409, detail='单号已存在，请勿重复提交') from e
    except (OperationalError, DisconnectionError) as e:
        logger.error(f'创建计划失败: {e}', exc_info=True)
        raise HTTPException(status_code=500, detail=f'创建计划失败: {settings.sanitize_error(e)}') from e

@router.put('/edit/{plan_id}', response_model=PurchasePlanActionResponse)
async def update_plan(plan_id: int, data: PurchasePlanUpdate, db: AsyncSession=Depends(get_async_db), user: User=Depends(require_permission('production_plan_manage'))):
    """编辑采购计划主单"""
    try:
        _, created_by = get_user_identity(user)
        await purchase_plan_service.update_plan(db, plan_id, created_by=created_by, **data.model_dump(exclude_unset=True))
        return PurchasePlanActionResponse(success=True, message='更新成功')
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

@router.delete('/delete/{plan_id}', response_model=PurchasePlanActionResponse)
async def delete_plan(plan_id: int, db: AsyncSession=Depends(get_async_db), user: User=Depends(require_permission('production_plan_manage'))):
    """删除采购计划"""
    try:
        _, operator = get_user_identity(user)
        await purchase_plan_service.delete_plan(db, plan_id, operator=operator)
        return PurchasePlanActionResponse(success=True, message='删除成功')
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

@router.put('/details/{detail_id}', response_model=PurchasePlanActionResponse)
async def update_detail(detail_id: int, data: PurchasePlanDetailUpdate, db: AsyncSession=Depends(get_async_db), user: User=Depends(require_permission('production_plan_manage'))):
    """编辑明细"""
    try:
        _, created_by = get_user_identity(user)
        await purchase_plan_service.update_detail(db, detail_id, created_by=created_by, **data.model_dump(exclude_unset=True))
        return PurchasePlanActionResponse(success=True, message='明细更新成功')
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

@router.delete('/details/{detail_id}', response_model=PurchasePlanActionResponse)
async def delete_detail(detail_id: int, db: AsyncSession=Depends(get_async_db), _user: User=Depends(require_permission('production_plan_manage'))):
    """删除明细"""
    try:
        await purchase_plan_service.delete_detail(db, detail_id)
        return PurchasePlanActionResponse(success=True, message='明细删除成功')
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

@router.post('/details/add', response_model=PurchasePlanActionResponse)
async def add_details(data: AddDetailsRequest, plan_id: int=Query(..., description='主单ID'), db: AsyncSession=Depends(get_async_db), _user: User=Depends(require_permission('production_plan_manage'))):
    """向主单追加明细"""
    try:
        result = await purchase_plan_service.add_details(db, plan_id, [d.model_dump() for d in data.details])
        return PurchasePlanActionResponse(success=True, message=f"追加{result['added_count']}条明细")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

@router.get('/monthly')
async def monthly_calendar(year: int=Query(..., description='年份'), month: int=Query(..., ge=1, le=12, description='月份'), customer_id: int=Query(0, description='客户ID筛选'), db: AsyncSession=Depends(get_async_read_db), _user: User=Depends(require_permission('production_plan_view'))):
    """月度日历数据（按日期聚合，供CSS Grid渲染）"""
    try:
        async with asyncio.timeout(20):
            result = await purchase_plan_service.get_monthly_calendar(db, year, month, customer_id)
        # 补充客户图标URL：服务层仅返回客户id/name，图标需额外查询Customer表
        customer_ids = [c['id'] for c in result['customers']]
        if customer_ids:
            from sqlalchemy import select as sa_select
            c_result = await db.execute(sa_select(Customer).where(Customer.id.in_(customer_ids)))
            c_map = {c.id: c for c in c_result.scalars().all()}
            for c in result['customers']:
                c_obj = c_map.get(c['id'])
                if c_obj:
                    c['icon_url'] = c_obj.icon_url or ''
        return result
    except (OperationalError, DisconnectionError) as e:
        logger.error(f'获取月度日历数据失败: {e}', exc_info=True)
        raise HTTPException(status_code=500, detail=f'获取月度数据失败: {settings.sanitize_error(e)}') from e
    except asyncio.TimeoutError:
        logger.error(f'获取月度日历数据超时: year={year} month={month}')
        raise HTTPException(status_code=504, detail='获取月度数据超时，请稍后重试') from None
    except Exception as e:
        logger.error(f'获取月度日历数据异常: {e}', exc_info=True)
        raise HTTPException(status_code=500, detail='获取月度数据失败，请稍后重试') from e

@router.get('/customer-summary', response_model=CustomerSummaryResponse)
async def customer_summary(year: int=Query(..., description='年份'), month: int=Query(..., ge=1, le=12, description='月份'), db: AsyncSession=Depends(get_async_read_db), _user: User=Depends(require_permission('production_plan_view'))):
    """客户汇总统计"""
    try:
        async with asyncio.timeout(20):
            return await purchase_plan_service.get_customer_summary(db, year, month)
    except (OperationalError, DisconnectionError) as e:
        logger.error(f'获取客户汇总失败: {e}', exc_info=True)
        raise HTTPException(status_code=500, detail=f'获取汇总数据失败: {settings.sanitize_error(e)}') from e
    except asyncio.TimeoutError:
        logger.error(f'获取客户汇总超时: year={year} month={month}')
        raise HTTPException(status_code=504, detail='获取汇总数据超时，请稍后重试') from None
    except Exception as e:
        logger.error(f'获取客户汇总异常: {e}', exc_info=True)
        raise HTTPException(status_code=500, detail='获取汇总数据失败，请稍后重试') from e

@router.get('/inventory-compare', response_model=InventoryCompareResponse)
async def inventory_compare(year: int=Query(..., description='年份'), month: int=Query(..., ge=1, le=12, description='月份'), customer_id: int=Query(0, description='客户ID筛选'), db: AsyncSession=Depends(get_async_read_db), _user: User=Depends(require_permission('production_plan_view'))):
    """库存对比数据"""
    try:
        return await purchase_plan_service.get_inventory_compare(db, year, month, customer_id)
    except (OperationalError, DisconnectionError) as e:
        logger.error(f'获取库存对比失败: {e}', exc_info=True)
        raise HTTPException(status_code=500, detail=f'获取库存对比失败: {settings.sanitize_error(e)}') from e

@router.get('/shipment/progress', response_model=ShipmentProgressResponse)
async def shipment_progress(plan_id: int=Query(..., description='计划主单ID'), db: AsyncSession=Depends(get_async_read_db), _user: User=Depends(require_permission('production_plan_view'))):
    """出货进度追踪"""
    try:
        return await purchase_plan_service.get_shipment_progress(db, plan_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except (OperationalError, DisconnectionError) as e:
        logger.error(f'获取出货进度失败: {e}', exc_info=True)
        raise HTTPException(status_code=500, detail=f'获取出货进度失败: {settings.sanitize_error(e)}') from e

@router.get('/shipment/records')
async def shipment_records(plan_id: int=Query(..., description='计划主单ID'), db: AsyncSession=Depends(get_async_read_db), _user: User=Depends(require_permission('production_plan_view'))):
    """获取指定计划的出货流水记录"""
    try:
        records = await purchase_plan_service.get_shipment_records(db, plan_id)
        return {'records': records}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except (OperationalError, DisconnectionError) as e:
        logger.error(f'获取出货流水失败: {e}', exc_info=True)
        raise HTTPException(status_code=500, detail=f'获取出货流水失败: {settings.sanitize_error(e)}') from e

@router.post('/shipment/sync')
async def shipment_sync(data: SyncShipmentRequest, db: AsyncSession=Depends(get_async_db), _user: User=Depends(require_permission('production_plan_manage'))):
    """手动触发出货数据同步"""
    try:
        start = date_type(data.year, data.month, 1)
        end = date_type(data.year, data.month, calendar.monthrange(data.year, data.month)[1])
        total_synced = 0
        current = start
        while current <= end:
            result = await purchase_plan_service.sync_shipment_records(db, current)
            total_synced += result['synced_count']
            current = date_type.fromordinal(current.toordinal() + 1)
        return {'success': True, 'synced_count': total_synced}
    except (OperationalError, DisconnectionError) as e:
        logger.error(f'出货同步失败: {e}', exc_info=True)
        raise HTTPException(status_code=500, detail=f'出货同步失败: {settings.sanitize_error(e)}') from e

@router.post('/upload')
async def upload_excel(file: UploadFile=File(..., description='Excel文件'), db: AsyncSession=Depends(get_async_db), _user: User=Depends(require_permission('production_plan_manage'))):
    """上传Excel文件，解析到暂存表"""
    # 安全校验：文件类型和大小限制
    if not file.filename.endswith('.xlsx'):
        raise HTTPException(status_code=400, detail='仅支持 .xlsx 格式文件，.xls 已不再支持')
    content = await file.read()
    if len(content) > 10 * 1024 * 1024:
        raise HTTPException(status_code=400, detail='文件大小不能超过10MB')
    session_id, created_by = get_user_identity(_user)
    try:
        result = await purchase_plan_service.upload_excel(db, content, session_id, created_by)
        return {'success': True, **result}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

@router.get('/staging/list')
async def staging_list(db: AsyncSession=Depends(get_async_read_db), _user: User=Depends(require_permission('production_plan_manage'))):
    """获取暂存区预览数据"""
    session_id, _ = get_user_identity(_user)
    records = await purchase_plan_service.get_staging_list(db, session_id)
    return {'success': True, 'data': records, 'total': len(records)}

@router.post('/staging/validate')
async def staging_validate(db: AsyncSession=Depends(get_async_db), _user: User=Depends(require_permission('production_plan_manage'))):
    """触发暂存数据验证"""
    session_id, _ = get_user_identity(_user)
    result = await purchase_plan_service.validate_staging(db, session_id)
    return {'success': True, **result}

@router.post('/staging/confirm')
async def staging_confirm(data: ConfirmStagingRequest, db: AsyncSession=Depends(get_async_db), user: User=Depends(require_permission('production_plan_manage'))):
    """确认暂存数据，批量写入正式表"""
    session_id, created_by = get_user_identity(user)
    try:
        result = await purchase_plan_service.confirm_staging(db, session_id, batch_id=data.batch_id, created_by=created_by, selected_ids=data.selected_ids)
        return {'success': True, **result}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except IntegrityError as e:
        logger.error(f'确认计划单号冲突: {e}')
        raise HTTPException(status_code=409, detail='单号已存在，请勿重复提交') from e

@router.delete('/staging/clear')
async def staging_clear(db: AsyncSession=Depends(get_async_db), _user: User=Depends(require_permission('production_plan_manage'))):
    """清空暂存区"""
    session_id, _ = get_user_identity(_user)
    await purchase_plan_service.clear_staging(db, session_id)
    return {'success': True, 'message': '暂存区已清空'}

@router.get('/validate-barcode', response_model=BarcodeValidationResponse)
async def validate_barcode(q: str=Query(..., min_length=1, description='69码'), db: AsyncSession=Depends(get_async_read_db), _user: User=Depends(require_permission('production_plan_manage'))):
    """验证69码"""
    result = await purchase_plan_service.validate_barcode(db, q)
    return BarcodeValidationResponse(**result)

@router.get('/template/download')
async def download_template(_user: User=Depends(require_permission('production_plan_manage'))):
    """下载Excel上传模板（重定向到Flask路由）"""
    return RedirectResponse(url='/plans/template', status_code=307)
