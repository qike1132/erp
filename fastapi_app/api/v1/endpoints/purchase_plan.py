"""
采购计划管理 API 端点（重构版）

主从表结构路由，前缀 /api/v1/plans

职责：
    - 采购计划主单与明细的 CRUD
    - 月度日历、客户汇总、库存对比等报表查询
    - 出货进度追踪与流水记录同步
    - Excel 模板上传/下载与暂存区确认流程
    - 69 码校验
"""
import asyncio
import logging
import os
from typing import Any

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from sqlalchemy.exc import DisconnectionError, IntegrityError, OperationalError
from sqlalchemy.ext.asyncio import AsyncSession

from fastapi_app.core.config import settings
from fastapi_app.core.database import get_async_db, get_async_read_db
from fastapi_app.core.deps import get_user_identity, require_permission
from fastapi_app.core.exceptions import db_transaction
from fastapi_app.core.response import success_response
from fastapi_app.core.validators import require_upload_magic
from fastapi_app.schemas.purchase_plan import (
    AddDetailsRequest,
    BarcodeValidationResponse,
    ConfirmStagingRequest,
    CreatePlanResponse,
    CustomerSummaryResponse,
    InventoryCompareResponse,
    MonthlyAggregatedResponse,
    MonthlyCalendarResponse,
    PlanListResponse,
    PurchasePlanActionResponse,
    PurchasePlanCreate,
    PurchasePlanDetailResponse,
    PurchasePlanDetailUpdate,
    PurchasePlanStagingConfirmResponse,
    PurchasePlanStagingListResponse,
    PurchasePlanStagingValidateResponse,
    PurchasePlanUpdate,
    PurchasePlanUploadExcelResponse,
    ShipmentProgressResponse,
    ShipmentRecordsResponse,
)
from fastapi_app.services import purchase_plan_service
from fastapi_app.services.xlsx_budget import XlsxBudgetError
from fastapi_app.shared_models import User

# 上传 Excel 文件大小上限（10MB）
MAX_UPLOAD_FILE_SIZE = 10 * 1024 * 1024
# 月度日历/客户汇总查询超时阈值（秒）
MONTHLY_QUERY_TIMEOUT_SECONDS = 20

router = APIRouter()
logger = logging.getLogger(__name__)

@router.get('/list', response_model=PlanListResponse)
async def list_plans(year: int=Query(..., description='年份'), month: int=Query(..., ge=1, le=12, description='月份'), customer_id: int=Query(0, description='客户ID筛选'), status: str=Query('', description='状态筛选'), db: AsyncSession=Depends(get_async_read_db), _user: User=Depends(require_permission('production_plan_view'))) -> PlanListResponse:
    """采购计划主单列表。

    Args:
        year: 年份。
        month: 月份（1-12）。
        customer_id: 客户 ID 筛选，0 表示不筛选。
        status: 状态筛选，空串表示不筛选。
        db: 只读数据库会话。
        _user: 当前操作用户（用于权限校验）。

    Returns:
        PlanListResponse: 计划主单分页列表。

    Raises:
        HTTPException: 数据库异常时返回 500。
    """
    try:
        result = await purchase_plan_service.get_plan_list(db, year, month, customer_id, status)
        return PlanListResponse(plans=result['plans'], total=result['total'])
    except (OperationalError, DisconnectionError) as e:
        logger.error(f'获取计划列表失败: {e}', exc_info=True)
        raise HTTPException(status_code=500, detail=f'获取计划列表失败: {settings.sanitize_error(e)}') from e

