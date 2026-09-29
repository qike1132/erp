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
from fastapi_app.core.deps import (
    get_current_user_with_permissions,
    require_permission,
    resolve_production_view_scope,
    resolve_production_write_scope,
)
from fastapi_app.core.exceptions import db_transaction
from fastapi_app.core.limiter import limiter
from fastapi_app.core.production_scope import narrow_departments
from fastapi_app.core.response import success_response
from fastapi_app.schemas.daily_production import (
    DailySummaryResponse,
    MonthlySummaryResponse,
    ProductInfoResponse,
    ProductionRecordActionResponse,
    ProductionRecordCreate,
    ProductionRecordListResponse,
    ProductionRecordUpdate,
    TrendResponse,
)
from fastapi_app.services import daily_production_service
from fastapi_app.services.daily_production_service import InvalidDateRangeError
from fastapi_app.shared_models import User

router = APIRouter()


def _assert_department_writable(department: str, scope: set[str] | None) -> None:
    """校验部门是否在用户可写范围内。

    Raises:
        HTTPException: 403 —— scope 非 None 且部门不在其中。
    """
    if scope is not None and department not in scope:
        raise HTTPException(
            status_code=403,
            detail=f'无权操作该部门（{department}）的生产数据',
        )


@router.get('/records', response_model=ProductionRecordListResponse)
async def list_records(
    year: int | None = Query(None, description='年份；未提供区间时必填'),
    month: int | None = Query(None, ge=1, le=12, description='月份；未提供区间时必填'),
    start_date: str = Query('', description='区间起始日 (YYYY-MM-DD)，与 end_date 成对'),
    end_date: str = Query('', description='区间结束日 (YYYY-MM-DD)，闭区间'),
    department: str = Query('', description='部门筛选 (filling/handcraft/packaging)'),
    production_date: str = Query('', description='指定日期筛选 (YYYY-MM-DD)'),
    created_by: str = Query('', description='录单人筛选；留空为不限'),
    sort: str = Query('desc', description="排序：desc（最新在前，默认）或 asc"),
    page: int = Query(1, ge=1, description='页码'),
    per_page: int = Query(50, ge=1, le=200, description='每页数量'),
    scope: set[str] | None = Depends(resolve_production_view_scope),
    db: AsyncSession = Depends(get_async_read_db),
) -> ProductionRecordListResponse:
    """获取生产记录列表（支持按自然月或日期区间、部门、录单人筛选与分页）。

    Args:
        year: 年份；与 month 搭配。提供区间时忽略。
        month: 月份，1-12。提供区间时忽略。
        start_date: 区间起始日；与 end_date 必须成对。
        end_date: 区间结束日（闭区间）。
        department: 部门筛选；超出用户可见范围时忽略该参数。
        production_date: 指定日期筛选，叠加在日期条件之上。
        created_by: 录单人筛选；空白表示不限。
        sort: 排序方向，'desc' 或 'asc'。
        page: 页码。
        per_page: 每页数量，1-200。
        scope: 用户可见部门范围（None 表示全部）。
        db: 异步数据库会话（只读副本）。

    Returns:
        ProductionRecordListResponse: 记录列表 + 分页信息 + 当前筛选下的统计。

    Raises:
        HTTPException: 400（日期条件或 sort 非法）、500（数据库异常）。
    """
    try:
        conditions_scope = narrow_departments(department, scope)
        result = await daily_production_service.get_records(
            db,
            year=year,
            month=month,
            departments=conditions_scope,
            start_date=start_date,
            end_date=end_date,
            created_by=created_by,
            sort=sort,
            page=page,
            per_page=per_page,
            production_date=production_date,
        )
        return ProductionRecordListResponse(
            data=result['data'], total=result['total'],
            page=result['page'], per_page=result['per_page'],
            pages=result['pages'], stats=result.get('stats'),
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except (OperationalError, DisconnectionError) as e:
        raise HTTPException(status_code=500, detail=f'获取数据失败: {settings.sanitize_error(e)}') from e


@router.post('/records', response_model=ProductionRecordActionResponse)
async def create_record(
    data: ProductionRecordCreate,
    scope: set[str] | None = Depends(resolve_production_write_scope),
    user: User = Depends(get_current_user_with_permissions),
    db: AsyncSession = Depends(get_async_db),
) -> ProductionRecordActionResponse:
    """创建生产记录。

    Args:
        data: 生产记录创建参数（部门、产品、条码、单价、数量、日期等）。
        scope: 用户可写部门范围（None 表示全部）。
        user: 当前登录用户，作为记录创建人。
        db: 异步数据库会话（读写主库）。

    Returns:
        ProductionRecordActionResponse: 包含成功标志和提示消息的响应。

    Raises:
        HTTPException: 403（部门越权）。
    """
    _assert_department_writable(data.department, scope)
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
    scope: set[str] | None = Depends(resolve_production_write_scope),
    user: User = Depends(get_current_user_with_permissions),
    db: AsyncSession = Depends(get_async_db),
) -> ProductionRecordActionResponse:
    """更新生产记录。

    Args:
        record_id: 生产记录 ID。
        data: 生产记录更新参数（仅包含需要修改的字段）。
        scope: 用户可写部门范围（None 表示全部）。
        user: 当前登录用户，作为操作人。
        db: 异步数据库会话（读写主库）。

    Returns:
        ProductionRecordActionResponse: 包含成功标志和提示消息的响应。

    Raises:
        HTTPException: 404（记录不存在）、403（原部门或目标部门越权）。
    """
    async with db_transaction(db):
        record = await daily_production_service.get_record(db, record_id)
        if record is None:
            raise HTTPException(status_code=404, detail='记录不存在')
        # 原部门与目标部门都必须可写：既不能改别部门的数据，
        # 也不能把自己的数据「搬」到无权写入的部门
        _assert_department_writable(record.department, scope)
        if data.department is not None:
            _assert_department_writable(data.department, scope)
        update_data = data.model_dump(exclude_unset=True)
        await daily_production_service.update_record(
            db, record_id, created_by=user.username if hasattr(user, 'username') else '', **update_data
        )
    return ProductionRecordActionResponse(success=True, message='生产记录更新成功')


@router.delete('/records/{record_id}', response_model=ProductionRecordActionResponse)
async def delete_record(
    record_id: int,
    scope: set[str] | None = Depends(resolve_production_write_scope),
    user: User = Depends(get_current_user_with_permissions),
    db: AsyncSession = Depends(get_async_db),
) -> ProductionRecordActionResponse:
    """删除生产记录（不可恢复）。

    Args:
        record_id: 生产记录 ID。
        scope: 用户可写部门范围（None 表示全部）。
        user: 当前登录用户，作为操作人写入审计日志。
        db: 异步数据库会话（读写主库）。

    Returns:
        ProductionRecordActionResponse: 包含成功标志和提示消息的响应。

    Raises:
        HTTPException: 404（记录不存在）、403（部门越权）。
    """
    operator = user.username if hasattr(user, 'username') else ''
    async with db_transaction(db):
        record = await daily_production_service.get_record(db, record_id)
        if record is None:
            raise HTTPException(status_code=404, detail='记录不存在')
        _assert_department_writable(record.department, scope)
        await daily_production_service.delete_record(db, record_id, operator=operator)
    return ProductionRecordActionResponse(success=True, message='生产记录删除成功')


@router.get('/daily-summary', response_model=DailySummaryResponse)
async def daily_summary(
    date: str = Query(..., description='日期 (YYYY-MM-DD)'),
    scope: set[str] | None = Depends(resolve_production_view_scope),
    db: AsyncSession = Depends(get_async_read_db),
) -> DailySummaryResponse:
    """获取当日生产汇总。

    Args:
        date: 查询日期（YYYY-MM-DD）。
        scope: 用户可见部门范围（None 表示全部）。
        db: 异步数据库会话（只读副本）。

    Returns:
        DailySummaryResponse: 包含当日汇总数据的响应。

    Raises:
        HTTPException: 日期格式错误时抛出 400。
    """
    try:
        result = await daily_production_service.get_daily_summary(db, date, departments=scope)
        return DailySummaryResponse(**result)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.get('/monthly-summary', response_model=MonthlySummaryResponse)
async def monthly_summary(
    year: int = Query(..., description='年份'),
    month: int = Query(..., ge=1, le=12, description='月份'),
    scope: set[str] | None = Depends(resolve_production_view_scope),
    db: AsyncSession = Depends(get_async_read_db),
) -> MonthlySummaryResponse:
    """获取月度生产汇总。

    Args:
        year: 年份。
        month: 月份，1-12。
        scope: 用户可见部门范围（None 表示全部）。
        db: 异步数据库会话（只读副本）。

    Returns:
        MonthlySummaryResponse: 包含月度汇总数据的响应。

    Raises:
        HTTPException: 数据库连接异常时抛出 500。
    """
    try:
        result = await daily_production_service.get_monthly_summary(
            db, year, month, departments=scope,
        )
        return MonthlySummaryResponse(**result)
    except (OperationalError, DisconnectionError) as e:
        raise HTTPException(status_code=500, detail=f'获取汇总失败: {settings.sanitize_error(e)}') from e


@router.get('/trend', response_model=TrendResponse)
async def trend(
    start_date: str = Query(..., description='起始日期 (YYYY-MM-DD)'),
    end_date: str = Query(..., description='结束日期 (YYYY-MM-DD)'),
    department: str = Query('', description='部门筛选 (filling/handcraft/packaging)'),
    scope: set[str] | None = Depends(resolve_production_view_scope),
    db: AsyncSession = Depends(get_async_read_db),
) -> TrendResponse:
    """获取按日按部门的生产数量趋势（可跨月，最长 92 天）。

    Args:
        start_date: 起始日期。
        end_date: 结束日期（闭区间）。
        department: 部门筛选；超出用户可见范围时忽略该参数。
        scope: 用户可见部门范围（None 表示全部）。
        db: 异步数据库会话（只读副本）。

    Returns:
        TrendResponse: 含 departments 与逐日补零后的 days。

    Raises:
        HTTPException: 400（区间非法）、500（数据库异常）。
    """
    try:
        result = await daily_production_service.get_trend(
            db,
            start_date=start_date,
            end_date=end_date,
            departments=narrow_departments(department, scope),
        )
        return TrendResponse(**result)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except (OperationalError, DisconnectionError) as e:
        raise HTTPException(status_code=500, detail=f'获取趋势失败: {settings.sanitize_error(e)}') from e


@router.get('/export')
@limiter.limit("100/minute")  # 内网宽松：导出接口取消严格限流
async def export_records(
    request: Request,
    start_date: str = Query('', description='起始日期 (YYYY-MM-DD)'),
    end_date: str = Query('', description='结束日期 (YYYY-MM-DD)'),
    department: str = Query('', description='部门筛选 (filling/handcraft/packaging)'),
    scope: set[str] | None = Depends(resolve_production_view_scope),
    db: AsyncSession = Depends(get_async_read_db),
) -> Response:
    """导出生产报表为 Excel。

    Args:
        start_date: 起始日期（YYYY-MM-DD）。
        end_date: 结束日期（YYYY-MM-DD）。
        department: 部门筛选；超出用户可见范围时忽略该参数。
        scope: 用户可见部门范围（None 表示全部）。
        db: 异步数据库会话（只读副本）。

    Returns:
        Response: Excel 文件流响应。

    Raises:
        HTTPException: 数据库连接异常时抛出 500。
    """
    try:
        content = await daily_production_service.export_records(
            db,
            start_date=start_date,
            end_date=end_date,
            departments=narrow_departments(department, scope),
        )
        return Response(
            content=content,
            media_type='application/vnd.openxmlformats-officedocument.spreadsheetml.xlsx',
            headers={'Content-Disposition': 'attachment; filename=production_report.xlsx'},
        )
    except InvalidDateRangeError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
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
