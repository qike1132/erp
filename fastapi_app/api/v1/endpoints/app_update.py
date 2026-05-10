"""
App版本管理 API

工作流：上传(待发布) → 发布(激活+FCM推送) → 用户收到更新通知
"""
import asyncio
import hashlib
import logging
import os
import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from fastapi_app.core.database import get_async_db, get_async_read_db
from fastapi_app.core.deps import require_permission
from fastapi_app.shared_models.app_version import AppVersion

logger = logging.getLogger(__name__)

router = APIRouter()

UPLOAD_DIR = os.path.join(os.path.dirname(__file__), '..', '..', '..', '..', 'static', 'releases')
os.makedirs(UPLOAD_DIR, exist_ok=True)


class AppVersionResponse(BaseModel):
    id: int
    platform: str
    version_code: int
    version_name: str
    download_url: str
    changelog: str | None = None
    file_size: int | None = None
    md5_hash: str | None = None
    force_update: bool = False
    is_active: bool = False
    pushed: bool = False
    created_at: str | None = None

    model_config = {"from_attributes": True}

    @field_validator("created_at", mode="before")
    @classmethod
    def format_created_at(cls, v: Any) -> str | None:
        if isinstance(v, datetime):
            return v.strftime("%Y-%m-%d %H:%M:%S")
        return v


class CheckUpdateResponse(BaseModel):
    has_update: bool
    latest_version: AppVersionResponse | None = None
    current_version_code: int = 0


def _compute_md5(file_path: str) -> str:
    md5 = hashlib.md5()
    with open(file_path, 'rb') as f:
        for chunk in iter(lambda: f.read(8192), b''):
            md5.update(chunk)
    return md5.hexdigest()


def _write_file(path: str, content: bytes) -> None:
    with open(path, 'wb') as f:
        f.write(content)


@router.get("/latest", response_model=CheckUpdateResponse)
async def check_update(
    platform: str = "android",
    current_version_code: int = 0,
    db: AsyncSession = Depends(get_async_read_db),
):
    """客户端检查是否有新版本可用（仅返回已发布的版本）"""
    result = await db.execute(
        select(AppVersion)
        .where(AppVersion.platform == platform, AppVersion.is_active == True)
        .order_by(AppVersion.version_code.desc())
    )
    latest = result.scalars().first()

    if latest is None or latest.version_code <= current_version_code:
        return CheckUpdateResponse(has_update=False, current_version_code=current_version_code)

    return CheckUpdateResponse(
        has_update=True,
        latest_version=latest,
        current_version_code=current_version_code,
    )


@router.post("/upload", response_model=AppVersionResponse)
async def upload_version(
    version_name: str = Form(..., description="显示版本号，如 1.1"),
    version_code: int = Form(..., description="整数版本号"),
    changelog: str = Form("", description="更新日志"),
    force_update: bool = Form(False, description="是否强制更新"),
    file: UploadFile = File(..., description="APK文件"),
    user: User = Depends(require_permission('app_manage')),
    db: AsyncSession = Depends(get_async_db),
):
    """上传新版本APK，状态为「待发布」"""
    ext = os.path.splitext(file.filename or "release.apk")[1]
    if ext.lower() != ".apk":
        raise HTTPException(status_code=400, detail="仅支持.apk文件上传")

    saved_name = f"{uuid.uuid4().hex}{ext}"
    saved_path = os.path.join(UPLOAD_DIR, saved_name)

    content = await file.read()
    file_size = len(content)
    await asyncio.to_thread(lambda: _write_file(saved_path, content))

    md5_hash = await asyncio.to_thread(_compute_md5, saved_path)

    download_url = f"/static/releases/{saved_name}"

    version = AppVersion(
        platform="android",
        version_code=version_code,
        version_name=version_name,
        download_url=download_url,
        changelog=changelog or None,
        file_size=file_size,
        md5_hash=md5_hash,
        force_update=force_update,
        is_active=False,
        pushed=False,
        created_at=datetime.now(),
    )
    db.add(version)
    await db.flush()
    await db.refresh(version)

    logger.info("新版本已上传(待发布): v%s (code=%d), size=%d", version_name, version_code, file_size)
    return version


@router.post("/{version_id}/publish", response_model=AppVersionResponse)
async def publish_version(
    version_id: int,
    user: User = Depends(require_permission('app_manage')),
    db: AsyncSession = Depends(get_async_db),
):
    """发布版本：激活版本 + 推送FCM通知到所有设备"""
    result = await db.execute(
        select(AppVersion).where(AppVersion.id == version_id)
    )
    version = result.scalars().first()
    if version is None:
        raise HTTPException(status_code=404, detail="版本不存在")

    if version.is_active and version.pushed:
        raise HTTPException(status_code=400, detail="该版本已发布，请勿重复操作")

    version.is_active = True

    # 尝试 FCM 推送（可选）
    topic = "android_updates"
    try:
        import firebase_admin
        from firebase_admin import messaging
        
        # 检查是否已初始化
        if not firebase_admin._apps:
            logger.warning("FCM未配置，跳过推送通知")
        else:
            message = messaging.Message(
                data={
                    "type": "app_update",
                    "version_code": str(version.version_code),
                    "version_name": version.version_name,
                    "download_url": version.download_url,
                    "changelog": version.changelog or "",
                    "force_update": str(version.force_update).lower(),
                    "md5_hash": version.md5_hash or "",
                    "file_size": str(version.file_size or 0),
                },
                notification=messaging.Notification(
                    title="滨发ERP新版本可用",
                    body=f"v{version.version_name} 已发布，点击更新",
                ),
                topic=topic,
            )
            response = messaging.send(message)
            version.pushed = True
            logger.info("版本发布成功: v%s, FCM推送完成, topic=%s, response=%s", version.version_name, topic, response)
    except ImportError as e:
        logger.warning("firebase_admin未安装，跳过FCM推送: %s", e)
        version.pushed = False
    except Exception as e:
        logger.error("FCM推送失败(版本已激活): %s", e)
        version.pushed = False

    await db.flush()
    await db.refresh(version)
    return version


@router.get("/versions", response_model=list[AppVersionResponse])
async def list_versions(
    platform: str = "android",
    user: User = Depends(require_permission('app_manage')),
    db: AsyncSession = Depends(get_async_read_db),
):
    """管理后台：列出所有版本"""
    result = await db.execute(
        select(AppVersion)
        .where(AppVersion.platform == platform)
        .order_by(AppVersion.version_code.desc())
    )
    return result.scalars().all()
