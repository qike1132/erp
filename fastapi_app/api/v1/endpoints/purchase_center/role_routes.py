"""采购中心 — 全局角色字典路由。

提供全局角色（跨产品复用）的最小维护能力：
``GET/POST /purchase-center/roles``、``PUT/DELETE /purchase-center/roles/{role_id}``。
权限一律 ``require_permission('product_manage')``。

错误契约：
- 名称冲突（``lower(trim(name))``）→ **400**；
- 角色不存在 → **404**；
- 删除被任意产品引用的角色 → **409**（REQ-P0-02 / Q-02，文案含引用数）。

注意：``role_service`` 的业务异常（``RoleNotFoundError`` / ``RoleNameConflictError`` /
``RoleReferencedError``）均继承 ``ValueError``，而 ``db_transaction`` 默认把
``ValueError`` 一律映射为 400。故必须通过 ``error_map`` 显式声明各异常的目标状态码，
否则 404/409 会被默认规则吞成 400（覆盖默认规则的唯一正规途径）。
"""
from collections.abc import Callable, Mapping
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from fastapi_app.core.database import get_async_db as get_db
from fastapi_app.core.database import get_async_read_db as get_read_db
from fastapi_app.core.deps import require_permission
from fastapi_app.core.exceptions import db_transaction
from fastapi_app.core.logger import logger
from fastapi_app.core.response import success_response
from fastapi_app.schemas.purchase_center import (
    RoleCreate,
    RoleDeleteResponse,
    RoleListResponse,
    RoleRename,
)
from fastapi_app.services.product import role_service
from fastapi_app.services.product.role_service import (
    RoleNameConflictError,
    RoleNotFoundError,
    RoleReferencedError,
)

router = APIRouter()


def get_role_service():
    """返回全局角色服务模块（模块级函数集合）。

    作为 FastAPI 依赖暴露，测试可用 app.dependency_overrides 注入替身。
    """
    return role_service


def _map_not_found(exc: Exception) -> HTTPException:
    """角色不存在 → 404。"""
    return HTTPException(status_code=404, detail=str(exc))


def _map_conflict(exc: Exception) -> HTTPException:
    """名称冲突（lower(trim(name))）→ 400。"""
    return HTTPException(status_code=400, detail=str(exc))


def _map_referenced(exc: Exception) -> HTTPException:
    """删除被引用角色 → 409（文案含引用数），并留一条 info 便于审计。"""
    logger.info('拒绝删除被引用角色: detail=%s', exc)
    return HTTPException(status_code=409, detail=str(exc))


# 覆盖 db_transaction 的默认「ValueError → 400」规则（按需声明目标状态码）
_ROLE_ERROR_MAP: Mapping[type[Exception] | tuple[type[Exception], ...], Callable[[Exception], HTTPException]] = {
    RoleNotFoundError: _map_not_found,
    RoleNameConflictError: _map_conflict,
    RoleReferencedError: _map_referenced,
}


@router.get('/roles', response_model=RoleListResponse)
async def api_list_roles(
    db: AsyncSession = Depends(get_read_db),
    _current_user=Depends(require_permission('product_manage')),
    svc=Depends(get_role_service),
) -> dict[str, Any]:
    """列出全部全局角色（跨产品复用字典）。"""
    roles = await svc.list_roles(db)
    return success_response(roles=roles)


@router.post('/roles')
async def api_create_role(
    data: RoleCreate,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_permission('product_manage')),
    svc=Depends(get_role_service),
) -> dict[str, Any]:
    """新建全局角色；名称冲突返回 400。"""
    async with db_transaction(db, error_map=_ROLE_ERROR_MAP):
        role = await svc.create_role(db, data.name, current_user.username)
    return success_response(role=role)


@router.put('/roles/{role_id}')
async def api_rename_role(
    role_id: int,
    data: RoleRename,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_permission('product_manage')),
    svc=Depends(get_role_service),
) -> dict[str, Any]:
    """重命名全局角色；改名同步镜像列、不改物料归属（按 id）；冲突 400 / 不存在 404。"""
    async with db_transaction(db, error_map=_ROLE_ERROR_MAP):
        role = await svc.rename_role(db, role_id, data.name, current_user.username)
    return success_response(role=role)


@router.delete('/roles/{role_id}', response_model=RoleDeleteResponse)
async def api_delete_role(
    role_id: int,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_permission('product_manage')),
    svc=Depends(get_role_service),
) -> dict[str, Any]:
    """删除全局角色；被任意产品引用时返回 409 且文案含引用数。"""
    async with db_transaction(db, error_map=_ROLE_ERROR_MAP):
        message = await svc.delete_role(db, role_id, current_user.username)
    return success_response(message=message)
