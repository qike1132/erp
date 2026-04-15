"""
Flask 服务层 - 共享工具函数
"""
from datetime import datetime
import logging

logger = logging.getLogger(__name__)


def validate_quantity(quantity_str, max_value=100000):
    """验证数量参数，返回 (quantity, error_msg)"""
    try:
        quantity = int(quantity_str)
    except (ValueError, TypeError):
        return None, '数量必须是有效的整数'
    if quantity <= 0:
        return None, '数量必须大于0'
    if quantity > max_value:
        return None, f'数量超出合理范围（最大{max_value}）'
    return quantity, None


def validate_customer(customer_str):
    """验证客户名称，返回 (customer, error_msg)"""
    if not customer_str:
        return None, '客户名称不能为空'
    if len(customer_str) > 100:
        return None, '客户名称过长（最大100字符）'
    return customer_str, None


def validate_note(note_str, max_length=500):
    """验证备注，返回 (note, error_msg)"""
    if note_str and len(note_str) > max_length:
        return None, f'备注过长（最大{max_length}字符）'
    return note_str or '', None


def parse_date(date_str, format='%Y-%m-%d'):
    """解析日期字符串，返回 (datetime_base, error_msg)"""
    try:
        return datetime.strptime(date_str, format), None
    except (ValueError, TypeError):
        return None, '日期格式不正确'


def build_datetime_with_time(date_base, existing_time=None):
    """构建带时间的日期对象"""
    now = datetime.now()
    if existing_time and (existing_time.hour != 0 or existing_time.minute != 0 or existing_time.second != 0):
        return datetime(date_base.year, date_base.month, date_base.day,
                        existing_time.hour, existing_time.minute, existing_time.second)
    return datetime(date_base.year, date_base.month, date_base.day,
                    now.hour, now.minute, now.second)
