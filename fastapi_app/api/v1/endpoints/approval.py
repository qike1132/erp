"""审批管理接口"""
from fastapi import APIRouter, Depends, HTTPException, Query

from fastapi_app.core.deps import require_permission
from fastapi_app.core.database import get_async_db
from fastapi_app.shared_models import User
from fastapi_app.schemas.approval import (
    ApprovalActionRequest, ApprovalListResponse, ApprovalDetailResponse,
    ApprovalActionResponse, ApprovalPendingCountResponse,
)
from fastapi_app.services import approval_service
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter()


@router.get("/list", response_model=ApprovalListResponse)
async def approval_list(
    status: str = Query('pending', description="状态筛选: pending/approved/rejected/all"),
    search: str = Query('', description="搜索关键词"),
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    user: User = Depends(require_permission("order_manage")),
    db: AsyncSession = Depends(get_async_db),
):
    """审批列表"""
    if not user.is_super:
        raise HTTPException(status_code=403, detail="仅管理员可访问")

    result = await approval_service.get_approval_list(db, status, search, page, per_page)
    return ApprovalListResponse(
        data=result['approvals'],
        pending_count=result['pending_count'],
        approved_count=result['approved_count'],
        rejected_count=result['rejected_count'],
    )


@router.get("/detail/{approval_id}", response_model=ApprovalDetailResponse)
async def approval_detail(
    approval_id: int,
    user: User = Depends(require_permission("order_manage")),
    db: AsyncSession = Depends(get_async_db),
):
    """审批详情"""
    if not user.is_super:
        raise HTTPException(status_code=403, detail="仅管理员可访问")

    try:
        data = await approval_service.get_approval_detail(db, approval_id)
        return ApprovalDetailResponse(data=data)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/approve/{approval_id}", response_model=ApprovalActionResponse)
async def approve(
    approval_id: int,
    user: User = Depends(require_permission("order_manage")),
    db: AsyncSession = Depends(get_async_db),
):
    """同意审批"""
    if not user.is_super:
        raise HTTPException(status_code=403, detail="仅管理员可访问")

    try:
        message = await approval_service.approve_request(db, approval_id, user)
        await db.commit()
        return ApprovalActionResponse(message=message)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/reject/{approval_id}", response_model=ApprovalActionResponse)
async def reject(
    approval_id: int,
    data: ApprovalActionRequest | None = None,
    user: User = Depends(require_permission("order_manage")),
    db: AsyncSession = Depends(get_async_db),
):
    """拒绝审批"""
    if not user.is_super:
        raise HTTPException(status_code=403, detail="仅管理员可访问")

    try:
        reason = data.reason if data else None
        message = await approval_service.reject_request(db, approval_id, user, reason)
        await db.commit()
        return ApprovalActionResponse(message=message)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/pending-count", response_model=ApprovalPendingCountResponse)
async def pending_count(
    user: User = Depends(require_permission("order_manage")),
    db: AsyncSession = Depends(get_async_db),
):
    """待审批数量"""
    count = await approval_service.get_pending_count(db)
    return ApprovalPendingCountResponse(count=count)
