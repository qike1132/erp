"""报表统计接口"""
from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from fastapi_app.core.database import get_async_db, get_async_read_db
from fastapi_app.core.deps import require_permission
from fastapi_app.schemas.report import ReportResponse
from fastapi_app.services import report_service
from fastapi_app.shared_models import User

router = APIRouter()


@router.get("/order-logs", response_model=ReportResponse)
async def order_logs(
    customer: str = Query('', description="客户筛选"),
    product: str = Query('', description="产品筛选"),
    status: str = Query('', description="状态筛选"),
    start_date: str = Query('', description="开始日期"),
    end_date: str = Query('', description="结束日期"),
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    user: User = Depends(require_permission("report_view")),
    db: AsyncSession = Depends(get_async_read_db),
):
    """订单流水"""
    return await report_service.get_order_logs(
        db, customer, product, status, start_date, end_date, page, per_page
    )


@router.get("/stockin-logs", response_model=ReportResponse)
async def stockin_logs(
    customer: str = Query('', description="客户筛选"),
    product: str = Query('', description="产品筛选"),
    start_date: str = Query('', description="开始日期"),
    end_date: str = Query('', description="结束日期"),
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    user: User = Depends(require_permission("report_view")),
    db: AsyncSession = Depends(get_async_read_db),
):
    """备货流水"""
    return await report_service.get_stockin_logs(
        db, customer, product, start_date, end_date, page, per_page
    )


@router.get("/stockout-logs", response_model=ReportResponse)
async def stockout_logs(
    customer: str = Query('', description="客户筛选"),
    product: str = Query('', description="产品筛选"),
    start_date: str = Query('', description="开始日期"),
    end_date: str = Query('', description="结束日期"),
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    user: User = Depends(require_permission("report_view")),
    db: AsyncSession = Depends(get_async_read_db),
):
    """出货流水"""
    return await report_service.get_stockout_logs(
        db, customer, product, start_date, end_date, page, per_page
    )


@router.get("/deduction-logs", response_model=ReportResponse)
async def deduction_logs(
    customer: str = Query('', description="客户筛选"),
    product: str = Query('', description="产品筛选"),
    start_date: str = Query('', description="开始日期"),
    end_date: str = Query('', description="结束日期"),
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    user: User = Depends(require_permission("report_view")),
    db: AsyncSession = Depends(get_async_read_db),
):
    """备货抵扣流水"""
    return await report_service.get_deduction_logs(
        db, customer, product, start_date, end_date, page, per_page
    )


@router.get("/export")
async def export_report(
    report_type: str = Query(..., description="报表类型: order/stockin/stockout/deduction"),
    customer: str = Query('', description="客户筛选"),
    product: str = Query('', description="产品筛选"),
    status: str = Query('', description="状态筛选"),
    start_date: str = Query('', description="开始日期"),
    end_date: str = Query('', description="结束日期"),
    user: User = Depends(require_permission("report_view")),
    db: AsyncSession = Depends(get_async_read_db),
):
    """导出报表为 Excel 文件"""
    if report_type not in ("order", "stockin", "stockout", "deduction"):
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail=f"不支持的报表类型: {report_type}")

    buffer = await report_service.export_report_to_excel(
        db, report_type, customer, product, status, start_date, end_date
    )

    filename = f"{report_type}_report.xlsx"
    return StreamingResponse(
        buffer,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )

