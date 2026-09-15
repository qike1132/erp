"""用户管理服务层"""
import logging

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload, selectinload

from fastapi_app.shared_models import ApprovalRequest, Order, Permission, User

logger = logging.getLogger(__name__)

SENSITIVE_PERMISSIONS = ['user_manage']


async def get_users(db: AsyncSession, page: int = 1, per_page: int = 15) -> tuple[list[User], int]:
    """获取用户列表（分页）"""
    # 总数
    count_result = await db.execute(select(func.count(User.id)))
    total = count_result.scalar_one()
    # 分页数据
    offset = (page - 1) * per_page
    result = await db.execute(
        select(User).options(joinedload(User.permissions)).order_by(User.id)
        .offset(offset).limit(per_page)
    )
    users = list(result.unique().scalars().all())
    return users, total


async def create_user(
    db: AsyncSession,
    username: str,
    password: str,
    is_super: bool,
    factory: str | None = None,
) -> User:
    """创建用户"""
    # 验证密码复杂度
    from utils.password_validator import PasswordValidator
    is_valid, error_msg = PasswordValidator.validate(password)
    if not is_valid:
        raise ValueError(error_msg)

    # 检查用户名唯一性
    result = await db.execute(
        select(User).where(User.username == username).with_for_update()
    )
    existing = result.scalar_one_or_none()
    if existing:
        raise ValueError("用户名已存在")

    from fastapi_app.core.security import hash_password
    new_user = User(
        username=username,
        password=hash_password(password),
        is_super=is_super,
        status=True,
        factory=factory or None,
    )
    db.add(new_user)
    await db.flush()
    await db.refresh(new_user)
    return new_user


async def update_user(
    db: AsyncSession,
    user_id: int,
    password: str | None,
    is_super: bool | None,
    factory: str | None = None,
) -> User:
    """更新用户

    factory 参数语义：
    - None：不修改
    - 空字符串或合法工厂值：写入（空字符串视为清除为 NULL）
    """
    result = await db.execute(select(User).where(User.id == user_id).with_for_update())
    user = result.scalar_one_or_none()
    if not user:
        raise ValueError("用户不存在")

    if password:
        from utils.password_validator import PasswordValidator
        is_valid, error_msg = PasswordValidator.validate(password)
        if not is_valid:
            raise ValueError(error_msg)
        from fastapi_app.core.security import hash_password
        user.password = hash_password(password)

    if is_super is not None:
        user.is_super = is_super

    if factory is not None:
        user.factory = factory or None

    await db.flush()
    await db.refresh(user)
    return user


async def toggle_user_status(db: AsyncSession, user_id: int) -> User:
    """切换用户状态"""
    result = await db.execute(select(User).where(User.id == user_id).with_for_update())
    user = result.scalar_one_or_none()
    if not user:
        raise ValueError("用户不存在")

    if user.is_super:
        raise ValueError("超级用户不能禁用")

    user.status = not user.status
    await db.flush()
    await db.refresh(user)
    return user


async def delete_user(db: AsyncSession, user_id: int) -> None:
    """删除用户"""
    user = await db.get(User, user_id)
    if not user:
        raise ValueError("用户不存在")

    if user.is_super:
        raise ValueError("超级用户不能删除")

    approval_count = await db.scalar(
        select(func.count()).select_from(ApprovalRequest).where(
            ApprovalRequest.requester_id == user_id,
            ApprovalRequest.status == ApprovalRequest.STATUS_PENDING,
        )
    )
    if approval_count and approval_count > 0:
        raise ValueError(f"该用户有 {approval_count} 个待处理审批请求，无法删除")

    # ⚠️ `not Order.is_deleted` 求值为 Python 布尔 False（不是 SQL 表达式），
    #    会让整个 WHERE 恒假 → locked_order_count 永远为 0 → 本守卫永不触发。
    #    必须用 SQLAlchemy 表达式（项目惯例 isnot(True)，列可空故 NULL 视为未删除）。
    #    `Order.is_locked` 同理改用 `is_(True)`：裸列虽可运行，但列可空时语义不清晰。
    locked_order_count = await db.scalar(
        select(func.count()).select_from(Order).where(
            Order.locked_by_id == user_id,
            Order.is_locked.is_(True),
            Order.is_deleted.isnot(True),
        )
    )
    if locked_order_count and locked_order_count > 0:
        raise ValueError(f"该用户锁定了 {locked_order_count} 个订单，无法删除")

    await db.delete(user)
    await db.flush()


