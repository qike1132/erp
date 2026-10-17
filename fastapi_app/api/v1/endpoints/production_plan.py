"""
采购计划管理 API 端点

提供排产计划的增删改查、批量上传预览、库存对比、出货进度、时间轴等功能。

职责：
- 提供排产计划的增删改查接口
- 提供时间轴、客户汇总统计接口
- 提供 69 码验证接口
- 提供 Excel 批量上传、暂存区预览/验证/确认/清空接口
"""
from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from sqlalchemy.exc import DisconnectionError, OperationalError
from sqlalchemy.ext.asyncio import AsyncSession

from fastapi_app.core.config import settings
from fastapi_app.core.database import get_async_db, get_async_read_db
from fastapi_app.core.deps import get_user_identity, require_permission
from fastapi_app.core.exceptions import db_transaction
from fastapi_app.core.response import success_response
from fastapi_app.core.validators import require_upload_magic
from fastapi_app.schemas.production_plan import (
    BarcodeValidationResponse,
    MonthlySummary,
    ProductionPlanActionResponse,
    ProductionPlanCreate,
    ProductionPlanListResponse,
    ProductionPlanUpdate,
    StagingConfirmResponse,
    StagingListResponse,
    StagingValidateResponse,
    TimelineResponse,
    UploadExcelResponse,
)
from fastapi_app.services import production_plan_service
from fastapi_app.shared_models import User

router = APIRouter()

# Excel 上传文件大小上限（10MB）
MAX_UPLOAD_FILE_SIZE = 10 * 1024 * 1024


@router.get('/list', response_model=ProductionPlanListResponse)
async def list_plans(
    year: int = Query(..., description='年份'),
    month: int = Query(..., ge=1, le=12, description='月份'),
    customer: str = Query('', max_length=100, description='客户名称筛选'),
    db: AsyncSession = Depends(get_async_read_db),
    _user: User = Depends(require_permission('production_plan_view')),
) -> ProductionPlanListResponse:
    """排产计划列表（含库存对比+出货进度数据）。

    Args:
        year: 年份。
        month: 月份，1-12。
        customer: 客户名称筛选关键字。
        db: 异步数据库会话（只读副本）。
        _user: 当前登录用户（仅需通过权限校验）。

    Returns:
        ProductionPlanListResponse: 包含计划列表、月度汇总和总数的响应。

    Raises:
        HTTPException: 数据库连接异常时抛出 500。
    """
    try:
        result = await production_plan_service.get_plans_with_inventory(db, year, month, customer)
        return ProductionPlanListResponse(
            plans=result['plans'], monthly_summary=result['monthly_summary'], total=result['total'],
        )
    except (OperationalError, DisconnectionError) as e:
        raise HTTPException(status_code=500, detail=f'获取排产计划失败: {settings.sanitize_error(e)}') from e


@router.post('/create', response_model=ProductionPlanActionResponse)
async def create_plan(
    data: ProductionPlanCreate,
    db: AsyncSession = Depends(get_async_db),
    user: User = Depends(require_permission('production_plan_manage')),
) -> ProductionPlanActionResponse:
    """创建排产计划。

    Args:
        data: 排产计划创建参数（客户、产品、条码、数量、日期等）。
        db: 异步数据库会话（读写主库）。
        user: 当前登录用户，作为创建人。

    Returns:
        ProductionPlanActionResponse: 包含成功标志和提示消息的响应。
    """
    async with db_transaction(db):
        _, created_by = get_user_identity(user)
        await production_plan_service.create_plan(
            db, customer_name=data.customer_name, product_name=data.product_name,
            barcode=data.barcode, quantity=data.quantity, plan_date_str=data.plan_date,
            remark=data.remark or '', created_by=created_by,
        )
    return ProductionPlanActionResponse(success=True, message='排产计划创建成功！')


@router.put('/edit/{plan_id}', response_model=ProductionPlanActionResponse)
async def update_plan(
    plan_id: int,
    data: ProductionPlanUpdate,
    db: AsyncSession = Depends(get_async_db),
    user: User = Depends(require_permission('production_plan_manage')),
) -> ProductionPlanActionResponse:
    """编辑排产计划。

    Args:
        plan_id: 排产计划 ID。
        data: 排产计划更新参数（仅包含需要修改的字段）。
        db: 异步数据库会话（读写主库）。
        user: 当前登录用户，作为操作人。

    Returns:
        ProductionPlanActionResponse: 包含成功标志和提示消息的响应。
    """
    async with db_transaction(db):
        update_data = data.model_dump(exclude_unset=True)
        _, created_by = get_user_identity(user)
        await production_plan_service.update_plan(db, plan_id, created_by=created_by, **update_data)
    return ProductionPlanActionResponse(success=True, message='排产计划更新成功！')


