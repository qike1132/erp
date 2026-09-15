"""应用自定义异常与统一错误响应工具"""
from __future__ import annotations

import logging
import uuid
from collections.abc import AsyncIterator, Callable, Mapping
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any

from fastapi import HTTPException
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


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


# ---------------------------------------------------------------------------
# 统一错误响应工具
# ---------------------------------------------------------------------------

def make_error_response(
    *,
    code: str,
    message: str,
    status_code: int = 400,
    request_id: str | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    构造统一结构的错误响应体。

    返回结构：
        {
            "success": False,
            "error": {
                "code": "BUSINESS_ERROR",
                "message": "操作失败",
                "request_id": "uuid-or-trace-id",
                "timestamp": "2026-06-24T09:30:00",
                "extra": {...}
            }
        }
    """
    payload: dict[str, Any] = {
        'success': False,
        'error': {
            'code': code,
            'message': message,
            'request_id': request_id or _generate_request_id(),
            'timestamp': datetime.now(UTC).isoformat(timespec='seconds').replace('+00:00', 'Z'),
        },
    }
    if extra:
        payload['error']['extra'] = extra
    return payload


def _generate_request_id() -> str:
    """生成短格式请求ID，便于日志关联。"""
    return uuid.uuid4().hex[:16]


def current_iso_timestamp() -> str:
    """统一的 UTC ISO8601 时间戳字符串。"""
    return datetime.now(UTC).isoformat(timespec='seconds').replace('+00:00', 'Z')


def new_request_id() -> str:
    """公开的 request_id 生成函数，供全局 exception handler 等使用。"""
    return _generate_request_id()


def http_error(
    *,
    status_code: int,
    code: str,
    message: str,
    extra: dict[str, Any] | None = None,
) -> HTTPException:
    """
    构造一个带有统一错误响应体的 HTTPException。

    使用方式：
        raise http_error(status_code=400, code='BUSINESS_ERROR', message='...')
    """
    return HTTPException(
        status_code=status_code,
        detail=make_error_response(
            code=code, message=message, status_code=status_code, extra=extra,
        ),
    )


def app_error_to_http(app_error: AppError) -> HTTPException:
    """将业务异常转换为带有统一响应体的 HTTPException。"""
    return http_error(
        status_code=app_error.status_code,
        code=app_error.code,
        message=app_error.message,
    )


@asynccontextmanager
async def db_transaction(
    db: AsyncSession,
    *,
    commit: bool = True,
    error_map: Mapping[type[Exception] | tuple[type[Exception], ...], _ErrorMapValue] | None = None,
) -> AsyncIterator[None]:
    """数据库事务上下文管理器，统一处理 commit/rollback 和异常转换。

    用法：
        async with db_transaction(db):
            await some_service.create(db, ...)
        return ActionResponse(message='操作成功')

    异常处理（默认）：
        - ValueError → HTTP 400（业务校验失败）
        - SQLAlchemyError → HTTP 500（数据库异常，自动 rollback）

    异常处理（error_map，优先于默认规则）：
        需要将唯一约束冲突映射为 409 等特定状态码时，传入 error_map 声明
        异常类型 → HTTP 响应的映射，无需在端点内手动 commit/catch：
            - 值为 (status_code, detail) 元组：固定响应；
            - 值为 callable(exc) -> HTTPException：可记录日志、拼接动态 detail。
        按字典注册顺序取首个 isinstance 命中；未命中走默认规则。
        注意被映射类型若为 ValueError 子类（如 PlanExistsError），
        也必须通过 error_map 声明才能覆盖默认的 400 转换。

    Post-commit 回调：
        服务层可将需要在事务提交成功后执行的异步回调注册到
        db.info['post_commit_callbacks'] 列表中。db_transaction 在 commit 成功后
        会按注册顺序执行这些回调；如果 commit 失败或发生回滚，则不会执行。
        适用于缓存失效、事件发布等必须在持久化完成后才执行的操作。
    """
    try:
        try:
            yield
            if commit:
                await db.commit()
        except Exception as e:  # broad-except: 必须捕获全部异常以保证任何失败路径都 rollback（收窄会残留脏会话）
            mapped = _match_error_map(error_map, e)
            if mapped is not None:
                await db.rollback()
                raise mapped from e
            # 未映射的异常（含 HTTPException 等）也必须 rollback，避免会话残留
            # 脏状态被后续请求复用后误提交
            await db.rollback()
            raise
    except NotFoundError as e:
        await db.rollback()
        raise HTTPException(status_code=e.status_code, detail=e.message) from e
    except AppError as e:
        await db.rollback()
        raise HTTPException(status_code=e.status_code, detail=e.message) from e
    except ValueError as e:
        await db.rollback()
        raise HTTPException(status_code=400, detail=str(e)) from e
    except SQLAlchemyError as e:
        await db.rollback()
        raise HTTPException(status_code=500, detail="数据库操作失败") from e
    else:
        if commit:
            callbacks = db.info.pop('post_commit_callbacks', [])
            for callback in callbacks:
                try:
                    await callback()
                except Exception as e:  # broad-except: 异常处理框架内部兜底
                    logger.error("post-commit 回调执行失败: %s", e, exc_info=True)


# error_map 的值：固定 (状态码, 响应文本) 或根据异常实例构造 HTTPException 的工厂
_ErrorMapValue = tuple[int, str] | Callable[[Exception], HTTPException]


def _match_error_map(
    error_map: Mapping[type[Exception] | tuple[type[Exception], ...], _ErrorMapValue] | None,
    exc: Exception,
) -> HTTPException | None:
    """按注册顺序返回首个 isinstance 命中的映射结果；未命中返回 None。"""
    if not error_map:
        return None
    for exc_types, handler in error_map.items():
        if isinstance(exc, exc_types):
            if isinstance(handler, tuple):
                status_code, detail = handler
                return HTTPException(status_code=status_code, detail=detail)
            return handler(exc)
    return None