async def get_permissions(db) -> list[Permission]:
    """获取所有权限（树形结构），section 排序与导航栏 SECTION_ORDER 保持一致"""
    result = await db.execute(
        select(Permission).options(
            joinedload(Permission.children)
        ).where(Permission.parent_id.is_(None))
        .order_by(Permission.sort_order)
    )
    permissions = list(result.unique().scalars().all())

    # 按 SECTION_ORDER 对 section 排序，与导航栏保持一致
    from fastapi_app.core.nav_context import SECTION_ORDER
    order_map = {sec: i for i, sec in enumerate(SECTION_ORDER)}

    def section_rank(p: Permission) -> int:
        return order_map.get(p.section or 'other', len(SECTION_ORDER))

    permissions.sort(key=lambda p: (section_rank(p), p.sort_order))
    # children 也按 sort_order 排序，确保子权限顺序稳定
    for p in permissions:
        if p.children:
            p.children.sort(key=lambda c: c.sort_order)
    return permissions


async def get_permissions_with_user_ids(db, target_user: User) -> tuple[list[Permission], list[int]]:
    """获取所有权限（树形结构）及目标用户的权限ID列表，合并为单次查询避免N+1问题"""
    permissions = await get_permissions(db)
    user_perm_ids = [p.id for p in target_user.permissions]
    return permissions, user_perm_ids


async def update_user_permissions(db: AsyncSession, user_id: int, permission_ids: list[int]) -> User:
    """更新用户权限"""
    logger.info(f"Updating permissions for user {user_id}: {permission_ids}")

    # 预加载 permissions 关系，避免异步上下文中懒加载触发 MissingGreenlet
    result = await db.execute(
        select(User).options(selectinload(User.permissions)).where(User.id == user_id)
    )
    user = result.unique().scalar_one_or_none()
    if not user:
        raise ValueError("用户不存在")

    # 清空现有权限
    user.permissions.clear()

    # 批量获取权限
    # 注：变量名不用 `result` —— 上方 `result` 已被推断为 Result[User]，
    # 复用同名变量会让 mypy 按首次赋值定型，进而把 Permission 误判为 User。
    perm_result = await db.execute(
        select(Permission).where(Permission.id.in_(permission_ids))
    )
    permissions = {p.id: p for p in perm_result.scalars().all()}
    logger.info(f"Loaded permissions: {list(permissions.keys())}")

    for pid in permission_ids:
        permission = permissions.get(pid)
        if permission:
            # 跳过敏感权限
            if permission.code in SENSITIVE_PERMISSIONS:
                logger.info(f"Skipping sensitive permission: {permission.code}")
                continue
            # 跳过已添加的权限
            if any(p.id == permission.id for p in user.permissions):
                continue
            user.permissions.append(permission)
        else:
            logger.warning(f"Permission {pid} not found")

    await db.flush()
    await db.refresh(user)
    logger.info(f"Permissions updated successfully for user {user_id}")
    return user


# ==================== 认证/管理查询函数（自 auth.py / user.py 端点下沉，纯查询搬移） ====================

async def get_user_with_permissions_by_id(db: AsyncSession, user_id: int) -> User | None:
    """按 ID 获取用户（预加载权限列表）"""
    result = await db.execute(
        select(User).options(selectinload(User.permissions)).where(User.id == user_id)
    )
    return result.unique().scalar_one_or_none()


async def get_user_with_permissions_by_username(db: AsyncSession, username: str) -> User | None:
    """按用户名获取用户（预加载权限列表，用于登录认证）"""
    result = await db.execute(
        select(User).where(User.username == username).options(
            selectinload(User.permissions)
        )
    )
    return result.unique().scalar_one_or_none()


async def get_user_auth_row_by_id(db: AsyncSession, user_id: int):
    """按 ID 获取用户认证状态行（id/status/username，用于令牌刷新校验）"""
    result = await db.execute(select(User.id, User.status, User.username).where(User.id == user_id))
    return result.first()


async def count_super_users(db: AsyncSession) -> int:
    """统计超级管理员数量（用于保护最后一个超管）"""
    super_count = await db.scalar(
        select(func.count()).select_from(User).where(User.is_super == True)  # noqa: E712
    )
    return int(super_count or 0)
