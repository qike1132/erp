"""应用自定义异常"""

from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import HTTPException
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession


class AppError(Exception):
    """业务异常基类"""

    def __init__(self, message: str = "操作失败", code: str = "APP_ERROR", status_code: int = 400):
        self.message = message
        self.code = code
        self.status_code = status_code
        super().__init__(message)


class NotFoundError(AppError):
    """资源不存在异常"""

    def __init__(self, message: str = "资源不存在"):
        super().__init__(message=message, code="NOT_FOUND", status_code=404)


class BusinessError(AppError):
    """业务校验异常（如 ValueError 的 HTTP 封装）"""

    def __init__(self, message: str = "业务校验失败"):
        super().__init__(message=message, code="BUSINESS_ERROR", status_code=400)


class PermissionDeniedError(AppError):
    """权限不足异常"""

    def __init__(self, message: str = "权限不足"):
        super().__init__(message=message, code="PERMISSION_DENIED", status_code=403)


class ConflictError(AppError):
    """资源冲突异常（如并发修改、唯一约束冲突）"""

    def __init__(self, message: str = "资源冲突"):
        super().__init__(message=message, code="CONFLICT", status_code=409)


class InternalError(AppError):
    """服务器内部错误异常"""

    def __init__(self, message: str = "服务器内部错误"):
        super().__init__(message=message, code="INTERNAL_ERROR", status_code=500)


@asynccontextmanager
async def db_transaction(db: AsyncSession, *, commit: bool = True) -> AsyncIterator[None]:
    """数据库事务上下文管理器，统一处理 commit/rollback 和异常转换。

    用法：
        async with db_transaction(db):
            await some_service.create(db, ...)
        return ActionResponse(message='操作成功')

    异常处理：
        - ValueError → HTTP 400（业务校验失败）
        - SQLAlchemyError → HTTP 500（数据库异常，自动 rollback）
    """
    try:
        yield
        if commit:
            await db.commit()
    except ValueError as e:
        await db.rollback()
        raise HTTPException(status_code=400, detail=str(e)) from e
    except SQLAlchemyError as e:
        await db.rollback()
        raise HTTPException(status_code=500, detail="数据库操作失败") from e
