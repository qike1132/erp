"""product 域服务子包。

按职责拆分 BOM / 角色相关服务，避免 ``bom_service`` 单文件继续膨胀（风险 M2）：

- ``role_service``：全局角色字典（role 表）CRUD + 被引用保护 + 名称唯一校验；
- ``bom_role_resolver``：``save_bom`` 的角色段解析（global_role_id / role_key / id 三路径）。

此处 re-export 公开符号，保持 `from fastapi_app.services.product import ...` 可用。
"""
from .bom_role_resolver import RoleResolution, resolve_role_rows
from .role_service import (
    RoleNameConflictError,
    RoleNotFoundError,
    RoleReferencedError,
    apply_global_rename,
    create_role,
    delete_role,
    list_roles,
    rename_role,
)

__all__ = [
    'RoleNameConflictError',
    'RoleNotFoundError',
    'RoleReferencedError',
    'RoleResolution',
    'apply_global_rename',
    'create_role',
    'delete_role',
    'list_roles',
    'rename_role',
    'resolve_role_rows',
]
