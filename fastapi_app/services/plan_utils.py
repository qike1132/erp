"""
计划管理共享工具函数

purchase_plan_service 和 production_plan_service 共用的日期处理、库存映射、出货状态函数。
"""
__all__ = ['build_inventory_map', 'calc_shipment_status', 'last_day_of_month', 'normalize_plan_date']

import calendar
from datetime import date, datetime


def last_day_of_month(year: int, month: int) -> date:
    return date(year, month, calendar.monthrange(year, month)[1])

def normalize_plan_date(date_str: str) -> date:
    """归一化计划日期为 date

    兼容 Excel 日期单元格：openpyxl 读出的 datetime 经 str() 转换后会带时间部分
    （如 '2026-09-15 00:00:00'），需先截断时间再解析，否则 split('-') 会得到
    ['2026', '09', '15 00:00:00'] 使 int() 抛出原始异常而非可读的业务提示。
    """
    if isinstance(date_str, datetime):
        return date_str.date()
    if isinstance(date_str, date):
        return date_str
    raw = str(date_str).strip()
    # 仅取空格前的日期部分，丢弃时间部分（'2026-09-15 00:00:00' → '2026-09-15'）
    date_part = raw.split(' ', 1)[0]
    try:
        return datetime.strptime(date_part, '%Y-%m-%d').date()
    except ValueError:
        parts = date_part.split('-')
        if len(parts) != 3:
            raise ValueError(f'日期格式不正确: {date_str}，请使用 YYYY-MM-DD 格式') from None
        try:
            y, m = (int(parts[0]), int(parts[1]))
            d = min(int(parts[2]), calendar.monthrange(y, m)[1])
        except ValueError:
            raise ValueError(f'日期格式不正确: {date_str}，请使用 YYYY-MM-DD 格式') from None
        return date(y, m, d)

def build_inventory_map(inventory_data: list) -> dict:
    mapping = {}
    for item in inventory_data:
        key = (item['customer'], item['product_name'])
        stock = item.get('total_stock', 0) or 0
        if isinstance(stock, str):
            try:
                stock = int(stock)
            except (ValueError, TypeError):
                stock = 0
        mapping[key] = mapping.get(key, 0) + stock
    return mapping

def calc_shipment_status(plan_qty: int, shipped_qty: int) -> str:
    if shipped_qty >= plan_qty:
        return 'completed'
    elif shipped_qty > 0:
        return 'partial'
    return 'pending'
