"""
产品-客户归属关联模型（多对多）

映射到 'product_customer' 表。

业务背景（2026-10-09 用户裁定）：产品页给每个 SKU 挂「所属客户」，下单/出货/
备货/备货计划选产品时按客户过滤，避免甲客户选到乙客户的专属 SKU。
一个 SKU 可挂多个客户；**未挂任何客户的 SKU 对所有客户可见**（兼容存量数据，
上线不打断现有下单）。可见性过滤落在 product_search_service。

与 Order.customer / StockIn.customer / StockOut.customer（客户名字符串）不同，
本表用 customer_id 外键：客户改名不会断链。
"""
from datetime import UTC, datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from fastapi_app.shared_models import Base


class ProductCustomer(Base):
    """SKU 所属客户关联行"""
    __tablename__ = 'product_customer'

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    product_id: Mapped[int] = mapped_column(
        Integer, ForeignKey('product.id', ondelete='CASCADE'), nullable=False, comment='产品ID')
    customer_id: Mapped[int] = mapped_column(
        Integer, ForeignKey('customer.id', ondelete='CASCADE'), nullable=False, comment='客户ID')
    create_time: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), comment='创建时间')

    __table_args__ = (
        UniqueConstraint('product_id', 'customer_id', name='uq_product_customer'),
        # 可见性过滤按 customer_id 反查（「这个客户能看到哪些 SKU」）
        Index('idx_product_customer_customer', 'customer_id'),
        # 表注释必须与迁移 pg_standalone_086 逐字一致：只写一边会让 alembic check
        # 报 remove_table_comment（CI 的空库 upgrade head + check 会因此变红）。
        {'comment': '产品-客户归属（多对多；未挂客户的 SKU 对所有客户可见）'},
    )

    def __repr__(self):
        return f'<ProductCustomer product={self.product_id} customer={self.customer_id}>'
