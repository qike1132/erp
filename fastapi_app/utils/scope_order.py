"""作用域（BOM 角色作用域）排序与显示名的**统一口径**。

背景
----
「默认 BOM + 各角色」的作用域枚举在两处独立存在：

1. 采购单生成：``services/purchase_order_generate._scope_order``
2. 物料计算器：``services/purchase_product_service.aggregate_materials_by_scope``

两处若各自实现排序，口径极易漂移（一处按 id、一处按名），导致「计算器算出来的
分块顺序」与「一键生成落单的顺序」不一致，前端分块错乱。本模块以**纯函数**固化
唯一口径，供两处共用（架构设计 §7 共享约定 #2 / Q-05）。

口径
----
- 默认 BOM（``role_id is None``）**恒在首位**；
- 其余作用域按「显示名升序，名同按 role_id 升序」；
- 去重；``None`` 最多出现一次。
"""
from __future__ import annotations

from collections.abc import Callable, Iterable

# BOM 作用域显示名：role_id=None 即产品级默认 BOM
DEFAULT_SCOPE_LABEL = '默认BOM'


def scope_label(role_id: int | None, role_name: str | None = None) -> str:
    """作用域显示名。

    角色名缺失时退化为 ``角色#<id>`` 而非空串：既便于现场定位脏数据，也保证
    排序键非空且互不相同（不会因多个角色名皆空而坍缩成同一键）。

    Args:
        role_id: 角色 ID；``None`` 表示产品级默认 BOM。
        role_name: 角色显示名（可为空串或 ``None``）。

    Returns:
        str: 默认 BOM 返回 ``'默认BOM'``；具名角色返回其名；
        无名角色返回 ``'角色#<id>'``。
    """
    if role_id is None:
        return DEFAULT_SCOPE_LABEL
    return (role_name or '').strip() or f'角色#{role_id}'


def order_scopes(
    role_ids: Iterable[int | None],
    name_of: Callable[[int], str | None] | None = None,
) -> list[int | None]:
    """按统一口径对作用域去重并排序。

    排序键 = ``(scope_label(rid, name_of(rid) if name_of else None), rid)``；
    默认 BOM 恒在首位。

    Args:
        role_ids: 待排序的作用域 role_id 集合（可含 ``None``）。
        name_of: 角色名解析函数：给定 role_id 返回显示名（或 ``None``）。
            采购单生成传入 ``lambda rid: role_names.get((pid, rid))``；
            计算器按产品分别构造。为 ``None`` 时全部视为无名，此时**按 role_id
            数值升序**（与历史调用方口径一致，见下）。

    Returns:
        list[int | None]: 默认 BOM（``None``）在首位，其余按
        （显示名, role_id）升序；去重且 ``None`` 至多一次。

    Note:
        ``name_of is None`` 时必须按 **id 数值**升序，而不是按 ``'角色#<id>'``
        的字典序——后者在跨位数时会与历史「按 id 升序」静默分叉：
        ``'角色#12' < '角色#3'`` ⇒ ``{3, 12}`` 会得到 ``[12, 3]`` 而非 ``[3, 12]``。
        历史 ``_scope_order`` 的口径就是 id 升序，故无名路径保持数值序才是向后兼容。
    """
    present = set(role_ids)
    named = [rid for rid in present if rid is not None]

    if name_of is None:
        # 无名可解析：按 id 数值升序（见 Note，避免跨位数时的字典序分叉）
        ordered = sorted(named)
    else:
        ordered = sorted(
            named,
            key=lambda rid: (scope_label(rid, name_of(rid)), rid),
        )

    return ([None] if None in present else []) + ordered
