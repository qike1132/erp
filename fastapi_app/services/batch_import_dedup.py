"""批量导入的应用层去重（ITER-2 决策 1）。

## 为什么必须放在应用层

现行导入是「逐行 SAVEPOINT + ``except SQLAlchemyError``」：某行触发唯一约束
冲突时，``db.begin_nested()`` 只回滚该行，循环继续 —— 也就是说
**DB 唯一约束实际承担了「跳过重复行」的职责**（见 ``batch_import_core.py:102-115``
与 ``Order.order_no`` / ``CaseStockIn.stockin_no`` / ``CaseStockOut.stockout_no``
上的 ``unique=True``）。

批量写入（``executemany``）**没有逐行 savepoint**：一条冲突会让整批失败。
所以「哪些行该被跳过」必须在上库之前、在内存里算清楚。

本模块提供一次性完成这件事的原语：

- 批内重复（同一个文件里出现两次）
- 与库中已有数据重复（自然键，如客户名 + 产品名）

两者共用同一遍遍历，**零 DB 往返**；不给 ``existing_keys`` 就只做批内去重。

## 边界与已知限制

- 没有唯一键的行（``key_fn`` 返回 ``None``）**一律保留**：无从判断何为重复，
  宁可让 DB 约束或后续校验去兜，也不要在这里静默丢数据。
- 本模块只解决「同一份数据里的重复」。并发场景下两个导入进程可能同时通过校验，
  因此批量写入仍应显式带 ``ON CONFLICT DO NOTHING``，并按 ``rowcount`` 核对
  （见 :func:`build_conflict_note`）—— 去重是**减少**冲突，不是**消除**冲突。
- 去重结果必须回显给用户。静默丢行是这类改造最容易引入的体验倒退。
"""
from __future__ import annotations

from collections.abc import Callable, Hashable, Iterable, Sequence
from dataclasses import dataclass, field

__all__ = [
    'DEFAULT_FIRST_DATA_ROW',
    'DedupResult',
    'DuplicateRow',
    'build_conflict_note',
    'composite_key',
    'dedupe_by_keys',
]

#: 表格数据的首个数据行号（第 1 行通常是表头）。与
#: ``batch_import_core._import_data_generic`` 的 ``enumerate(..., start=2)`` 对齐，
#: 使错误消息里的行号与用户在 Excel 里看到的行号一致。
DEFAULT_FIRST_DATA_ROW = 2


@dataclass(frozen=True)
class DuplicateRow:
    """一行被判定为重复的数据。

    Attributes:
        line_no: 原始行号（与 Excel 显示一致）。
        reason: 人类可读的原因，直接进导入报告。
        key: 触发重复的唯一键，便于排障。
    """

    line_no: int
    reason: str
    key: Hashable


@dataclass
class DedupResult[T]:
    """去重结果。

    ``kept`` 与 ``duplicates`` 的行号并集 = 输入的全部行号，
    便于断言「没有任何行被静默吞掉」。
    """

    kept: list[tuple[int, T]] = field(default_factory=list)
    duplicates: list[DuplicateRow] = field(default_factory=list)

    @property
    def kept_rows(self) -> list[T]:
        """仅取数据本身，供后续批量写入使用。"""
        return [row for _, row in self.kept]

    @property
    def removed_count(self) -> int:
        return len(self.duplicates)

    @property
    def total_count(self) -> int:
        return len(self.kept) + len(self.duplicates)

    def error_messages(self, *, limit: int | None = None) -> list[str]:
        """生成导入报告用的错误消息列表。

        Args:
            limit: 最多返回多少条；``None`` 表示不限。超出部分会附一条汇总，
                避免一个 5000 行的文件刷出上千条消息。
        """
        msgs = [f'行{d.line_no}: {d.reason}' for d in self.duplicates]
        if limit is not None and len(msgs) > limit:
            hidden = len(msgs) - limit
            return [*msgs[:limit], f'…另有 {hidden} 行重复未逐条列出']
        return msgs


def composite_key(*values: object, casefold: bool = True) -> tuple | None:
    """构造复合唯一键；任一值为空时返回 ``None``（表示「无法判定唯一性」）。

    默认对字符串做 ``strip`` + ``casefold``：本项目的客户名/产品名匹配
    一贯是大小写不敏感 + 去首尾空白的（见 ``_pre_load_product_map`` 的
    ``name.lower().strip()``），去重必须沿用同一套归一化，否则
    「Acme」与「acme 」会被当成两个客户，正是要防的那种重复。

    Args:
        *values: 参与唯一键的字段值。
        casefold: 是否对字符串做归一化。数值/日期等键传 ``False``。

    Returns:
        可用于 ``set`` 的元组；任一值为 ``None``/空串则为 ``None``。
    """
    parts: list[object] = []
    for value in values:
        if value is None:
            return None
        if isinstance(value, str):
            normalized = value.strip()
            if not normalized:
                return None
            parts.append(normalized.casefold() if casefold else normalized)
        else:
            parts.append(value)
    return tuple(parts)


