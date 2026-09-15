"""
每日生产报表 API 端点

统一三部门（充棉部、手工部、包装部）的 CRUD、每日汇总、月度汇总、导出。

职责：
- 提供生产记录的增删改查接口
- 提供按日、按月的汇总统计接口
- 提供生产报表 Excel 导出接口
- 提供产品信息查询接口（用于生产记录录入时获取 SKU 详情）
"""
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import Response
from sqlalchemy.exc import DisconnectionError, OperationalError
from sqlalchemy.ext.asyncio import AsyncSession

from fastapi_app.core.config import settings
from fastapi_app.core.database import get_async_db, get_async_read_db
from fastapi_app.core.deps import require_permission
from fastapi_app.core.exceptions import db_transaction
from fastapi_app.core.limiter import limiter
from fastapi_app.core.response import success_response
from fastapi_app.schemas.daily_production import (
    DailySummaryResponse,
    MonthlySummaryResponse,
    ProductInfoResponse,
    ProductionRecordActionResponse,
    ProductionRecordCreate,
    ProductionRecordListResponse,
    ProductionRecordUpdate,
)
from fastapi_app.services import daily_production_service
from fastapi_app.shared_models import User

router = APIRouter()


@router.get('/records', response_model=ProductionRecordListResponse)
async def list_records(
    year: int = Query(..., description='年份'),
    month: int = Query(..., ge=1, le=12, description='月份'),
    department: str = Query('', description='部门筛选 (filling/handcraft/packaging)'),
    production_date: str = Query('', description='指定日期筛选 (YYYY-MM-DD)'),
    page: int = Query(1, ge=1, description='页码'),
    per_page: int = Query(50, ge=1, le=200, description='每页数量'),
    db: AsyncSession = Depends(get_async_read_db),
    _user: User = Depends(require_permission('production_summary_view')),
) -> ProductionRecordListResponse:
    """获取生产记录列表（支持按年月、部门、日期筛选和分页）。

    Args:
        year: 年份。
        month: 月份，1-12。
        department: 部门筛选（filling=充棉部/handcraft=手工部/packaging=包装部）。
        production_date: 指定日期筛选（YYYY-MM-DD）。
        page: 页码，从 1 开始。
        per_page: 每页数量，1-200。
        db: 异步数据库会话（只读副本）。
        _user: 当前登录用户（仅需通过权限校验）。

    Returns:
        ProductionRecordListResponse: 包含生产记录列表、分页信息和统计数据的响应。

    Raises:
        HTTPException: 数据库连接异常时抛出 500。
    """
    try:
        result = await daily_production_service.get_records(
            db, year=year, month=month, department=department, production_date=production_date,
            page=page, per_page=per_page,
        )
        return ProductionRecordListResponse(
            data=result['data'], total=result['total'],
            page=result['page'], per_page=result['per_page'],
            pages=result['pages'], stats=result.get('stats'),
        )
    except (OperationalError, DisconnectionError) as e:
        raise HTTPException(status_code=500, detail=f'获取数据失败: {settings.sanitize_error(e)}') from e


@router.post('/records', response_model=ProductionRecordActionResponse)
async def create_record(
    data: ProductionRecordCreate,
    db: AsyncSession = Depends(get_async_db),
    user: User = Depends(require_permission('production_summary_manage')),
) -> ProductionRecordActionResponse:
    """创建生产记录。

    Args:
        data: 生产记录创建参数（部门、产品、条码、单价、数量、日期等）。
        db: 异步数据库会话（读写主库）。
        user: 当前登录用户，作为记录创建人。

    Returns:
        ProductionRecordActionResponse: 包含成功标志和提示消息的响应。
    """
    async with db_transaction(db):
        await daily_production_service.create_record(
            db,
            department=data.department,
            product_id=data.product_id,
            product_name=data.product_name,
            barcode=data.barcode,
            unit_price=data.unit_price,
            quantity=data.quantity,
            production_date_str=data.production_date,
            remark=data.remark or '',
            created_by=user.username if hasattr(user, 'username') else '',
        )
    return ProductionRecordActionResponse(success=True, message='生产记录创建成功')


@router.put('/records/{record_id}', response_model=ProductionRecordActionResponse)
async def update_record(
    record_id: int,
    data: ProductionRecordUpdate,
    db: AsyncSession = Depends(get_async_db),
    user: User = Depends(require_permission('production_summary_manage')),
) -> ProductionRecordActionResponse:
    """更新生产记录。

    Args:
        record_id: 生产记录 ID。
        data: 生产记录更新参数（仅包含需要修改的字段）。
        db: 异步数据库会话（读写主库）。
        user: 当前登录用户，作为操作人。

    Returns:
        ProductionRecordActionResponse: 包含成功标志和提示消息的响应。
    """
    async with db_transaction(db):
        update_data = data.model_dump(exclude_unset=True)
        await daily_production_service.update_record(
            db, record_id, created_by=user.username if hasattr(user, 'username') else '', **update_data
        )
    return ProductionRecordActionResponse(success=True, message='生产记录更新成功')


