"""角色名工具（BOM 角色已「产品私有」化）。

背景：BOM 角色原为**跨产品共享的全局字典**（`role` 表 + `product_role.global_role_id`）。
业务上各 SKU 角色互相独立，故迁移 088（放宽约束）+ 089（删列删表）把它退回产品私有，
全局字典与相关 CRUD（list/create/rename/delete/ensure_global_role/apply_global_rename）
随之下线。本模块只保留**角色名归一/比较**这两个仍有用的工具，供
``bom_role_resolver`` 复用。

名字口径：归一 = ``trim``；比较键 = ``lower(trim(name))``，与 DB 的
``uq_product_role_product_name_lower (product_id, lower(role_name))`` 一致
（写入前已 trim，故索引侧只需 lower）。
"""
from __future__ import annotations

from fastapi_app.core.exceptions import BusinessError

_MAX_NAME_LEN = 100


def _normalize_name(name: str | None) -> str:
    """trim 角色名并做基础校验；空/超长抛 ``BusinessError``（→ HTTP 400）。"""
    normalized = (name or '').strip()
    if not normalized:
        raise BusinessError('角色名不能为空')
    if len(normalized) > _MAX_NAME_LEN:
        raise BusinessError(f'角色名长度不能超过 {_MAX_NAME_LEN} 字符')
    return normalized


def _name_key(name: str | None) -> str:
    """大小写不敏感比较键（``lower(trim(name))``），与 DB 唯一索引口径一致。"""
    return (name or '').strip().lower()