def dedupe_by_keys[T](
    rows: Sequence[T],
    key_fn: Callable[[T], Hashable | None],
    *,
    # 类型为 Iterable 而非 Container：函数体要 `set(existing_keys)`，
    # 而 Container 只保证 `__contains__`、**不保证可迭代**。
    # 原注解 `Container[Hashable] | Iterable[Hashable]` 过宽 —— 传入一个
    # 非可迭代的 Container 会在运行时崩。此处收窄到实际所需能力。
    existing_keys: Iterable[Hashable] = (),
    start_index: int = DEFAULT_FIRST_DATA_ROW,
    label: str = '唯一键',
) -> DedupResult[T]:
    """在一遍遍历内去掉「批内重复」与「与既有数据重复」的行。

    **归一化是 ``key_fn`` 的职责**，不是本函数的：需要大小写不敏感 /
    去空白时用 :func:`composite_key` 构造键即可。本函数只做集合判重，
    不猜测哪些字段该归一化 —— 混在一起会让「订单编号要不要区分大小写」
    这类问题变成隐式行为。

    Args:
        rows: 待导入的数据行（原始顺序会被保留）。
        key_fn: 从一行提取唯一键；返回 ``None`` 表示该行没有唯一键（一律保留）。
            可直接用 :func:`composite_key`。
        existing_keys: 与「库中已有数据」冲突的键集合。传空表示只做批内去重。
        start_index: 首个数据行的行号，用于错误消息。
        label: 错误消息里对这把键的称呼，如 ``'订单编号'``、``'客户+产品'``。

    Returns:
        :class:`DedupResult`，``kept`` 保持输入相对顺序（先出现者胜）。

    Note:
        「先出现者胜」是有意选择：导入文件通常从上往下填写，用户修正过的
        行更可能靠后，但**保留先出现的**与现有逐行 SAVEPOINT 行为一致
        （先到的先入库，后到的撞唯一约束被跳过）。行为对齐比猜测意图重要。
    """
    seen_existing: set[Hashable] = set(existing_keys)
    seen_in_batch: set[Hashable] = set()
    result: DedupResult[T] = DedupResult()

    for offset, row in enumerate(rows):
        line_no = start_index + offset
        key = key_fn(row)

        if key is None:
            # 无从判定唯一性 —— 一律保留，绝不在这里静默丢数据。
            result.kept.append((line_no, row))
            continue

        if key in seen_existing:
            result.duplicates.append(
                DuplicateRow(line_no, f'{label}与已有数据重复，已跳过: {_fmt(key)}', key)
            )
            continue

        if key in seen_in_batch:
            result.duplicates.append(
                DuplicateRow(line_no, f'{label}在文件内重复，已跳过: {_fmt(key)}', key)
            )
            continue

        seen_in_batch.add(key)
        result.kept.append((line_no, row))

    return result


def build_conflict_note(expected: int, actual_rowcount: int | None) -> str | None:
    """把 ``executemany`` 的实际写入行数与期望值对比，返回给人看的差异说明。

    去重只能**减少**冲突，不能消除并发冲突。因此批量写入应带
    ``ON CONFLICT DO NOTHING``，再用本函数核对 ``rowcount``：
    差值不为 0 说明确有并发冲突，必须回显，不能当成「导入成功」。

    Returns:
        无差异（或 ``rowcount`` 为 ``None``，即驱动未提供）时返回 ``None``。
    """
    if actual_rowcount is None or actual_rowcount == expected:
        return None
    missing = expected - actual_rowcount
    if missing > 0:
        return (
            f'实际写入 {actual_rowcount} 行，比预期少 {missing} 行 —— '
            f'可能与并发导入的唯一键冲突（已按 ON CONFLICT DO NOTHING 跳过），请核对后重试'
        )
    return f'实际写入 {actual_rowcount} 行，比预期多 {-missing} 行 —— 请排查是否有触发器或重复执行'


def _fmt(key: Hashable) -> str:
    """把唯一键渲染成可读文本（复合键用 ``+`` 连接）。"""
    if isinstance(key, tuple):
        return ' + '.join(str(p) for p in key)
    return str(key)
