"""product 域服务子包。

按职责拆分 BOM / 角色相关服务：

- ``role_service``：角色名归一/比较工具（全局角色字典已随「角色产品私有化」下线）；
- ``bom_role_resolver``：``save_bom`` 的角色段解析（角色产品私有：id / role_key / 名称）。

此处 re-export 公开符号，保持 `from fastapi_app.services.product import ...` 可用。
"""
from .bom_role_resolver import RoleResolution, resolve_role_rows

__all__ = [
    'RoleResolution',
    'resolve_role_rows',
]
