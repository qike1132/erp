"""SKU 客户可见性口径 —— 单一事实来源

口径（2026-10-09 用户裁定）：
- 一个 SKU 可挂多个客户（product_customer 多对多）；
- **未挂任何客户的 SKU 对所有客户可见**（兼容存量数据，上线不打断下单）；
- 挂了客户之后，只对挂上的客户可见。

这个条件有两个消费点：产品列表的筛选（product_service.get_products_page）与
下单/出货/备货/备货计划共用的产品搜索（product_search_service）。两处若各写一份
SQL，迟早会漂移成两个口径（同 2026-10-08 结余口径两处必须同步的教训），
故抽到此模块。
"""
from sqlalchemy import exists, or_, select

from fastapi_app.shared_models import Product, ProductCustomer


def _any_link_exists():
    """EXISTS：该 SKU 挂了至少一个客户。"""
    return exists(select(ProductCustomer.id).where(ProductCustomer.product_id == Product.id))


def _link_to_customer_exists(customer_id: int):
    """EXISTS：该 SKU 挂到了指定客户。"""
    return exists(select(ProductCustomer.id).where(
        ProductCustomer.product_id == Product.id,
        ProductCustomer.customer_id == customer_id,
    ))


def visible_to_customer(customer_id: int):
    """SQL 条件：该 SKU 对指定客户可见（未挂客户，或挂了该客户）。"""
    return or_(~_any_link_exists(), _link_to_customer_exists(customer_id))


def unassigned_product():
    """SQL 条件：该 SKU 未挂任何客户（用于「未分配」筛选，补齐存量）。"""
    return ~_any_link_exists()
