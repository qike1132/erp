"""用户管理服务层"""
import logging
from sqlalchemy import select
from sqlalchemy.orm import joinedload

from fastapi_app.shared_models import User, Permission

logger = logging.getLogger(__name__)

SENSITIVE_PERMISSIONS = ['user_manage']


async def get_users(db) -> list[User]:
    """获取所有用户列表"""
    result = await db.execute(
        select(User).options(joinedload(User.permissions)).order_by(User.id)
    )
    return list(result.unique().scalars().all())


async def create_user(db, username: str, password: str, is_super: bool) -> User:
    """创建用户"""
    # 验证密码复杂度
    from utils.password_validator import PasswordValidator
    is_valid, error_msg = PasswordValidator.validate(password)
    if not is_valid:
        raise ValueError(error_msg)

    # 检查用户名唯一性
    result = await db.execute(
        select(User).where(User.username == username)
    )
    existing = result.scalar_one_or_none()
    if existing:
        raise ValueError("用户名已存在")

    from werkzeug.security import generate_password_hash
    new_user = User(
        username=username,
        password=generate_password_hash(password),
        is_super=is_super,
        status=True,
    )
    db.add(new_user)
    await db.flush()
    await db.refresh(new_user)
    return new_user


async def update_user(db, user_id: int, password: str | None, is_super: bool | None) -> User:
    """更新用户"""
    user = await db.get(User, user_id)
    if not user:
        raise ValueError("用户不存在")

    if password:
        from utils.password_validator import PasswordValidator
        is_valid, error_msg = PasswordValidator.validate(password)
        if not is_valid:
            raise ValueError(error_msg)
        from werkzeug.security import generate_password_hash
        user.password = generate_password_hash(password)

    if is_super is not None:
        user.is_super = is_super

    await db.flush()
    await db.refresh(user)
    return user


async def toggle_user_status(db, user_id: int) -> User:
    """切换用户状态"""
    user = await db.get(User, user_id)
    if not user:
        raise ValueError("用户不存在")

    if user.is_super:
        raise ValueError("超级用户不能禁用")

    user.status = not user.status
    await db.flush()
    await db.refresh(user)
    return user


async def delete_user(db, user_id: int) -> None:
    """删除用户"""
    user = await db.get(User, user_id)
    if not user:
        raise ValueError("用户不存在")

    if user.is_super:
        raise ValueError("超级用户不能删除")

    await db.delete(user)
    await db.flush()


async def get_permissions(db) -> list[Permission]:
    """获取所有权限（树形结构）"""
    result = await db.execute(
        select(Permission).options(
            joinedload(Permission.children)
        ).where(Permission.parent_id.is_(None))
        .order_by(Permission.sort_order)
    )
    return list(result.unique().scalars().all())


async def update_user_permissions(db, user_id: int, permission_ids: list[int]) -> User:
    """更新用户权限"""
    user = await db.get(User, user_id)
    if not user:
        raise ValueError("用户不存在")

    # 清空现有权限
    user.permissions.clear()

    for pid in permission_ids:
        permission = await db.get(Permission, pid)
        if permission:
            # 跳过敏感权限
            if permission.code in SENSITIVE_PERMISSIONS:
                continue
            user.permissions.append(permission)
            # 自动添加子权限
            if permission.children:
                for child in permission.children:
                    if child not in user.permissions:
                        user.permissions.append(child)

    await db.flush()
    await db.refresh(user)
    return user
