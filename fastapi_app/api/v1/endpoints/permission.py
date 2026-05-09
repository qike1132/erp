"""权限管理接口"""
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from fastapi_app.core.database import get_async_db, get_async_read_db
from fastapi_app.core.deps import require_permission
from fastapi_app.schemas.user import PermissionResponse
from fastapi_app.services import user_service
from fastapi_app.shared_models import User

router = APIRouter()


@router.get("/tree", response_model=list[PermissionResponse])
async def get_permission_tree(
    user: User = Depends(require_permission("user_manage")),
    db: AsyncSession = Depends(get_async_read_db),
):
    """获取权限树形结构"""
    permissions = await user_service.get_permissions(db)
    visible_perms = [
        PermissionResponse(
            id=p.id, name=p.name, code=p.code, parent_id=p.parent_id,
            icon=p.icon, url=p.url, section=p.section, section_name=p.section_name,
            sort_order=p.sort_order, is_nav=p.is_nav,
            children=[
                PermissionResponse(
                    id=c.id, name=c.name, code=c.code, parent_id=c.parent_id,
                    icon=c.icon, url=c.url, section=c.section, section_name=c.section_name,
                    sort_order=c.sort_order, is_nav=c.is_nav,
                )
                for c in p.children
            ],
        )
        for p in permissions
        if p.code not in ['user_manage']
    ]
    return visible_perms


@router.get("/list", response_model=list[PermissionResponse])
async def get_permission_list(
    user: User = Depends(require_permission("user_manage")),
    db: AsyncSession = Depends(get_async_read_db),
):
    """获取权限平铺列表"""
    permissions = await user_service.get_permissions(db)
    result = []
    for p in permissions:
        if p.code in ['user_manage']:
            continue
        result.append(
            PermissionResponse(
                id=p.id, name=p.name, code=p.code, parent_id=p.parent_id,
                icon=p.icon, url=p.url, section=p.section, section_name=p.section_name,
                sort_order=p.sort_order, is_nav=p.is_nav,
                children=[
                    PermissionResponse(
                        id=c.id, name=c.name, code=c.code, parent_id=c.parent_id,
                        icon=c.icon, url=c.url, section=c.section, section_name=c.section_name,
                        sort_order=c.sort_order, is_nav=c.is_nav,
                    )
                    for c in p.children
                ],
            )
        )
    return result
