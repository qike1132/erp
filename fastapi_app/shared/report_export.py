"""报表导出的单一事实来源：类型集合、方法表与行数上限。

同步导出（report_service）、异步任务（report_tasks）、两个端点
（report.py / tasks.py）以及 report_data_service 的分支必须从这里取，
避免新增报表类型时四处同步、漏一处即能力分叉（审计 L-24）。
"""
REPORT_TYPES: tuple[str, ...] = ('order', 'stockin', 'stockout', 'deduction', 'return')

EXPORT_METHOD_NAMES: dict[str, str] = {
    'order': 'export_order_logs',
    'stockin': 'export_stockin_logs',
    'stockout': 'export_stockout_logs',
    'deduction': 'export_deduction_logs',
    'return': 'export_return_logs',
}

MAX_EXPORT_ROWS = 10000


def export_limit_message(total_count: int, order_count: int | None = None) -> str:
    """超限拒绝文案：订单报表同时给出订单数与明细行数（审计 L-22）。"""
    amount = f'{total_count} 行'
    if order_count is not None and int(order_count) != int(total_count):
        amount = f'订单 {order_count} 单 / 明细 {total_count} 行'
    return (
        f'导出数据量超过单次上限 {MAX_EXPORT_ROWS} 条（{amount}），'
        f'请缩小日期范围或增加筛选条件后重试'
    )
