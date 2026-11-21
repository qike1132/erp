"""导出行数上界保护（批次 2，2026-08-22）

同步生成 Excel 的导出端点在超量数据下会占住 worker 并放大内存，
统一在此做"先计数、超限即拒"的门禁；上限值经模块常量集中管理。
计数查询由调用方以 SQLAlchemy ORM 构造传入，值均走绑定参数。
"""

EXPORT_MAX_ROWS = 20000


class ExportLimitError(ValueError):
    """导出行数超上界（L-35/N-54，2026-11-21 审计）。

    继承 ValueError 保持向后兼容：既有 `except ValueError` → 413/400 的映射
    行为不变。类型化的目的是让端点**不必**再靠 `'日期' in str(e)` 字符串判别
    来区分「行数上界」与「日期非法」两种 ValueError。
    """


async def ensure_within_export_limit(db, count_query, *, limit: int = EXPORT_MAX_ROWS) -> int:
    """读取计数查询的标量结果，超过 limit 行时抛 ExportLimitError（端点转 413 引导缩小范围）。

    Returns:
        实际行数（未超限时调用方可继续导出）。
    """
    total = await db.scalar(count_query)
    total = int(total or 0)
    if total > limit:
        raise ExportLimitError(
            f'导出数据量过大（{total} 行，上限 {limit}），请缩小筛选范围后分批导出'
        )
    return total