@router.delete('/records/{record_id}', response_model=ProductionRecordActionResponse)
async def delete_record(
    record_id: int,
    db: AsyncSession = Depends(get_async_db),
    _user: User = Depends(require_permission('production_summary_manage')),
) -> ProductionRecordActionResponse:
    """删除生产记录。

    Args:
        record_id: 生产记录 ID。
        db: 异步数据库会话（读写主库）。
        _user: 当前登录用户（仅需通过权限校验）。

    Returns:
        ProductionRecordActionResponse: 包含成功标志和提示消息的响应。
    """
    async with db_transaction(db):
        await daily_production_service.delete_record(db, record_id)
    return ProductionRecordActionResponse(success=True, message='生产记录删除成功')


@router.get('/daily-summary', response_model=DailySummaryResponse)
async def daily_summary(
    date: str = Query(..., description='日期 (YYYY-MM-DD)'),
    db: AsyncSession = Depends(get_async_read_db),
    _user: User = Depends(require_permission('production_summary_view')),
) -> DailySummaryResponse:
    """获取当日生产汇总。

    Args:
        date: 查询日期（YYYY-MM-DD）。
        db: 异步数据库会话（只读副本）。
        _user: 当前登录用户（仅需通过权限校验）。

    Returns:
        DailySummaryResponse: 包含当日汇总数据的响应。

    Raises:
        HTTPException: 日期格式错误时抛出 400。
    """
    try:
        result = await daily_production_service.get_daily_summary(db, date)
        return DailySummaryResponse(**result)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.get('/monthly-summary', response_model=MonthlySummaryResponse)
async def monthly_summary(
    year: int = Query(..., description='年份'),
    month: int = Query(..., ge=1, le=12, description='月份'),
    db: AsyncSession = Depends(get_async_read_db),
    _user: User = Depends(require_permission('production_summary_view')),
) -> MonthlySummaryResponse:
    """获取月度生产汇总。

    Args:
        year: 年份。
        month: 月份，1-12。
        db: 异步数据库会话（只读副本）。
        _user: 当前登录用户（仅需通过权限校验）。

    Returns:
        MonthlySummaryResponse: 包含月度汇总数据的响应。

    Raises:
        HTTPException: 数据库连接异常时抛出 500。
    """
    try:
        result = await daily_production_service.get_monthly_summary(db, year, month)
        return MonthlySummaryResponse(**result)
    except (OperationalError, DisconnectionError) as e:
        raise HTTPException(status_code=500, detail=f'获取汇总失败: {settings.sanitize_error(e)}') from e


@router.get('/export')
@limiter.limit("100/minute")  # 内网宽松：导出接口取消严格限流
async def export_records(
    request: Request,
    start_date: str = Query('', description='起始日期 (YYYY-MM-DD)'),
    end_date: str = Query('', description='结束日期 (YYYY-MM-DD)'),
    department: str = Query('', description='部门筛选 (filling/handcraft/packaging)'),
    db: AsyncSession = Depends(get_async_read_db),
    _user: User = Depends(require_permission('production_summary_view')),
) -> Response:
    """导出生产报表为 Excel。

    Args:
        start_date: 起始日期（YYYY-MM-DD）。
        end_date: 结束日期（YYYY-MM-DD）。
        department: 部门筛选（filling/handcraft/packaging）。
        db: 异步数据库会话（只读副本）。
        _user: 当前登录用户（仅需通过权限校验）。

    Returns:
        Response: Excel 文件流响应。

    Raises:
        HTTPException: 数据库连接异常时抛出 500。
    """
    try:
        content = await daily_production_service.export_records(
            db, start_date=start_date, end_date=end_date, department=department
        )
        return Response(
            content=content,
            media_type='application/vnd.openxmlformats-officedocument.spreadsheetml.xlsx',
            headers={'Content-Disposition': 'attachment; filename=production_report.xlsx'},
        )
    except ValueError as e:
        # 服务层行数上界保护：超限时引导用户缩小筛选范围（批次 2）
        raise HTTPException(status_code=413, detail=str(e)) from e
    except (OperationalError, DisconnectionError) as e:
        raise HTTPException(status_code=500, detail=f'导出失败: {settings.sanitize_error(e)}') from e


@router.get('/product-info/{product_id}', response_model=ProductInfoResponse)
async def get_product_info(
    product_id: int,
    db: AsyncSession = Depends(get_async_read_db),
    _user: User = Depends(require_permission('production_summary_view')),
) -> ProductInfoResponse:
    """获取产品信息（用于生产记录时从产品清单获取SKU详情）。

    Args:
        product_id: 产品 ID。
        db: 异步数据库会话（只读副本）。
        _user: 当前登录用户（仅需通过权限校验）。

    Returns:
        ProductInfoResponse: 包含产品信息的响应。

    Raises:
        HTTPException: 产品不存在时抛出 404；数据库连接异常时抛出 500。
    """
    try:
        product = await daily_production_service.get_product_for_production(db, product_id)
        if not product:
            raise HTTPException(status_code=404, detail='产品不存在')
        return success_response(data=product)
    except (OperationalError, DisconnectionError) as e:
        raise HTTPException(status_code=500, detail=f'获取产品信息失败: {settings.sanitize_error(e)}') from e
