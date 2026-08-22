"""客户启用状态筛选(active/inactive)统一实现

消除 customer_service 与 purchase_customer_service 中重复且写法漂移的
status 分派(`is_(False)` vs `~`),统一行为与 SQL 语义。
"""
from fastapi_app.shared_models import Customer


def apply_customer_status_filter(query, count_query, status):
    """按启用状态过滤客户查询。

    Args:
        query: SQLAlchemy 查询对象。
        count_query: 配套的 COUNT 查询对象。
        status: 'active' 仅启用；'inactive' 仅停用；其他值（含 None/'all'）不过滤。

    Returns:
        (query, count_query) 元组。
    """
    if status == 'active':
        query = query.where(Customer.status)
        count_query = count_query.where(Customer.status)
    elif status == 'inactive':
        query = query.where(Customer.status.is_(False))
        count_query = count_query.where(Customer.status.is_(False))
    return query, count_query
