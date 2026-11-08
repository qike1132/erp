"""盲盒 SKU 的订单数量分配（纯函数）：按角色数均分 + 隐藏款随箱配比。

背景
----
产品录入新增「盲盒」选择项（2026-11-08 需求）：勾选后展开「盲盒隐藏款装箱配比」
与「该 SKU 是否有隐藏款」，采购口径分三档：

- **非盲盒**（``is_blind_box=False``）：存量口径——每个作用域都用完整订单数量，
  不做任何均分（未勾选盲盒的 SKU 零行为变化）；
- **盲盒、无隐藏款**（``has_hidden_role=False``）：隐藏款配置不启用，订单数量
  按「**角色数量**」均分（含名为「隐藏款」的角色，它只是普通角色之一）；
- **盲盒、有隐藏款**且配比 P 非空：BOM 须恰有 1 个隐藏款；常规角色按「**常规
  角色数量**」均分（常规 4 + 隐藏 1 → N/4；常规 8 + 隐藏 1 → N/8），隐藏款额外
  ``ceil(N/P)``（不占用 N，实际采购总量 = N + H）；**配比留空 = 不额外配隐藏款**，
  退化为「按角色数量均分」。

均分细节：``base = N // R``、``rem = N % R``，按 ``role_id`` 升序（角色创建
顺序/角色编码序，与展示用的名称序解耦）前 ``rem`` 个各 +1，**合计恒等于 N**。

隐藏款角色的识别：优先按 BOM 角色页签右键指定的 ``product_role.is_hidden``
（角色可任意命名）；未指定时回退「角色名**精确**等于三个字『隐藏款』」——
严格全等，不 trim、不做包含/后缀匹配。

设计约束
--------
- 纯函数、不查库：采购生成（``purchase_order_generate``）、物料计算器
  （``purchase_product_service``）与工厂推算共用同一实现，保证三方数量一致；
- 整数运算（``divmod`` / ``(N + P - 1) // P``），不经过 float ceil，
  杜绝精度漂移；
- fail-closed：N 非非负整数、P 非正整数、有隐藏款时隐藏款角色不是恰好 1 个、
  盲盒没有任何参与均分的角色时**明确报错**，绝不静默错算。
"""
from __future__ import annotations

from collections.abc import Callable, Iterable
from decimal import Decimal, InvalidOperation

from fastapi_app.utils.scope_order import order_scopes

# 隐藏款角色的约定显示名（与 BOM 配置页的角色名一致；识别按**严格全等**，
# 绝不做模糊包含匹配，前后空格/后缀都不算，避免「隐藏款-黄蛋」这类近似名被静默当成隐藏款）
HIDDEN_ROLE_NAME = '隐藏款'

# 历史固定口径（6 常规款）的默认份数；盲盒实际按 BOM 中参与均分的角色数量传入
REGULAR_ROLE_COUNT = 6


def _to_total_int(quantity: object) -> int:
    """把订单数量收敛为非负整数；无法收敛时抛 ValueError（fail-closed）。

    接受 int / 整值 float / 整值 Decimal / 数值字符串；拒绝布尔、负数、
    带小数部分的值——陈列样按「个」采购， fractional 数量会让
    「六款合计恒等于 N」的不变量失真。
    """
    if isinstance(quantity, bool):
        raise ValueError('采购数量必须是非负整数')
    if isinstance(quantity, int):
        if quantity < 0:
            raise ValueError('采购数量必须是非负整数')
        return quantity
    if isinstance(quantity, float):
        if quantity < 0 or not quantity.is_integer():
            raise ValueError('采购数量必须是非负整数')
        return int(quantity)
    if isinstance(quantity, Decimal):
        if quantity < 0 or quantity != quantity.to_integral_value():
            raise ValueError('采购数量必须是非负整数')
        return int(quantity)
    try:
        return _to_total_int(Decimal(str(quantity)))
    except (InvalidOperation, ValueError, TypeError):
        raise ValueError('采购数量必须是非负整数') from None


