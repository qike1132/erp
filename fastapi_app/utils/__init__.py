"""FastAPI 应用通用工具函数（去重提取）"""
import calendar
import logging
import re
from datetime import date, datetime, timedelta

from fastapi_app.shared_models import InventoryLog

logger = logging.getLogger(__name__)


def calc_total_pages(total: int, per_page: int) -> int:
    """根据总数和每页数量计算总页数。

    Args:
        total: 记录总数。
        per_page: 每页数量。

    Returns:
        总页数；per_page <= 0 时返回 0。
    """
    if per_page <= 0:
        return 0
    return (total + per_page - 1) // per_page


def inventory_balance_bounds(current_stock_after: int, change_quantity: int) -> tuple[int, int]:
    """由「写入口返回的变动后库存」与本次变更量反推 (变动前, 变动后)。

    唯一合法来源是 **已持行锁的写入口**（apply_stock_delta_locked /
    update_stock_with_optimistic_lock）的返回值：该值在锁内确定，天然与本次
    变更同序。禁止改用 `SELECT current_stock` 反查 —— 并发下会读到交叉快照，
    写出自我矛盾的流水；这正是 frappe/erpnext#51562（qty_after_transaction
    并发算错，需 Repost Item Valuation 重算）的成因。

    Args:
        current_stock_after: 写入口返回的变动后库存。
        change_quantity: 本次变更量（正增负减），须与写入口 delta 逐字一致。

    Returns:
        (quantity_before, quantity_after)
    """
    return current_stock_after - change_quantity, current_stock_after


def log_inventory_change(db, *, product_id: int, change_type: str,
                         change_quantity: int, related_id: str = '',
                         note: str = '', customer: str | None = None,
                         idem_key: str | None = None,
                         operator_id: int | None = None,
                         quantity_before: int | None = None,
                         quantity_after: int | None = None,
                         product_name: str | None = None,
                         product_barcode: str | None = None) -> None:
    """创建库存流水日志并加入数据库会话。

    统一 InventoryLog 创建逻辑，消除各服务中 db.add(InventoryLog(...)) 重复。
    db 参数接受同步 Session 或异步 AsyncSession（两者均有 .add() 方法）。
    调用方负责在合适时机调用 flush/commit。

    Args:
        db: 数据库会话（同步或异步）。
        product_id: 产品 ID。
        change_type: 变更类型（如 '入库'、'出库'、'退货'）。
        change_quantity: 变更数量（正数表示增加，负数表示减少）。
        related_id: 关联记录 ID 字符串。
        note: 备注信息。
        customer: 客户名称（可选，退货等场景使用）。
        idem_key: 幂等键（可选）。命中 uq_inventory_log_idem 部分唯一索引
                  （仅对非 NULL 生效），用于请求级防重。
        operator_id: 操作人用户 ID（可选）。ARQ 任务 / 脚本等无用户上下文时留 None。
        quantity_before/quantity_after: 记账时序的前后库存，须由
                  ``inventory_balance_bounds`` 从锁内写入口返回值推导，
                  不要从数据库另行反查（见该函数 docstring）。
        product_name: 产品名称快照（可选）。产品删除后外键置空，历史靠快照仍可读；
                  调用方持有 Product 对象时带上（写路径只带名称）。
        product_barcode: 产品条码快照（可选）。**一般无需在写路径传**——产品存在时
                  可直接 JOIN 取到，只在产品删除时才有价值，由
                  ``product_service.delete_product`` 删除前统一 coalesce 补齐。
    """
    db.add(InventoryLog(
        product_id=product_id,
        change_type=change_type,
        change_quantity=change_quantity,
        related_id=related_id,
        note=note,
        customer=customer,
        idem_key=idem_key,
        operator_id=operator_id,
        quantity_before=quantity_before,
        quantity_after=quantity_after,
        product_name=product_name,
        product_barcode=product_barcode,
    ))


def parse_date_strict(date_str: str, field_name: str = '日期') -> datetime:
    """严格解析 YYYY-MM-DD 格式日期字符串。

    Args:
        date_str: 日期字符串，必须符合 YYYY-MM-DD 格式。
        field_name: 字段名（用于错误消息展示），默认为"日期"。

    Returns:
        解析后的 datetime 对象。

    Raises:
        ValueError: 当 date_str 格式不符合 YYYY-MM-DD 时抛出。
    """
    try:
        return datetime.strptime(date_str, '%Y-%m-%d')
    except (ValueError, TypeError) as e:
        raise ValueError(f'{field_name}格式错误，请使用YYYY-MM-DD格式') from e


def parse_date_with_fallback(date_str: str) -> date:
    """解析日期字符串，支持日溢出回退（如 2-30 → 2-28/29）。

    先尝试标准 YYYY-MM-DD 解析；失败时尝试按年/月/日拆分，
    将日截断为该月最后一天（处理 Excel 输入的 2-30 等非法日期）。

    Args:
        date_str: 日期字符串。

    Returns:
        解析后的 date 对象。

    Raises:
        ValueError: 当 date_str 无法解析时抛出。
    """
    try:
        return datetime.strptime(date_str, '%Y-%m-%d').date()
    except ValueError:
        parts = date_str.strip().split('-')
        if len(parts) != 3:
            raise ValueError(f'日期格式不正确: {date_str}，请使用 YYYY-MM-DD 格式') from None
        y, m = (int(parts[0]), int(parts[1]))
        d = min(int(parts[2]), calendar.monthrange(y, m)[1])
        return date(y, m, d)



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
        pass  # defensive: 异常静默处理,不影响主流程
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