@router.delete('/delete/{plan_id}', response_model=ProductionPlanActionResponse)
async def delete_plan(
    plan_id: int,
    db: AsyncSession = Depends(get_async_db),
    user: User = Depends(require_permission('production_plan_manage')),
) -> ProductionPlanActionResponse:
    """删除排产计划。

    Args:
        plan_id: 排产计划 ID。
        db: 异步数据库会话（读写主库）。
        user: 当前登录用户，作为操作人。

    Returns:
        ProductionPlanActionResponse: 包含成功标志和提示消息的响应。
    """
    async with db_transaction(db):
        _, operator = get_user_identity(user)
        await production_plan_service.delete_plan(db, plan_id, operator=operator)
    return ProductionPlanActionResponse(success=True, message='排产计划删除成功！')


@router.get('/timeline', response_model=TimelineResponse)
async def timeline(
    year: int = Query(..., description='年份'),
    month: int = Query(..., ge=1, le=12, description='月份'),
    customer: str = Query('', max_length=100, description='客户名称筛选'),
    db: AsyncSession = Depends(get_async_read_db),
    _user: User = Depends(require_permission('production_plan_view')),
) -> TimelineResponse:
    """时间轴数据（按日期+客户维度，用于日历热力图）。

    Args:
        year: 年份。
        month: 月份，1-12。
        customer: 客户名称筛选关键字。
        db: 异步数据库会话（只读副本）。
        _user: 当前登录用户（仅需通过权限校验）。

    Returns:
        TimelineResponse: 包含时间轴数据的响应。

    Raises:
        HTTPException: 数据库连接异常时抛出 500。
    """
    try:
        return TimelineResponse(**await production_plan_service.get_timeline(db, year, month, customer))
    except (OperationalError, DisconnectionError) as e:
        raise HTTPException(status_code=500, detail=f'获取时间轴数据失败: {settings.sanitize_error(e)}') from e


@router.get('/customer-summary', response_model=MonthlySummary)
async def customer_summary(
    year: int = Query(..., description='年份'),
    month: int = Query(..., ge=1, le=12, description='月份'),
    db: AsyncSession = Depends(get_async_read_db),
    _user: User = Depends(require_permission('production_plan_view')),
) -> MonthlySummary:
    """客户汇总统计。

    Args:
        year: 年份。
        month: 月份，1-12。
        db: 异步数据库会话（只读副本）。
        _user: 当前登录用户（仅需通过权限校验）。

    Returns:
        MonthlySummary: 包含客户汇总数据的响应。

    Raises:
        HTTPException: 数据库连接异常时抛出 500。
    """
    try:
        return MonthlySummary(**await production_plan_service.get_customer_summary(db, year, month))
    except (OperationalError, DisconnectionError) as e:
        raise HTTPException(status_code=500, detail=f'获取汇总数据失败: {settings.sanitize_error(e)}') from e


@router.get('/validate-barcode', response_model=BarcodeValidationResponse)
async def validate_barcode(
    q: str = Query(..., min_length=1, description='69码'),
    db: AsyncSession = Depends(get_async_read_db),
    _user: User = Depends(require_permission('production_plan_manage')),
) -> BarcodeValidationResponse:
    """验证69码，返回关联的产品信息。

    Args:
        q: 待验证的 69 码。
        db: 异步数据库会话（只读副本）。
        _user: 当前登录用户（仅需通过权限校验）。

    Returns:
        BarcodeValidationResponse: 包含验证结果和产品信息的响应。
    """
    result = await production_plan_service.validate_barcode(db, q)
    return BarcodeValidationResponse(**result)


