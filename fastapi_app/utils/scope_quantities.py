"""陈列样「6 常规款均分 + 隐藏款随箱配比」的作用域数量分配（纯函数）。

背景
----
《蛋仔派对》市集拾趣系列毛绒公仔挂件盲盒（陈列样）这类 SKU 的采购口径
（2026-11-07 与需求方确认）：

- **N**：该 SKU 的订单数量（采购生成按「同客户组内同 SKU 合并后的总量」取 N）；
- **常规款 6 款**：``base = N // 6``，``rem = N % 6``；按固定角色顺序
  前 ``rem`` 款各 +1，六款合计**恒等于 N**（不是每款都按 N 采购）；
- **隐藏款 1 款**：随箱额外配置，``H = ceil(N / P)``，P 为 SKU 主数据
  ``product.hidden_carton_ratio``（用户填写的随箱配比，正整数）；
  隐藏款不占用 N（实际采购总量 = N + H）；
- **P 为空（NULL）= 不启用本规则**：所有作用域一律使用完整 N（历史口径，
  由回归测试锁死，存量 SKU 零行为变化）。

设计约束
--------
- 纯函数、不查库：采购生成（``purchase_order_generate``）与物料计算器
  （``purchase_product_service``）共用同一实现，保证「计算器算出来的」与
  「一键生成落单的」数量一致（与 utils.scope_order 同一动机）；
- 整数运算（``divmod`` / ``(N + P - 1) // P``），不经过 float ceil，
  杜绝精度漂移；
- fail-closed：P 非正整数、N 非非负整数、角色结构不是「6 常规 + 1 隐藏款」
  时**明确报错**，绝不静默错算（历史教训：fail-open 闸门放过脏配置）。
"""
from __future__ import annotations

from collections.abc import Callable, Iterable
from decimal import Decimal, InvalidOperation

from fastapi_app.utils.scope_order import order_scopes

# 隐藏款角色的约定显示名（与 BOM 配置页的角色名一致；识别按「strip 后全等」，
# 绝不做模糊包含匹配，避免「隐藏款-黄蛋」这类近似名被静默当成隐藏款）
HIDDEN_ROLE_NAME = '隐藏款'

# 常规款数量（业务口径固定 6 款；抽取为常量便于测试与将来口径调整）
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
    base, remainder = divmod(total_qty, count)
    return [base + (1 if index < remainder else 0) for index in range(count)]


def hidden_quantity(total_qty: int, carton_ratio: int) -> int:
    """隐藏款用量 = ``ceil(total_qty / carton_ratio)``（不足一箱按一箱配 1 个）。

    例：N=10000、P=72 → 139；N=10000、P=100 → 100。
    """
    if carton_ratio < 1:
        raise ValueError(f'隐藏款随箱配比必须是正整数，当前为 {carton_ratio!r}')
    return (total_qty + carton_ratio - 1) // carton_ratio


def allocate_scope_quantities(
    quantity: object,
    role_ids: Iterable[int | None],
    *,
    hidden_carton_ratio: int | None,
    name_of: Callable[[int], str | None] | None = None,
) -> dict[int | None, object]:
    """按陈列样口径把 ``quantity`` 分配到各 BOM 作用域。

    Args:
        quantity: 该 SKU 的订单数量（启用规则时必须是非负整数）。
        role_ids: 该 SKU 出现的作用域 role_id 集合（可含 ``None``=默认 BOM、
            可含「配了角色但暂无物料」的声明角色——与生成/计算器的作用域
            装配口径一致，见 purchase_order_generate._load_bom_context）。
        hidden_carton_ratio: 隐藏款随箱配比 P；``None`` = 不启用本规则。
        name_of: 角色名解析函数（role_id → 显示名）。隐藏款按显示名
            全等 ``'隐藏款'`` 识别；余数分配顺序 = 显示名升序（order_scopes）。

    Returns:
        dict: ``{role_id: 数量乘子}``。``None``（默认 BOM）恒在返回值中且
        使用完整 ``quantity``；未启用规则时所有作用域一律完整 ``quantity``。

    Raises:
        ValueError: P 非正整数 / N 非非负整数 / 角色结构不是
            「6 个常规款 + 1 个隐藏款」。
    """
    # 未配置 P：历史口径——每个作用域都用完整数量，不做任何结构校验
    if hidden_carton_ratio is None:
        allocation: dict[int | None, object] = dict.fromkeys(set(role_ids), quantity)
        allocation[None] = quantity
        return allocation

    if isinstance(hidden_carton_ratio, bool) or not isinstance(hidden_carton_ratio, int):
        raise ValueError(f'隐藏款随箱配比必须是正整数，当前为 {hidden_carton_ratio!r}')
    if hidden_carton_ratio < 1:
        raise ValueError(f'隐藏款随箱配比必须是正整数，当前为 {hidden_carton_ratio!r}')

    total = _to_total_int(quantity)

    scopes = order_scopes(set(role_ids) | {None}, name_of)
    # 局部变量承接 name_of：mypy 对「参数在闭包/推导式内收窄」不稳，局部变量可收窄
    resolver = name_of
    hidden_scopes = [
        rid for rid in scopes
        if rid is not None and resolver is not None
        and (resolver(rid) or '').strip() == HIDDEN_ROLE_NAME
    ]
    regular_scopes = [rid for rid in scopes if rid is not None and rid not in hidden_scopes]

    if len(hidden_scopes) != 1 or len(regular_scopes) != REGULAR_ROLE_COUNT:
        raise ValueError(
            f'配置了隐藏款随箱配比={hidden_carton_ratio} 的陈列样 SKU 需要 6 个常规款'
            f'和 1 个隐藏款（当前常规款 {len(regular_scopes)} 个、'
            f'「{HIDDEN_ROLE_NAME}」{len(hidden_scopes)} 个），请先在 BOM 配置中补齐角色'
        )

    allocation = {None: quantity}
    allocation[hidden_scopes[0]] = hidden_quantity(total, hidden_carton_ratio)
    for rid, per_role_qty in zip(regular_scopes, split_regular_quantities(total), strict=True):
        allocation[rid] = per_role_qty
    return allocation
