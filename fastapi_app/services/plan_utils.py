"""
计划管理共享工具函数

purchase_plan_service 和 production_plan_service 共用的日期处理、库存映射、出货状态函数。
"""
import calendar
from datetime import date, datetime


def last_day_of_month(year: int, month: int) -> date:
    return date(year, month, calendar.monthrange(year, month)[1])

def normalize_plan_date(date_str: str) -> date:
    try:
        return datetime.strptime(date_str, '%Y-%m-%d').date()
    except ValueError:
        parts = date_str.strip().split('-')
        if len(parts) != 3:
            raise ValueError(f'日期格式不正确: {date_str}，请使用 YYYY-MM-DD 格式') from None
        y, m = (int(parts[0]), int(parts[1]))
        d = min(int(parts[2]), calendar.monthrange(y, m)[1])
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
