"""用户管理接口"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from fastapi_app.core.database import get_async_db, get_async_read_db
from fastapi_app.core.deps import invalidate_user_permission_cache, require_superuser
from fastapi_app.core.exceptions import db_transaction
from fastapi_app.schemas.user import (
    PermissionResponse,
    UserActionResponse,
    UserCreate,
    UserListResponse,
    UserPermissionResponse,
    UserPermissionUpdate,
    UserResponse,
    UserUpdate,
)
from fastapi_app.services import user_service
from fastapi_app.shared_models import User
from sqlalchemy import select, func

router = APIRouter()

@router.get('/list', response_model=UserListResponse)
async def list_users(page: int=Query(1, ge=1), per_page: int=Query(15, ge=1, le=100), _user: User=Depends(require_superuser()), db: AsyncSession=Depends(get_async_read_db)):
    """用户列表"""
    users, total = await user_service.get_users(db, page=page, per_page=per_page)
    return UserListResponse(users=[UserResponse(id=u.id, username=u.username, is_super=u.is_super, status=u.status, create_time=u.create_time.strftime('%Y-%m-%d %H:%M') if u.create_time else None) for u in users], total=total, page=page, per_page=per_page)

@router.post('/create', response_model=UserActionResponse)
async def create_user(data: UserCreate, _user: User=Depends(require_superuser()), db: AsyncSession=Depends(get_async_db)):
    """添加用户"""
    async with db_transaction(db):
        await user_service.create_user(db, data.username, data.password, data.is_super)
    return UserActionResponse(message='用户添加成功')

@router.put('/edit/{user_id}', response_model=UserActionResponse)
async def edit_user(user_id: int, data: UserUpdate, _user: User=Depends(require_superuser()), db: AsyncSession=Depends(get_async_db)):
    """编辑用户"""
    async with db_transaction(db):
        await user_service.update_user(db, user_id, data.password, data.is_super)
    return UserActionResponse(message='用户编辑成功')

@router.post('/toggle/{user_id}', response_model=UserActionResponse)
async def toggle_user_status(user_id: int, user: User=Depends(require_superuser()), db: AsyncSession=Depends(get_async_db)):
    """切换用户状态"""
    if user_id == user.id:
        raise HTTPException(status_code=400, detail='不能禁用自身账户')
    async with db_transaction(db):
        updated_user = await user_service.toggle_user_status(db, user_id)
        await invalidate_user_permission_cache(user_id)
    status_text = '启用' if updated_user.status else '禁用'
    return UserActionResponse(message=f'用户已{status_text}')

@router.delete('/delete/{user_id}', response_model=UserActionResponse)
async def delete_user(user_id: int, user: User=Depends(require_superuser()), db: AsyncSession=Depends(get_async_db)):
    """删除用户"""
    if user_id == user.id:
        raise HTTPException(status_code=400, detail='不能删除自身账户')
    target_user = await db.get(User, user_id)
    if not target_user:
        raise HTTPException(status_code=404, detail='用户不存在')
    if target_user.is_super:
        super_count = await db.scalar(select(func.count()).select_from(User).where(User.is_super == True))  # noqa: E712
        if super_count <= 1:
            raise HTTPException(status_code=400, detail='无法删除最后一个超级用户')
    async with db_transaction(db):
        await user_service.delete_user(db, user_id)
        await invalidate_user_permission_cache(user_id)
    return UserActionResponse(message='用户已删除')

@router.get('/permission/{user_id}', response_model=UserPermissionResponse)
async def get_user_permissions(user_id: int, _user: User=Depends(require_superuser()), db: AsyncSession=Depends(get_async_read_db)):
    """获取用户权限设置"""
    target_user = await db.get(User, user_id, options=[selectinload(User.permissions)])
    if not target_user:
        raise HTTPException(status_code=404, detail='用户不存在')
    permissions, user_perm_ids = await user_service.get_permissions_with_user_ids(db, target_user)
    visible_perms = [PermissionResponse(id=p.id, name=p.name, code=p.code, parent_id=p.parent_id, icon=p.icon, url=p.url, section=p.section, section_name=p.section_name, sort_order=p.sort_order, is_nav=p.is_nav, children=[PermissionResponse(id=c.id, name=c.name, code=c.code, parent_id=c.parent_id, icon=c.icon, url=c.url, section=c.section, section_name=c.section_name, sort_order=c.sort_order, is_nav=c.is_nav) for c in p.children]) for p in permissions if p.code not in ['user_manage']]
    return UserPermissionResponse(user_id=user_id, user_permission_ids=user_perm_ids, permissions=visible_perms)

@router.post('/permission/{user_id}', response_model=UserActionResponse)
async def update_user_permissions(user_id: int, data: UserPermissionUpdate, _user: User=Depends(require_superuser()), db: AsyncSession=Depends(get_async_db)):
    """设置用户权限"""
    async with db_transaction(db):
        await user_service.update_user_permissions(db, user_id, data.permission_ids)
        await invalidate_user_permission_cache(user_id)
    return UserActionResponse(message='权限设置成功')
