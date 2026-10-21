"""
采购模块共享工具函数

从 purchase_order_service.py 提取的重复逻辑，集中管理采购相关的纯函数工具。

包含：
- parse_source_order_ids: 解析采购订单关联的客户订单ID列表
- normalize_spare_rate: 归一化损耗率（千分之几）
- calc_spare_quantity: 计算备品数量（前后端同源的唯一后端实现）
- resolve_item_loss_rate: 解析明细行的有效损耗率（逐行 → 订单级 → 0）
- magnified_purchase_qty: 计价数量（落库数量按损耗率加放，不取整）
"""
import json
import logging
import math
from decimal import Decimal, InvalidOperation

logger = logging.getLogger(__name__)


def parse_source_order_ids(source_order_ids: str | list | None) -> list[int]:
    """解析采购订单的 source_order_ids 字段为整数 ID 列表。

    该字段可能以两种形式存储：
    - JSON 字符串（如 '[1, 2, 3]'）
    - 已反序列化的 list

    解析失败时返回空列表，不抛出异常，与原内联实现保持一致。

    注意：本函数仅处理 source_order_ids 字段本身；
    若需同时合并 source_order_id（单值字段），请由调用方自行追加。

    Args:
        source_order_ids: 原始字段值，可为 JSON 字符串、list 或 None。

    Returns:
        解析后的整数 ID 列表；输入为空或解析失败时返回空列表。
    """
    if not source_order_ids:
        return []
    try:
        parsed = json.loads(source_order_ids) if isinstance(source_order_ids, str) else source_order_ids
        return [int(x) for x in parsed]
    except (ValueError, TypeError):
        return []


def normalize_spare_rate(rate: float | None) -> float | None:
    """归一化损耗率（单位：千分之几）。

    口径与前端 `useSummaryModal.calcSpareQuantity` 保持一致：
    - `None` → `None`（语义为「不覆盖已存值 / 跳过」）；
    - 非数值或非有限值（NaN/Inf）→ `0.0`；
    - `< 0`（非法）→ `0.0`；
    - `> 1000` → 截断为 `1000.0`（与前端输入框 `max=1000` 一致）；
    - 其余原值返回。

    Args:
        rate: 原始损耗率，可为 None。

    Returns:
        归一化后的损耗率；输入为 None 时返回 None。
    """
    if rate is None:
        return None
    try:
        value = float(rate)
    except (TypeError, ValueError):
        return 0.0
    if not math.isfinite(value) or value < 0:
        return 0.0
    if value > 1000:
        return 1000.0
    return value


def calc_spare_quantity(qty: float | None, rate: float | None) -> int:
    """计算备品数量：`ceil(qty × rate / 1000)`（前后端同源的唯一后端实现）。

    与前端 `calcSpareQuantity` 语义逐字一致：
    - 归一化后 `rate` 为 `None` / `<= 0`，或 `qty` 非有限 / `<= 0` → `0`；
    - 否则返回 `math.ceil(qty × rate / 1000)`（向上取整到整数）。

    Args:
        qty: 订单数量（可含小数）。
        rate: 损耗率（千分之几）。

    Returns:
        向上取整后的备品数量（非负整数）。
    """
    normalized = normalize_spare_rate(rate)
    if normalized is None or normalized <= 0:
        return 0
    if qty is None:
        return 0
    try:
        quantity = float(qty)
    except (TypeError, ValueError):
        return 0
    if not math.isfinite(quantity) or quantity <= 0:
        return 0
    return math.ceil(quantity * normalized / 1000)


def _to_float(value: float | Decimal | int | str | None) -> float:
    """把 ORM 数值列（Decimal / int / float / str）转成 float；不可解析时返回 0.0。"""
    if value is None:
        return 0.0
    try:
        result = float(value)
    except (TypeError, ValueError):
        return 0.0
    return result if math.isfinite(result) else 0.0


def resolve_item_loss_rate(
    item_loss_rate: float | Decimal | None, order_spare_rate: float | Decimal | None
) -> float:
    """解析明细行的**有效损耗率**（千分之几）：逐行 loss_rate → 订单级 spare_rate → 0。

    与前端 ``resolveItemLossRate`` 逐字同源。回退链必须与「数量」列一致：
    一键生成的明细落库时 ``loss_rate`` 为 NULL，真正生效的是订单级 ``spare_rate``；
    若金额用另一套回退链，同一行的「数量」与「金额」就会按两个数量计价。

    注意：显式的 0 视为有效值（不再回退订单级），与前端一致。
    """
    for candidate in (item_loss_rate, order_spare_rate):
        if candidate is None:
            continue
        normalized = normalize_spare_rate(_to_float(candidate))
        if normalized is not None:
            return normalized
    return 0.0


def magnified_purchase_qty(
    base_qty: float | Decimal | None, loss_rate: float | Decimal | None
) -> Decimal:
    """计价数量 = 落库数量按损耗率加放（**不向上取整**，保留小数）。

    与前端 ``magnifyByLossRate`` 逐字同源（先算 ``qty + qty × rate/1000``，
    再四舍五入到 2 位小数）。损耗率为 0 时结果 == 落库数量，旧金额口径零回归。

    为什么金额按加放后的数量计价：采购单落库的 ``quantity`` 是**损耗加放前**的
    原始用量，真正下单/结算的数量是加放后的值（前端「数量」列展示的也是它）。
    若金额仍按加放前的数量算，采购单总金额会系统性低于实际采购额。

    Args:
        base_qty: 落库数量（采购明细的 ``quantity``）。
        loss_rate: 有效损耗率（千分之几），由 :func:`resolve_item_loss_rate` 给出。

    Returns:
        加放后的计价数量（Decimal，2 位小数）；输入非法时返回 0。
    """
    quantity = _to_float(base_qty)
    if quantity <= 0:
        return Decimal('0')
    rate = _to_float(loss_rate)
    magnified = (quantity + quantity * (rate / 1000)) * 100
    # JS Math.round 对正数等价于 floor(x + 0.5)；Python 内置 round 是银行家舍入，不能用
    rounded = math.floor(magnified + 0.5) / 100
    try:
        return Decimal(str(rounded))
    except InvalidOperation:  # pragma: no cover - str(float) 恒可被 Decimal 解析
        return Decimal('0')