@router.get('/detail/{plan_id}', response_model=PurchasePlanDetailResponse)
async def plan_detail(plan_id: int, db: AsyncSession=Depends(get_async_read_db), _user: User=Depends(require_permission('production_plan_view'))) -> dict[str, Any]:
    """获取主单+明细（含库存对比+出货进度）。

    Args:
        plan_id: 计划主单 ID。
        db: 只读数据库会话。
        _user: 当前操作用户（用于权限校验）。

    Returns:
        PurchasePlanDetailResponse: 计划详情（含明细、库存对比、出货进度）。

    Raises:
        HTTPException: 计划不存在返回 404；数据库异常返回 500。
    """
    try:
        return await purchase_plan_service.get_plan_detail(db, plan_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except (OperationalError, DisconnectionError) as e:
        logger.error(f'获取计划详情失败: {e}', exc_info=True)
        raise HTTPException(status_code=500, detail=f'获取计划详情失败: {settings.sanitize_error(e)}') from e

@router.post('/create', response_model=CreatePlanResponse)
async def create_plan(data: PurchasePlanCreate, db: AsyncSession=Depends(get_async_db), user: User=Depends(require_permission('production_plan_manage'))) -> dict[str, Any]:
    """创建采购计划主单+明细。

    事务模式：db_transaction + error_map 异常映射（commit/rollback/post-commit
    回调由 db_transaction 统一执行，端点只声明 HTTP 语义）。

    异常映射：
        - PlanExistsError（uq_ppl_month_customer 冲突）→ 409 "该客户当月已存在采购计划"
        - IntegrityError（仅理论上可达：detail INSERT 异常）→ 409 单号冲突
        - OperationalError/DisconnectionError → 500（detail 含脱敏错误信息）
        - ValueError（业务校验失败 / plan_no 冲突耗尽）→ 400（db_transaction 默认）

    Args:
        data: 采购计划创建请求体（含客户、计划月份、明细列表等）。
        db: 读写数据库会话。
        user: 当前操作用户。

    Returns:
        CreatePlanResponse: 创建结果（含生成的计划数据）。

    Raises:
        HTTPException: 业务校验失败返回 400；单号冲突返回 409；数据库异常返回 500。
    """
    from fastapi_app.services.purchase_plan_crud import PlanExistsError

    def _plan_exists(e: Exception) -> HTTPException:
        # 该客户当月已有计划：冲突不可重试，提示用户编辑现有计划
        logger.warning(f'创建计划被拒：{e}')
        return HTTPException(status_code=409, detail=str(e))

    def _plan_no_conflict(e: Exception) -> HTTPException:
        logger.error(f'创建计划单号冲突: {e}', exc_info=True)
        return HTTPException(status_code=409, detail='单号已存在，请勿重复提交')

    def _db_failure(e: Exception) -> HTTPException:
        logger.error(f'创建计划失败: {e}', exc_info=True)
        return HTTPException(status_code=500, detail=f'创建计划失败: {settings.sanitize_error(e)}')

    async with db_transaction(db, error_map={
        PlanExistsError: _plan_exists,
        IntegrityError: _plan_no_conflict,
        (OperationalError, DisconnectionError): _db_failure,
    }):
        _, created_by = get_user_identity(user)
        result = await purchase_plan_service.create_plan(db, customer_id=data.customer_id, customer_name=data.customer_name, plan_month=data.plan_month, details=[d.model_dump() for d in data.details], remark=data.remark, created_by=created_by)
    return success_response(data=result)

@router.put('/edit/{plan_id}', response_model=PurchasePlanActionResponse)
async def update_plan(plan_id: int, data: PurchasePlanUpdate, db: AsyncSession=Depends(get_async_db), user: User=Depends(require_permission('production_plan_manage'))) -> PurchasePlanActionResponse:
    """编辑采购计划主单。

    Args:
        plan_id: 计划主单 ID。
        data: 主单更新请求体。
        db: 读写数据库会话。
        user: 当前操作用户。

    Returns:
        PurchasePlanActionResponse: 操作结果。
    """
    async with db_transaction(db):
        _, created_by = get_user_identity(user)
        await purchase_plan_service.update_plan(db, plan_id, created_by=created_by, **data.model_dump(exclude_unset=True))
    return PurchasePlanActionResponse(success=True, message='更新成功')

@router.delete('/delete/{plan_id}', response_model=PurchasePlanActionResponse)
async def delete_plan(plan_id: int, db: AsyncSession=Depends(get_async_db), user: User=Depends(require_permission('production_plan_manage'))) -> PurchasePlanActionResponse:
    """删除采购计划。

    Args:
        plan_id: 计划主单 ID。
        db: 读写数据库会话。
        user: 当前操作用户。

    Returns:
        PurchasePlanActionResponse: 操作结果。
    """
    async with db_transaction(db):
        _, operator = get_user_identity(user)
        await purchase_plan_service.delete_plan(db, plan_id, operator=operator)
    return PurchasePlanActionResponse(success=True, message='删除成功')

@router.put('/details/{detail_id}', response_model=PurchasePlanActionResponse)
async def update_detail(detail_id: int, data: PurchasePlanDetailUpdate, db: AsyncSession=Depends(get_async_db), user: User=Depends(require_permission('production_plan_manage'))) -> PurchasePlanActionResponse:
    """编辑明细。

    Args:
        detail_id: 明细 ID。
        data: 明细更新请求体。
        db: 读写数据库会话。
        user: 当前操作用户。

    Returns:
        PurchasePlanActionResponse: 操作结果。
    """
    async with db_transaction(db):
        _, created_by = get_user_identity(user)
        await purchase_plan_service.update_detail(db, detail_id, created_by=created_by, **data.model_dump(exclude_unset=True))
    return PurchasePlanActionResponse(success=True, message='明细更新成功')

@router.delete('/details/{detail_id}', response_model=PurchasePlanActionResponse)
async def delete_detail(detail_id: int, db: AsyncSession=Depends(get_async_db), _user: User=Depends(require_permission('production_plan_manage'))) -> PurchasePlanActionResponse:
    """删除明细。

    Args:
        detail_id: 明细 ID。
        db: 读写数据库会话。
        _user: 当前操作用户（用于权限校验）。

    Returns:
        PurchasePlanActionResponse: 操作结果。
    """
    async with db_transaction(db):
        await purchase_plan_service.delete_detail(db, detail_id)
    return PurchasePlanActionResponse(success=True, message='明细删除成功')

@router.post('/details/add', response_model=PurchasePlanActionResponse)
async def add_details(data: AddDetailsRequest, plan_id: int=Query(..., description='主单ID'), db: AsyncSession=Depends(get_async_db), _user: User=Depends(require_permission('production_plan_manage'))) -> PurchasePlanActionResponse:
    """向主单追加明细。

    Args:
        data: 追加明细请求体（含明细列表）。
        plan_id: 主单 ID。
        db: 读写数据库会话。
        _user: 当前操作用户（用于权限校验）。

    Returns:
        PurchasePlanActionResponse: 操作结果（含追加条数）。
    """
    async with db_transaction(db):
        result = await purchase_plan_service.add_details(db, plan_id, [d.model_dump() for d in data.details])
    return PurchasePlanActionResponse(success=True, message=f"追加{result['added_count']}条明细")

@router.get('/monthly', response_model=MonthlyCalendarResponse)
async def monthly_calendar(year: int=Query(..., description='年份'), month: int=Query(..., ge=1, le=12, description='月份'), customer_id: int=Query(0, description='客户ID筛选'), db: AsyncSession=Depends(get_async_read_db), _user: User=Depends(require_permission('production_plan_view'))) -> MonthlyCalendarResponse:
    """月度日历数据（按日期聚合，供CSS Grid渲染）。

    Args:
        year: 年份。
        month: 月份（1-12）。
        customer_id: 客户 ID 筛选，0 表示不筛选。
        db: 只读数据库会话。
        _user: 当前操作用户（用于权限校验）。

    Returns:
        MonthlyCalendarResponse: 月度日历聚合数据（含客户图标 URL）。

    Raises:
        HTTPException: 数据库异常返回 500；查询超时返回 504。
    """
    import time as _t
    _t0 = _t.perf_counter()
    try:
        async with asyncio.timeout(MONTHLY_QUERY_TIMEOUT_SECONDS):
            # S2: icon_url 查询已下沉到 service 层 _enrich_customer_icon_urls
            result = await purchase_plan_service.get_monthly_calendar(db, year, month, customer_id)
        logger.info(f'[PERF] monthly_calendar query took {(_t.perf_counter()-_t0)*1000:.0f}ms')
        return result
    except (OperationalError, DisconnectionError) as e:
        logger.error(f'获取月度日历数据失败: {e}', exc_info=True)
        raise HTTPException(status_code=500, detail=f'获取月度数据失败: {settings.sanitize_error(e)}') from e
    except TimeoutError:
        logger.error(f'获取月度日历数据超时: year={year} month={month}')
        raise HTTPException(status_code=504, detail='获取月度数据超时，请稍后重试') from None
    except Exception as e:  # defensive: 未预期异常统一返回 500，避免内部信息泄露
        logger.error(f'获取月度日历数据异常: {e}', exc_info=True)
        raise HTTPException(status_code=500, detail='获取月度数据失败，请稍后重试') from e

@router.get('/customer-summary', response_model=CustomerSummaryResponse)
async def customer_summary(year: int=Query(..., description='年份'), month: int=Query(..., ge=1, le=12, description='月份'), db: AsyncSession=Depends(get_async_read_db), _user: User=Depends(require_permission('production_plan_view'))) -> CustomerSummaryResponse:
    """客户汇总统计。

    Args:
        year: 年份。
        month: 月份（1-12）。
        db: 只读数据库会话。
        _user: 当前操作用户（用于权限校验）。

    Returns:
        CustomerSummaryResponse: 客户汇总统计数据。

    Raises:
        HTTPException: 数据库异常返回 500；查询超时返回 504。
    """
    try:
        async with asyncio.timeout(MONTHLY_QUERY_TIMEOUT_SECONDS):
            return await purchase_plan_service.get_customer_summary(db, year, month)
    except (OperationalError, DisconnectionError) as e:
        logger.error(f'获取客户汇总失败: {e}', exc_info=True)
        raise HTTPException(status_code=500, detail=f'获取汇总数据失败: {settings.sanitize_error(e)}') from e
    except TimeoutError:
        logger.error(f'获取客户汇总超时: year={year} month={month}')
        raise HTTPException(status_code=504, detail='获取汇总数据超时，请稍后重试') from None
    except Exception as e:  # defensive: 未预期异常统一返回 500，避免内部信息泄露
        logger.error(f'获取客户汇总异常: {e}', exc_info=True)
        raise HTTPException(status_code=500, detail='获取汇总数据失败，请稍后重试') from e

@router.get('/monthly-aggregated', response_model=MonthlyAggregatedResponse)
async def monthly_aggregated(year: int=Query(..., description='年份'), month: int=Query(..., ge=1, le=12, description='月份'), customer_id: int=Query(0, description='客户ID筛选'), db: AsyncSession=Depends(get_async_read_db), _user: User=Depends(require_permission('production_plan_view'))) -> MonthlyAggregatedResponse:
    """月度聚合数据（6.9+6.10：后端完成 rows/sku_summary/sku_date_index/customers 聚合，不传输全量明细）。

    Args:
        year: 年份。
        month: 月份（1-12）。
        customer_id: 客户 ID 筛选，0 表示不筛选。
        db: 只读数据库会话。
        _user: 当前操作用户（用于权限校验）。

    Returns:
        MonthlyAggregatedResponse: 月度聚合数据（含客户汇总，替代 monthly + customer-summary 两个接口）。

    Raises:
        HTTPException: 数据库异常返回 500；查询超时返回 504。
    """
    import time as _t
    _t0 = _t.perf_counter()
    try:
        async with asyncio.timeout(MONTHLY_QUERY_TIMEOUT_SECONDS):
            result = await purchase_plan_service.get_monthly_aggregated(db, year, month, customer_id)
        logger.info(f'[PERF] monthly_aggregated query took {(_t.perf_counter()-_t0)*1000:.0f}ms')
        return result
    except (OperationalError, DisconnectionError) as e:
        logger.error(f'获取月度聚合数据失败: {e}', exc_info=True)
        raise HTTPException(status_code=500, detail=f'获取月度数据失败: {settings.sanitize_error(e)}') from e
    except TimeoutError:
        logger.error(f'获取月度聚合数据超时: year={year} month={month}')
        raise HTTPException(status_code=504, detail='获取月度数据超时，请稍后重试') from None
    except Exception as e:  # broad-except: 端点兜底转 500 且不泄漏内部细节（DB/超时已在上方单独捕获）
        logger.error(f'获取月度聚合数据异常: {e}', exc_info=True)
        raise HTTPException(status_code=500, detail='获取月度数据失败，请稍后重试') from e

@router.get('/inventory-compare', response_model=InventoryCompareResponse)
async def inventory_compare(year: int=Query(..., description='年份'), month: int=Query(..., ge=1, le=12, description='月份'), customer_id: int=Query(0, description='客户ID筛选'), db: AsyncSession=Depends(get_async_read_db), _user: User=Depends(require_permission('production_plan_view'))) -> dict[str, Any]:
    """库存对比数据。

    Args:
        year: 年份。
        month: 月份（1-12）。
        customer_id: 客户 ID 筛选，0 表示不筛选。
        db: 只读数据库会话。
        _user: 当前操作用户（用于权限校验）。

    Returns:
        InventoryCompareResponse: 库存对比数据。

    Raises:
        HTTPException: 数据库异常返回 500。
    """
    try:
        return await purchase_plan_service.get_inventory_compare(db, year, month, customer_id)
    except (OperationalError, DisconnectionError) as e:
        logger.error(f'获取库存对比失败: {e}', exc_info=True)
        raise HTTPException(status_code=500, detail=f'获取库存对比失败: {settings.sanitize_error(e)}') from e

@router.get('/shipment/progress', response_model=ShipmentProgressResponse)
async def shipment_progress(plan_id: int=Query(..., description='计划主单ID'), db: AsyncSession=Depends(get_async_read_db), _user: User=Depends(require_permission('production_plan_view'))) -> dict[str, Any]:
    """出货进度追踪。

    Args:
        plan_id: 计划主单 ID。
        db: 只读数据库会话。
        _user: 当前操作用户（用于权限校验）。

    Returns:
        ShipmentProgressResponse: 出货进度数据。

    Raises:
        HTTPException: 计划不存在返回 404；数据库异常返回 500。
    """
    try:
        return await purchase_plan_service.get_shipment_progress(db, plan_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except (OperationalError, DisconnectionError) as e:
        logger.error(f'获取出货进度失败: {e}', exc_info=True)
        raise HTTPException(status_code=500, detail=f'获取出货进度失败: {settings.sanitize_error(e)}') from e

@router.get('/shipment/records-by-date', response_model=ShipmentRecordsResponse)
async def shipment_records_by_date(date: str=Query(..., description='查询日期 YYYY-MM-DD'), db: AsyncSession=Depends(get_async_read_db), _user: User=Depends(require_permission('production_plan_view'))) -> dict[str, Any]:
    """S1 批量端点：按日期查询所有相关出货流水记录

    替代前端按 plan_id 分块 N+1 请求的模式。
    一次查询返回当日所有客户+产品的出货记录，前端按 shipment_no 去重即可。

    Args:
        date: 查询日期 YYYY-MM-DD。
        db: 只读数据库会话。
        _user: 当前操作用户（用于权限校验）。

    Returns:
        ShipmentRecordsResponse: 出货流水记录列表。

    Raises:
        HTTPException: 日期格式错误返回 400；数据库异常返回 500。
    """
    try:
        records = await purchase_plan_service.get_shipment_records_by_date(db, date)
        return {'records': records}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except (OperationalError, DisconnectionError) as e:
        logger.error(f'按日期获取出货流水失败: {e}', exc_info=True)
        raise HTTPException(status_code=500, detail=f'获取出货流水失败: {settings.sanitize_error(e)}') from e

@router.post('/upload', response_model=PurchasePlanUploadExcelResponse)
async def upload_excel(file: UploadFile=File(..., description='Excel文件'), db: AsyncSession=Depends(get_async_db), _user: User=Depends(require_permission('production_plan_manage'))) -> dict[str, Any]:
    """上传Excel文件，解析到暂存表。

    Args:
        file: 上传的 Excel 文件（仅支持 .xlsx）。
        db: 读写数据库会话。
        _user: 当前操作用户（用于权限校验）。

    Returns:
        PurchasePlanUploadExcelResponse: 上传解析结果。

    Raises:
        HTTPException: 文件格式或大小不合法返回 400。
    """
    # 安全校验：文件类型和大小限制
    if not file.filename or not file.filename.endswith('.xlsx'):
        raise HTTPException(status_code=400, detail='仅支持 .xlsx 格式文件，.xls 已不再支持')
    content = await file.read()
    if len(content) > MAX_UPLOAD_FILE_SIZE:
        raise HTTPException(status_code=400, detail='文件大小不能超过10MB')
    # P0-12 同类上传端点均已校验文件头，本端点此前漏加：改名成 .xlsx 的非 Excel 文件
    # 会直接进入解析器（下游多落为 500）。此处补齐，与 production_plan/summary 等口径一致。
    require_upload_magic(content, ('xlsx', 'xlsm'), filename=file.filename)
    session_id, created_by = get_user_identity(_user)
    try:
        async with db_transaction(db):
            result = await purchase_plan_service.upload_excel(db, content, session_id, created_by)
    except XlsxBudgetError as e:
        # M5 评审 finding 3：资源预算拒绝必须落成 400 友好报错，而不是全局 handler 的 500
        raise HTTPException(status_code=400, detail=str(e)) from e
    return success_response(**{**result})

@router.get('/staging/list', response_model=PurchasePlanStagingListResponse)
async def staging_list(db: AsyncSession=Depends(get_async_read_db), _user: User=Depends(require_permission('production_plan_manage'))) -> dict[str, Any]:
    """获取暂存区预览数据。

    Args:
        db: 只读数据库会话。
        _user: 当前操作用户（用于权限校验，同时用于隔离暂存区）。

    Returns:
        PurchasePlanStagingListResponse: 暂存区记录列表。
    """
    session_id, _ = get_user_identity(_user)
    records = await purchase_plan_service.get_staging_list(db, session_id)
    return success_response(data=records, total=len(records))

@router.post('/staging/validate', response_model=PurchasePlanStagingValidateResponse)
async def staging_validate(db: AsyncSession=Depends(get_async_db), _user: User=Depends(require_permission('production_plan_manage'))) -> dict[str, Any]:
    """触发暂存数据验证。

    Args:
        db: 读写数据库会话。
        _user: 当前操作用户（用于权限校验，同时用于隔离暂存区）。

    Returns:
        PurchasePlanStagingValidateResponse: 验证结果。
    """
    session_id, _ = get_user_identity(_user)
    async with db_transaction(db):
        result = await purchase_plan_service.validate_staging(db, session_id)
    return success_response(**{**result})

@router.post('/staging/confirm', response_model=PurchasePlanStagingConfirmResponse)
async def staging_confirm(data: ConfirmStagingRequest, db: AsyncSession=Depends(get_async_db), user: User=Depends(require_permission('production_plan_manage'))) -> dict[str, Any]:
    """确认暂存数据，批量写入正式表。

    事务模式：db_transaction + error_map 异常映射（commit/rollback/post-commit
    回调由 db_transaction 统一执行）。

    Args:
        data: 确认请求体（含 batch_id 与 selected_ids）。
        db: 读写数据库会话。
        user: 当前操作用户。

    Returns:
        PurchasePlanStagingConfirmResponse: 确认结果。

    Raises:
        HTTPException: 单号冲突返回 409；业务校验失败返回 400。
    """
    session_id, created_by = get_user_identity(user)

    def _confirm_no_conflict(e: Exception) -> HTTPException:
        logger.error(f'确认计划单号冲突: {e}')
        return HTTPException(status_code=409, detail='单号已存在，请勿重复提交')

    async with db_transaction(db, error_map={IntegrityError: _confirm_no_conflict}):
        result = await purchase_plan_service.confirm_staging(db, session_id, batch_id=data.batch_id, created_by=created_by, selected_ids=data.selected_ids)
    return success_response(**{**result})

@router.delete('/staging/clear', response_model=PurchasePlanActionResponse)
async def staging_clear(db: AsyncSession=Depends(get_async_db), _user: User=Depends(require_permission('production_plan_manage'))) -> dict[str, Any]:
    """清空暂存区。

    Args:
        db: 读写数据库会话。
        _user: 当前操作用户（用于权限校验，同时用于隔离暂存区）。

    Returns:
        PurchasePlanActionResponse: 操作结果。
    """
    session_id, _ = get_user_identity(_user)
    async with db_transaction(db):
        await purchase_plan_service.clear_staging(db, session_id)
    return success_response(message='暂存区已清空')

@router.get('/validate-barcode', response_model=BarcodeValidationResponse)
async def validate_barcode(q: str=Query(..., min_length=1, description='69码'), db: AsyncSession=Depends(get_async_read_db), _user: User=Depends(require_permission('production_plan_manage'))) -> BarcodeValidationResponse:
    """验证69码。

    Args:
        q: 待验证的 69 码字符串。
        db: 只读数据库会话。
        _user: 当前操作用户（用于权限校验）。

    Returns:
        BarcodeValidationResponse: 验证结果。
    """
    result = await purchase_plan_service.validate_barcode(db, q)
    return BarcodeValidationResponse(**result)

@router.get('/template/download')
async def download_template(_user: User=Depends(require_permission('production_plan_manage'))):
    """下载出货计划导入模板。

    Args:
        _user: 当前操作用户（用于权限校验）。

    Returns:
        Response: Excel 文件流（含 Content-Disposition 头）。

    Raises:
        HTTPException: 模板文件不存在返回 404；读取失败返回 500。
    """
    from urllib.parse import quote

    from fastapi.responses import Response

    template_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))), 'static', 'files', 'purchase_order_template.xlsx')
    if not os.path.exists(template_path):
        raise HTTPException(status_code=404, detail='模板文件不存在')
    try:

        def _read_file():
            with open(template_path, 'rb') as f:
                return f.read()
        file_content = await asyncio.to_thread(_read_file)
        if not file_content:
            raise HTTPException(status_code=500, detail='模板文件为空')
        filename = '出货计划导入模板.xlsx'
        encoded_filename = quote(filename)
        return Response(content=file_content, media_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', headers={'Content-Disposition': f"attachment; filename*=UTF-8''{encoded_filename}", 'Content-Length': str(len(file_content)), 'Cache-Control': 'no-cache, no-store, must-revalidate'})
    except HTTPException:
        raise
    except (OSError, ValueError) as e:
        logger.error('模板读取失败: %s', e, exc_info=True)
        raise HTTPException(status_code=500, detail='模板读取失败') from e
