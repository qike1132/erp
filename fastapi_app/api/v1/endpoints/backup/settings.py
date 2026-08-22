"""备份系统设置路由(M1)。

- GET  /settings              读取备份设置(路径/保留策略/加密模式)
- POST /settings              保存设置(路径须先通过 validate-path)
- POST /settings/validate-path 自定义路径预校验(可写/空间/合法性)
"""
import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from fastapi_app.api.v1.endpoints.backup._deps import require_backup_permission
from fastapi_app.core.database import get_async_db
from fastapi_app.schemas.backup import (
    BackupPathValidateRequest,
    BackupPathValidateResponse,
    BackupSettingsOut,
    BackupSettingsUpdate,
)
from fastapi_app.services import backup as backup_service
from fastapi_app.services.backup import BackupSettingsError
from fastapi_app.shared_models import User

logger = logging.getLogger(__name__)
router = APIRouter()


# ---------------------------------------------------------------------------
# GET /settings
# ---------------------------------------------------------------------------
@router.get('/settings', response_model=BackupSettingsOut)
async def get_backup_settings(
    user: User = Depends(require_backup_permission('get_backup_settings')),
    db: AsyncSession = Depends(get_async_db),
):
    """读取备份系统设置。

    表未初始化时返回环境变量默认值(backup_dir 为 BACKUP_DIR env 或默认 backups/server),
    initialized=False 表示当前实际生效的是 env 配置。
    权限:backup_read
    """
    settings = await backup_service.get_settings(db)
    settings['success'] = True
    return settings


# ---------------------------------------------------------------------------
# POST /settings
# ---------------------------------------------------------------------------
@router.post('/settings', response_model=BackupSettingsOut)
async def update_backup_settings(
    payload: BackupSettingsUpdate,
    user: User = Depends(require_backup_permission('update_backup_settings')),
    db: AsyncSession = Depends(get_async_db),
):
    """保存备份系统设置。

    - backup_dir:自定义路径,保存前必须已通过 validate-path 校验(服务端兜底再次校验)
    - retention_days / max_count / encryption_mode:可选更新
    权限:backup_manage
    """
    operator = getattr(user, 'username', None) or str(getattr(user, 'id', ''))
    try:
        result = await backup_service.save_settings(
            db,
            backup_dir=payload.backup_dir,
            retention_days=payload.retention_days,
            max_count=payload.max_count,
            encryption_mode=payload.encryption_mode,
            operator=operator,
        )
    except BackupSettingsError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    result['success'] = True
    logger.info('备份设置已更新 operator=%s dir=%s', operator, result.get('backup_dir'))
    return result


# ---------------------------------------------------------------------------
# POST /settings/validate-path
# ---------------------------------------------------------------------------
@router.post('/settings/validate-path', response_model=BackupPathValidateResponse)
async def validate_backup_path(
    payload: BackupPathValidateRequest,
    user: User = Depends(require_backup_permission('validate_backup_path')),
):
    """自定义备份路径预校验。

    校验项:绝对路径/盘符白名单/非法字符/路径穿越/系统目录黑名单/目录可写/空间阈值。
    通过返回 valid=true + message,失败返回 valid=false + error。
    权限:backup_read
    """
    return backup_service.validate_path(payload.path)
