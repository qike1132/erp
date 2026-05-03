"""FastAPI 应用通用工具函数（去重提取）"""
import logging
import re
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)


def parse_date_value(date_value) -> datetime | None:
    """解析日期值（支持多种格式），解析失败返回None"""
    if date_value is None:
        return None
    if isinstance(date_value, datetime):
        return date_value
    if isinstance(date_value, (int, float)):
        try:
            base_date = datetime(1899, 12, 30)
            return base_date + timedelta(days=date_value)
        except (ValueError, OverflowError):
            return None
    try:
        date_str = str(date_value).strip()
        for fmt in ["%Y-%m-%d", "%Y/%m/%d", "%Y-%m-%d %H:%M:%S", "%Y/%m/%d %H:%M:%S"]:
            try:
                return datetime.strptime(date_str, fmt)
            except ValueError:
                continue
    except (ValueError, TypeError):
        pass
    return None


def validate_customer_name(customer_name: str) -> tuple[bool, str]:
    """验证客户名称"""
    if not customer_name or not customer_name.strip():
        return False, "客户名称不能为空"

    customer_name = customer_name.strip()
    if len(customer_name) < 2:
        return False, "客户名称至少需要 2 个字符"
    if len(customer_name) > 100:
        return False, "客户名称不能超过 100 个字符"

    pattern = r'^[\u4e00-\u9fa5a-zA-Z0-9\s\-\_\.\,\(\)\（\）]+$'
    if not re.match(pattern, customer_name):
        return False, "客户名称包含非法字符"
    return True, ""
