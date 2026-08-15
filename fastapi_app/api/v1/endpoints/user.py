"""用户管理接口

提供用户 CRUD、状态切换、权限查询与设置等管理端点。
所有端点均要求超级管理员权限（require_superuser）。
"""
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

router = APIRouter()

# 需要对普通管理员隐藏的权限代码
_HIDDEN_PERMISSION_CODES = frozenset({'user_manage'})


def _format_user_response(u: User) -> UserResponse:
    """将 User ORM 对象转换为响应模型，处理时间格式化。"""
    create_time = u.create_time.strftime('%Y-%m-%d %H:%M') if u.create_time else None
    return UserResponse(
        id=u.id,
        username=u.username,
        is_super=u.is_super,
        status=u.status,
        factory=u.factory,
        create_time=create_time,
    )


def _build_permission_response(p) -> PermissionResponse:
    """将权限对象（含子权限）转换为响应模型。"""
    children = [
        PermissionResponse(
            id=c.id, name=c.name, code=c.code, parent_id=c.parent_id,
            icon=c.icon, url=c.url, section=c.section, section_name=c.section_name,
            sort_order=c.sort_order, is_nav=c.is_nav,
        ) for c in p.children
    ]
    return PermissionResponse(
        id=p.id, name=p.name, code=p.code, parent_id=p.parent_id,
        icon=p.icon, url=p.url, section=p.section, section_name=p.section_name,
        sort_order=p.sort_order, is_nav=p.is_nav, children=children,
    )


@router.get('/list', response_model=UserListResponse)
async def list_users(
    page: int = Query(1, ge=1),
    per_page: int = Query(15, ge=1, le=100),
    _current_user: User = Depends(require_superuser()),
    db: AsyncSession = Depends(get_async_read_db),
) -> UserListResponse:
    """获取用户分页列表。

    Args:
        page: 页码，从 1 开始。
        per_page: 每页条数，1-100。
        _current_user: 当前操作者（仅用于权限校验）。
        db: 只读数据库会话。

    Returns:
        UserListResponse: 包含用户列表、总数及分页信息。
    """
    users, total = await user_service.get_users(db, page=page, per_page=per_page)
    return UserListResponse(
        users=[_format_user_response(u) for u in users],
        total=total, page=page, per_page=per_page,
    )


@router.post('/create', response_model=UserActionResponse)
async def create_user(
    data: UserCreate,
    _current_user: User = Depends(require_superuser()),
    db: AsyncSession = Depends(get_async_db),
) -> UserActionResponse:
    """创建新用户。

    Args:
        data: 用户创建参数（用户名、密码、是否超管）。
        _current_user: 当前操作者（仅用于权限校验）。
        db: 读写数据库会话。

    Returns:
        UserActionResponse: 操作结果消息。
    """
    async with db_transaction(db):
        await user_service.create_user(db, data.username, data.password, data.is_super, data.factory)
    return UserActionResponse(message='用户添加成功')


@router.put('/edit/{user_id}', response_model=UserActionResponse)
async def edit_user(
    user_id: int,
    data: UserUpdate,
    _current_user: User = Depends(require_superuser()),
    db: AsyncSession = Depends(get_async_db),
) -> UserActionResponse:
    """编辑用户信息（密码、超管标志）。

    Args:
        user_id: 目标用户 ID。
        data: 用户更新参数。
        _current_user: 当前操作者（仅用于权限校验）。
        db: 读写数据库会话。

    Returns:
        UserActionResponse: 操作结果消息。
    """
    async with db_transaction(db):
        await user_service.update_user(db, user_id, data.password, data.is_super, data.factory)
    return UserActionResponse(message='用户编辑成功')


