"""系统内消息通知接口

提供当前用户的未读数查询、分页列表、单条已读、全部已读端点。
所有端点仅操作 `notification.user_id == current_user.id` 的记录，不可越权。
"""
import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from fastapi_app.core.database import get_async_db, get_async_read_db
from fastapi_app.core.deps import get_current_user_id
from fastapi_app.core.exceptions import db_transaction
from fastapi_app.core.response import success_response
from fastapi_app.services.notification_service import (
    count_unread_notifications,
    get_notifications_page,
    mark_all_notifications_read,
)
from fastapi_app.shared_models import Notification

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/unread-count")
async def get_unread_count(
    user_id: int = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_async_read_db),
) -> dict:
    """返回当前用户的未读通知数。"""
    count = await count_unread_notifications(db, user_id)
    return {"count": count}


@router.get("")
async def list_notifications(
    page: int = Query(1, ge=1, description="页码，从 1 开始"),
    page_size: int = Query(20, ge=1, le=100, description="每页数量，1-100"),
    only_unread: bool = Query(False, description="仅返回未读通知"),
    user_id: int = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_async_read_db),
) -> dict:
    """获取当前用户的通知分页列表（按 created_at desc）。"""
    notifications, total = await get_notifications_page(db, user_id, page, page_size, only_unread)

    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "data": [n.to_dict() for n in notifications],
    }


@router.post("/{notification_id}/read")
async def mark_as_read(
    notification_id: int,
    user_id: int = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_async_db),
) -> dict:
    """标记单条通知为已读。

    校验通知存在且属于当前用户，否则 404。
    """
    notification = await db.get(Notification, notification_id)
    if notification is None or notification.user_id != user_id:
        raise HTTPException(status_code=404, detail="通知不存在")

    if not notification.is_read:
        async with db_transaction(db):
            notification.is_read = True
    return success_response(message="已标记为已读")


@router.post("/read-all")
async def mark_all_as_read(
    user_id: int = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_async_db),
) -> dict:
    """标记当前用户所有未读通知为已读。"""
    async with db_transaction(db):
        updated = await mark_all_notifications_read(db, user_id)
    return success_response(marked_count=int(updated))
