"""设备 FCM 令牌注册接口"""
import logging
from datetime import datetime

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from fastapi_app.core.database import get_async_db
from fastapi_app.core.deps import get_current_user_id
from fastapi_app.core.exceptions import db_transaction
from fastapi_app.shared_models.device_token import DeviceToken

logger = logging.getLogger(__name__)
router = APIRouter()


class DeviceTokenRequest(BaseModel):
    token: str
    platform: str = "android"


class DeviceTokenResponse(BaseModel):
    success: bool
    message: str


@router.post("/register", response_model=DeviceTokenResponse)
async def register_device(
    req: DeviceTokenRequest,
    user_id: int = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_async_db),
):
    """注册或更新设备 FCM 令牌（upsert）"""
    async with db_transaction(db):
        result = await db.execute(
            select(DeviceToken).where(DeviceToken.token == req.token)
        )
        existing = result.scalar_one_or_none()

        if existing:
            if existing.user_id != user_id:
                existing.user_id = user_id
            existing.is_active = True
            existing.platform = req.platform
            existing.updated_at = datetime.now()
        else:
            await db.execute(
                update(DeviceToken)
                .where(DeviceToken.user_id == user_id, DeviceToken.platform == req.platform)
                .values(is_active=False, updated_at=datetime.now())
            )
            db.add(DeviceToken(
                user_id=user_id,
                token=req.token,
                platform=req.platform,
                is_active=True,
            ))

    logger.info("设备令牌已注册: user_id=%s, platform=%s", user_id, req.platform)
    return DeviceTokenResponse(success=True, message="设备令牌注册成功")


@router.delete("/unregister", response_model=DeviceTokenResponse)
async def unregister_device(
    token: str = Query(..., description="FCM 设备令牌"),
    user_id: int = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_async_db),
):
    """注销设备 FCM 令牌"""
    async with db_transaction(db):
        await db.execute(
            update(DeviceToken)
            .where(DeviceToken.token == token, DeviceToken.user_id == user_id)
            .values(is_active=False, updated_at=datetime.now())
        )
    logger.info("设备令牌已注销: user_id=%s", user_id)
    return DeviceTokenResponse(success=True, message="设备令牌已注销")