@router.post('/upload', response_model=UploadExcelResponse)
async def upload_excel(
    file: UploadFile = File(..., description='Excel文件'),
    db: AsyncSession = Depends(get_async_db),
    _user: User = Depends(require_permission('production_plan_manage')),
) -> UploadExcelResponse:
    """上传Excel文件，解析到暂存表。

    对上传文件进行格式与大小校验后，解析 Excel 并写入暂存表。

    Args:
        file: 上传的 Excel 文件（.xlsx 格式）。
        db: 异步数据库会话（读写主库）。
        _user: 当前登录用户，用于构造用户隔离的会话标识。

    Returns:
        UploadExcelResponse: 包含上传结果的响应。

    Raises:
        HTTPException: 文件格式不支持或大小超限时抛出 400。
    """
    filename = file.filename or ''
    if not filename.endswith('.xlsx'):
        raise HTTPException(status_code=400, detail='仅支持 .xlsx 格式文件，.xls 已不再支持')
    try:
        content = await file.read()
    except (OSError, ValueError) as e:
        raise HTTPException(status_code=400, detail=f'文件读取失败: {settings.sanitize_error(e)}') from e
    if len(content) > MAX_UPLOAD_FILE_SIZE:
        raise HTTPException(status_code=400, detail='文件大小不能超过10MB')
    # P0-12：扩展名之外再校验文件头（.xls 改名 .xlsx、任意文件改名 .xlsx 都拦在这里）
    require_upload_magic(content, ('xlsx', 'xlsm'), filename=file.filename or '')
    session_id, _ = get_user_identity(_user)
    async with db_transaction(db):
        result = await production_plan_service.upload_excel(db, content, session_id)
    return UploadExcelResponse(**success_response(**{**result}))


@router.get('/staging/list', response_model=StagingListResponse)
async def staging_list(
    db: AsyncSession = Depends(get_async_read_db),
    _user: User = Depends(require_permission('production_plan_manage')),
) -> StagingListResponse:
    """获取暂存区预览数据。

    Args:
        db: 异步数据库会话（只读副本）。
        _user: 当前登录用户，用于构造用户隔离的会话标识。

    Returns:
        StagingListResponse: 包含暂存区数据和总数的响应。
    """
    session_id, _ = get_user_identity(_user)
    records = await production_plan_service.get_staging_list(db, session_id)
    return StagingListResponse(**success_response(data=records, total=len(records)))


@router.post('/staging/validate', response_model=StagingValidateResponse)
async def staging_validate(
    db: AsyncSession = Depends(get_async_db),
    _user: User = Depends(require_permission('production_plan_manage')),
) -> StagingValidateResponse:
    """触发暂存数据验证。

    Args:
        db: 异步数据库会话（读写主库）。
        _user: 当前登录用户，用于构造用户隔离的会话标识。

    Returns:
        StagingValidateResponse: 包含验证结果的响应。
    """
    session_id, _ = get_user_identity(_user)
    result = await production_plan_service.validate_staging(db, session_id)
    return StagingValidateResponse(**success_response(**{**result}))


@router.post('/staging/confirm', response_model=StagingConfirmResponse)
async def staging_confirm(
    batch_id: str = Query('', max_length=100, description='批次ID，空则确认该会话全部'),
    db: AsyncSession = Depends(get_async_db),
    user: User = Depends(require_permission('production_plan_manage')),
) -> StagingConfirmResponse:
    """确认暂存数据，批量写入正式表。

    Args:
        batch_id: 批次 ID，为空则确认该会话全部数据。
        db: 异步数据库会话（读写主库）。
        user: 当前登录用户，作为操作人。

    Returns:
        StagingConfirmResponse: 包含确认结果的响应。
    """
    session_id, created_by = get_user_identity(user)
    async with db_transaction(db):
        result = await production_plan_service.confirm_staging(
            db, session_id, batch_id=batch_id, created_by=created_by,
        )
    return StagingConfirmResponse(**success_response(**{**result}))


@router.delete('/staging/clear', response_model=ProductionPlanActionResponse)
async def staging_clear(
    db: AsyncSession = Depends(get_async_db),
    _user: User = Depends(require_permission('production_plan_manage')),
) -> ProductionPlanActionResponse:
    """清空暂存区。

    Args:
        db: 异步数据库会话（读写主库）。
        _user: 当前登录用户，用于构造用户隔离的会话标识。

    Returns:
        ProductionPlanActionResponse: 包含成功标志和提示消息的响应。
    """
    session_id, _ = get_user_identity(_user)
    # 2026-10-17 审计 P2-22：同文件其余写端点都在 db_transaction 内，唯独此处裸调，
    # 失败时事务边界不明确（与统一提交口径不一致）。
    async with db_transaction(db):
        await production_plan_service.clear_staging(db, session_id)
    return ProductionPlanActionResponse(**success_response(message='暂存区已清空'))