@router.post('/toggle/{user_id}', response_model=UserActionResponse)
async def toggle_user_status(
    user_id: int,
    user: User = Depends(require_superuser()),
    db: AsyncSession = Depends(get_async_db),
) -> UserActionResponse:
    """切换用户启用/禁用状态。

    禁止禁用自身账户，避免管理员锁定自己。

    Args:
        user_id: 目标用户 ID。
        user: 当前操作者。
        db: 读写数据库会话。

    Returns:
        UserActionResponse: 包含新状态（启用/禁用）的消息。

    Raises:
        HTTPException 400: 尝试禁用自身账户时抛出。
    """
    if user_id == user.id:
        raise HTTPException(status_code=400, detail='不能禁用自身账户')
    async with db_transaction(db):
        updated_user = await user_service.toggle_user_status(db, user_id)
        await invalidate_user_permission_cache(user_id)
    status_text = '启用' if updated_user.status else '禁用'
    return UserActionResponse(message=f'用户已{status_text}')


@router.delete('/delete/{user_id}', response_model=UserActionResponse)
async def delete_user(
    user_id: int,
    user: User = Depends(require_superuser()),
    db: AsyncSession = Depends(get_async_db),
) -> UserActionResponse:
    """删除用户。

    禁止删除自身账户；禁止删除最后一个超级管理员，避免系统失去管理能力。

    Args:
        user_id: 目标用户 ID。
        user: 当前操作者。
        db: 读写数据库会话。

    Returns:
        UserActionResponse: 操作结果消息。

    Raises:
        HTTPException 400: 尝试删除自身账户或最后一个超级用户时抛出。
        HTTPException 404: 目标用户不存在时抛出。
    """
    if user_id == user.id:
        raise HTTPException(status_code=400, detail='不能删除自身账户')
    target_user = await db.get(User, user_id)
    if not target_user:
        raise HTTPException(status_code=404, detail='用户不存在')
    # 保护最后一个超级管理员，防止系统无法管理
    if target_user.is_super:
        if await user_service.count_super_users(db) <= 1:
            raise HTTPException(status_code=400, detail='无法删除最后一个超级用户')
    async with db_transaction(db):
        await user_service.delete_user(db, user_id)
        await invalidate_user_permission_cache(user_id)
    return UserActionResponse(message='用户已删除')


@router.get('/permission/{user_id}', response_model=UserPermissionResponse)
async def get_user_permissions(
    user_id: int,
    _current_user: User = Depends(require_superuser()),
    db: AsyncSession = Depends(get_async_read_db),
) -> UserPermissionResponse:
    """获取用户权限设置。

    返回所有可见权限树及当前用户已分配的权限 ID 列表。
    user_manage 权限对非超管隐藏。

    Args:
        user_id: 目标用户 ID。
        _current_user: 当前操作者（仅用于权限校验）。
        db: 只读数据库会话。

    Returns:
        UserPermissionResponse: 权限树与用户已分配权限 ID。

    Raises:
        HTTPException 404: 目标用户不存在时抛出。
    """
    target_user = await db.get(User, user_id, options=[selectinload(User.permissions)])
    if not target_user:
        raise HTTPException(status_code=404, detail='用户不存在')
    permissions, user_perm_ids = await user_service.get_permissions_with_user_ids(db, target_user)
    visible_perms = [
        _build_permission_response(p)
        for p in permissions if p.code not in _HIDDEN_PERMISSION_CODES
    ]
    return UserPermissionResponse(user_id=user_id, user_permission_ids=user_perm_ids, permissions=visible_perms)


@router.post('/permission/{user_id}', response_model=UserActionResponse)
async def update_user_permissions(
    user_id: int,
    data: UserPermissionUpdate,
    _current_user: User = Depends(require_superuser()),
    db: AsyncSession = Depends(get_async_db),
) -> UserActionResponse:
    """设置用户权限。

    Args:
        user_id: 目标用户 ID。
        data: 权限更新参数（permission_ids 列表）。
        _current_user: 当前操作者（仅用于权限校验）。
        db: 读写数据库会话。

    Returns:
        UserActionResponse: 操作结果消息。
    """
    async with db_transaction(db):
        await user_service.update_user_permissions(db, user_id, data.permission_ids)
        await invalidate_user_permission_cache(user_id)
    return UserActionResponse(message='权限设置成功')
