"""财务统计接口"""
from fastapi import APIRouter, Depends, Query

from fastapi_app.core.deps import require_permission
from fastapi_app.core.database import get_async_db
from fastapi_app.shared_models import User
from fastapi_app.services import finance_service
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter()


@router.get("/customer-summary")
async def customer_summary(
    customer: str = Query('', description="客户筛选"),
    start_date: str = Query('', description="开始日期"),
    end_date: str = Query('', description="结束日期"),
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    user: User = Depends(require_permission("finance_view")),
    db: AsyncSession = Depends(get_async_db),
):
    """按客户汇总出货数量和金额"""
    return await finance_service.get_customer_summary(
        db, customer, start_date, end_date, page, per_page
    )


@router.get("/daily-amount")
async def daily_amount(
    customer: str = Query('', description="客户筛选"),
    start_date: str = Query('', description="开始日期"),
    end_date: str = Query('', description="结束日期"),
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    user: User = Depends(require_permission("finance_view")),
    db: AsyncSession = Depends(get_async_db),
):
    """按日汇总出货金额"""
    return await finance_service.get_daily_amount(
        db, customer, start_date, end_date, page, per_page
    )


@router.get("/daily-amount-chart")
async def daily_amount_chart(
    customer: str = Query('', description="客户筛选"),
    start_date: str = Query('', description="开始日期"),
    end_date: str = Query('', description="结束日期"),
    user: User = Depends(require_permission("finance_view")),
    db: AsyncSession = Depends(get_async_db),
):
    """按日汇总出货金额（图表数据）"""
    return await finance_service.get_daily_amount_chart(
        db, customer, start_date, end_date
    )
