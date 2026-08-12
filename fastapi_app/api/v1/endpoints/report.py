"""报表统计接口

职责：
    - 提供订单、备货、出货、抵扣四类流水的分页查询
    - 支持按客户、产品、状态、日期范围筛选
    - 支持将报表导出为 Excel 文件

依赖服务：report_service
"""
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from fastapi_app.core.database import get_async_read_db
from fastapi_app.core.deps import require_permission
from fastapi_app.core.limiter import limiter
from fastapi_app.schemas.report import ReportResponse
from fastapi_app.services import report_service
from fastapi_app.shared_models import User

# 允许导出的报表类型
ALLOWED_REPORT_TYPES = ('order', 'stockin', 'stockout', 'deduction')

router = APIRouter()


@router.get('/order-logs', response_model=ReportResponse)
async def order_logs(
    customer: str = Query('', description='客户筛选'),
    product: str = Query('', description='产品筛选'),
    status: str = Query('', description='状态筛选'),
    start_date: str = Query('', description='开始日期'),
    end_date: str = Query('', description='结束日期'),
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    user: User = Depends(require_permission('report_view')),
    db: AsyncSession = Depends(get_async_read_db),
) -> ReportResponse:
    """订单流水查询。

    Args:
        customer: 客户名称筛选，空串表示不筛选。
        product: 产品名称筛选，空串表示不筛选。
        status: 订单状态筛选，空串表示不筛选。
        start_date: 开始日期（字符串，如 '2024-01-01'），空串表示不限制。
        end_date: 结束日期（字符串），空串表示不限制。
        page: 页码，从 1 开始。
        per_page: 每页条数，1-100。
        user: 当前操作用户（用于权限校验）。
        db: 只读数据库会话。

    Returns:
        ReportResponse: 订单流水分页结果。
    """
    return await report_service.get_order_logs(
        db, customer, product, status, start_date, end_date, page, per_page,
    )


@router.get('/stockin-logs', response_model=ReportResponse)
async def stockin_logs(
    customer: str = Query('', description='客户筛选'),
    product: str = Query('', description='产品筛选'),
    start_date: str = Query('', description='开始日期'),
    end_date: str = Query('', description='结束日期'),
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    user: User = Depends(require_permission('report_view')),
    db: AsyncSession = Depends(get_async_read_db),
) -> ReportResponse:
    """备货流水查询。

    Args:
        customer: 客户名称筛选，空串表示不筛选。
        product: 产品名称筛选，空串表示不筛选。
        start_date: 开始日期（字符串），空串表示不限制。
        end_date: 结束日期（字符串），空串表示不限制。
        page: 页码，从 1 开始。
        per_page: 每页条数，1-100。
        user: 当前操作用户（用于权限校验）。
        db: 只读数据库会话。

    Returns:
        ReportResponse: 备货流水分页结果。
    """
    return await report_service.get_stockin_logs(
        db, customer, product, start_date, end_date, page, per_page,
    )


@router.get('/stockout-logs', response_model=ReportResponse)
async def stockout_logs(
    customer: str = Query('', description='客户筛选'),
    product: str = Query('', description='产品筛选'),
    start_date: str = Query('', description='开始日期'),
    end_date: str = Query('', description='结束日期'),
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    user: User = Depends(require_permission('report_view')),
    db: AsyncSession = Depends(get_async_read_db),
) -> ReportResponse:
    """出货流水查询。

    Args:
        customer: 客户名称筛选，空串表示不筛选。
        product: 产品名称筛选，空串表示不筛选。
        start_date: 开始日期（字符串），空串表示不限制。
        end_date: 结束日期（字符串），空串表示不限制。
        page: 页码，从 1 开始。
        per_page: 每页条数，1-100。
        user: 当前操作用户（用于权限校验）。
        db: 只读数据库会话。

    Returns:
        ReportResponse: 出货流水分页结果。
    """
    return await report_service.get_stockout_logs(
        db, customer, product, start_date, end_date, page, per_page,
    )


@router.get('/deduction-logs', response_model=ReportResponse)
async def deduction_logs(
    customer: str = Query('', description='客户筛选'),
    product: str = Query('', description='产品筛选'),
    start_date: str = Query('', description='开始日期'),
    end_date: str = Query('', description='结束日期'),
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    user: User = Depends(require_permission('report_view')),
    db: AsyncSession = Depends(get_async_read_db),
) -> ReportResponse:
    """备货抵扣流水查询。

    Args:
        customer: 客户名称筛选，空串表示不筛选。
        product: 产品名称筛选，空串表示不筛选。
        start_date: 开始日期（字符串），空串表示不限制。
        end_date: 结束日期（字符串），空串表示不限制。
        page: 页码，从 1 开始。
        per_page: 每页条数，1-100。
        user: 当前操作用户（用于权限校验）。
        db: 只读数据库会话。

    Returns:
        ReportResponse: 备货抵扣流水分页结果。
    """
    return await report_service.get_deduction_logs(
        db, customer, product, start_date, end_date, page, per_page,
    )


@router.get('/export')
@limiter.limit("100/minute")  # 内网宽松：导出接口取消严格限流
async def export_report(
    request: Request,
    report_type: str = Query(..., description='报表类型: order/stockin/stockout/deduction'),
    customer: str = Query('', description='客户筛选'),
    product: str = Query('', description='产品筛选'),
    status: str = Query('', description='状态筛选'),
    start_date: str = Query('', description='开始日期'),
    end_date: str = Query('', description='结束日期'),
    user: User = Depends(require_permission('report_view')),
    db: AsyncSession = Depends(get_async_read_db),
) -> StreamingResponse:
    """导出报表为 Excel 文件。

    Args:
        report_type: 报表类型，可选值：order/stockin/stockout/deduction。
        customer: 客户名称筛选，空串表示不筛选。
        product: 产品名称筛选，空串表示不筛选。
        status: 状态筛选，空串表示不筛选。
        start_date: 开始日期（字符串），空串表示不限制。
        end_date: 结束日期（字符串），空串表示不限制。
        user: 当前操作用户（用于权限校验）。
        db: 只读数据库会话。

    Returns:
        StreamingResponse: Excel 文件流（含 Content-Disposition 头）。

    Raises:
        HTTPException: 报表类型不支持时返回 400。
    """
    if report_type not in ALLOWED_REPORT_TYPES:
        raise HTTPException(status_code=400, detail=f'不支持的报表类型: {report_type}')

    buffer = await report_service.export_report_to_excel(
        db, report_type, customer, product, status, start_date, end_date,
    )

    filename = f'{report_type}_report.xlsx'
    return StreamingResponse(
        buffer,
        media_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        headers={'Content-Disposition': f'attachment; filename={filename}'},
    )