def split_regular_quantities(total_qty: int, count: int = REGULAR_ROLE_COUNT) -> list[int]:
    """把 ``total_qty`` 均分给 ``count`` 个常规款：floor + 余数按顺序逐款 +1。

    返回按固定角色顺序（显示名升序，见 order_scopes）排列的各款数量，
    ``sum(返回值) == total_qty`` 恒成立。

    例：``10000 // 6 = 1666 余 4`` → ``[1667, 1667, 1667, 1667, 1666, 1666]``。
    """
    if total_qty < 0:
        raise ValueError('采购数量必须是非负整数')
    if count < 1:
        raise ValueError(f'参与均分的角色数量必须为正整数，当前为 {count!r}')
    base, remainder = divmod(total_qty, count)
    return [base + (1 if index < remainder else 0) for index in range(count)]


def hidden_quantity(total_qty: int, carton_ratio: int) -> int:
    """隐藏款用量 = ``ceil(total_qty / carton_ratio)``（不足一箱按一箱配 1 个）。

    例：N=10000、P=72 → 139；N=10000、P=100 → 100。
    """
    if total_qty < 0:
        raise ValueError('采购数量必须是非负整数')
    if carton_ratio < 1:
        raise ValueError(f'盲盒隐藏款装箱配比必须是正整数，当前为 {carton_ratio!r}')
    return (total_qty + carton_ratio - 1) // carton_ratio


def _validate_ratio(hidden_carton_ratio: object) -> int:
    """配比必须是真实正整数（bool 也不算，Pydantic 宽松模式会把它转成 1/0）。"""
    if isinstance(hidden_carton_ratio, bool) or not isinstance(hidden_carton_ratio, int):
        raise ValueError(f'盲盒隐藏款装箱配比必须是正整数，当前为 {hidden_carton_ratio!r}')
    if hidden_carton_ratio < 1:
        raise ValueError(f'盲盒隐藏款装箱配比必须是正整数，当前为 {hidden_carton_ratio!r}')
    return hidden_carton_ratio


def _resolve_hidden_scopes(
    scopes: list, scope_set: set, resolver: Callable[[int], str | None] | None,
    hidden_role_id: int | None,
) -> list[int]:
    """隐藏款候选 = 「右键指定」∪「名字精确等于『隐藏款』」，按 id 升序返回。

    两者同时存在视为配置冲突（每 SKU 只允许一个隐藏款），由调用方按
    ``len(...) != 1`` fail-closed 报错。
    """
    candidates = {
        rid for rid in scopes
        if rid is not None and resolver is not None
        and resolver(rid) == HIDDEN_ROLE_NAME
    }
    if hidden_role_id is not None and hidden_role_id in scope_set:
        candidates.add(hidden_role_id)
    return sorted(candidates)


def _allocate_with_hidden(
    total: int, named_scopes: list[int], hidden_scopes: list[int], hidden_carton_ratio: int,
) -> dict[int | None, object]:
    """有隐藏款：常规角色按常规角色数均分 + 隐藏款 ``ceil(N/P)``。"""
    _validate_ratio(hidden_carton_ratio)
    regular_scopes = [rid for rid in named_scopes if rid not in hidden_scopes]
    if len(hidden_scopes) != 1:
        raise ValueError(
            f'配置了盲盒隐藏款装箱配比={hidden_carton_ratio} 的 SKU 需要恰好 1 个隐藏款'
            f'（当前 {len(hidden_scopes)} 个）。请先在 BOM 角色页签右键指定隐藏款，'
            '或把角色名精确命名为「隐藏款」；若两者同时存在，请只保留一种'
        )
    if not regular_scopes:
        raise ValueError(
            f'配置了盲盒隐藏款装箱配比={hidden_carton_ratio} 的 SKU 至少需要 1 个常规角色'
            '（当前 0 个），请先在 BOM 配置常规角色',
        )
    allocation: dict[int | None, object] = {None: total}
    allocation[hidden_scopes[0]] = hidden_quantity(total, hidden_carton_ratio)
    for rid, per_role_qty in zip(
        regular_scopes, split_regular_quantities(total, len(regular_scopes)), strict=True,
    ):
        allocation[rid] = per_role_qty
    return allocation


def _allocate_even(total: int, named_scopes: list[int]) -> dict[int | None, object]:
    """无隐藏款（或配比留空）：订单数量按「角色数量」均分。"""
    if not named_scopes:
        raise ValueError(
            '盲盒 SKU 至少需要 1 个角色才能按「订单数量÷角色数量」计算，'
            '请先在 BOM 配置角色',
        )
    allocation: dict[int | None, object] = {None: total}
    for rid, per_role_qty in zip(
        named_scopes, split_regular_quantities(total, len(named_scopes)), strict=True,
    ):
        allocation[rid] = per_role_qty
    return allocation


def allocate_scope_quantities(
    quantity: object,
    role_ids: Iterable[int | None],
    *,
    hidden_carton_ratio: int | None,
    name_of: Callable[[int], str | None] | None = None,
    hidden_role_id: int | None = None,
    blind_box: bool = False,
    has_hidden: bool = False,
) -> dict[int | None, object]:
    """把订单数量按 SKU 口径分配到各 BOM 作用域（三档，见下）。

    口径（2026-11-08 需求）：

    - ``blind_box=False``：**存量口径**，每个作用域都用完整订单数量，
      不校验、不分配（未勾选「盲盒」的 SKU 零行为变化）；
    - ``blind_box=True, has_hidden=False``：盲盒但**没有隐藏款**——隐藏款配置不
      启用，订单数量按「**角色数量**」均分（含名为「隐藏款」的角色，它只是普通
      角色之一）；
    - ``blind_box=True, has_hidden=True`` 且配比非空：**有隐藏款**——BOM 须恰有
      1 个隐藏款（右键指定或名字精确等于「隐藏款」），常规角色按「**常规角色
      数量**」均分（常规 4 + 隐藏 1 → N/4；常规 8 + 隐藏 1 → N/8），隐藏款额外
      ``ceil(N/P)``；配比留空 = 不额外配隐藏款，退化为「按角色数量均分」。

    Args:
        quantity: 该 SKU 的订单数量（盲盒口径下必须是非负整数）。
        role_ids: 该 SKU 出现的作用域 role_id 集合（可含 ``None``=默认 BOM、
            可含「配了角色但暂无物料」的声明角色）。
        hidden_carton_ratio: 盲盒隐藏款装箱配比 P；``None`` = 不额外配隐藏款。
        name_of: 角色名解析函数（role_id → 显示名）。余数分配顺序 = role_id
            升序（与展示用的名称序解耦）。
        hidden_role_id: 右键指定的隐藏款角色 id（``product_role.is_hidden``）。
            **优先**按它识别；未指定（None）时回退「名字精确等于『隐藏款』」
            （严格全等，不 trim、不做包含匹配——需求明确禁止空格/后缀修饰）。
        blind_box: 是否盲盒 SKU（``product.is_blind_box``）。
        has_hidden: 该盲盒 SKU 是否有隐藏款（``product.has_hidden_role``）。

    Returns:
        dict: ``{role_id: 数量乘子}``。``None``（默认 BOM）恒用完整 ``quantity``；
        非盲盒时所有作用域一律完整 ``quantity``。

    Raises:
        ValueError: 盲盒口径下 N 非非负整数 / P 非正整数 / 有隐藏款但隐藏款角色
            不是恰好 1 个 / 没有任何参与均分的角色。
    """
    scope_set = set(role_ids)

    # 非盲盒：存量口径——每个作用域都用完整数量，不做任何结构校验
    if not blind_box:
        allocation = dict.fromkeys(scope_set, quantity)
        allocation[None] = quantity
        return allocation

    total = _to_total_int(quantity)
    scopes = order_scopes(scope_set | {None}, name_of)
    named_scopes = sorted(rid for rid in scopes if rid is not None)
    hidden_scopes = _resolve_hidden_scopes(scopes, scope_set, name_of, hidden_role_id)

    # 有隐藏款且配比非空：常规角色按常规角色数均分 + 隐藏款 ceil(N/P)；
    # 其余情况（无隐藏款 / 配比留空）：按角色数量均分。
    if has_hidden and hidden_carton_ratio is not None:
        return _allocate_with_hidden(total, named_scopes, hidden_scopes, hidden_carton_ratio)
    return _allocate_even(total, named_scopes)
