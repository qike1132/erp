"""
订单明细模型 - 纯 SQLAlchemy 2.0 声明式

承载 SKU 级字段，使一个主订单（Order）可包含多个 SKU。
迁移期间 Order 表的 SKU 字段保留兼容，删列在后续 Task 5 完成。
"""
from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from fastapi_app.shared_models import Base

if TYPE_CHECKING:
    from fastapi_app.shared_models.order import Order
    from fastapi_app.shared_models.product import Product


class OrderItem(Base):
    """订单明细模型（SKU 粒度）"""
    __tablename__ = 'order_item'

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    order_id: Mapped[int] = mapped_column(
        Integer, ForeignKey('order.id', ondelete='CASCADE'), nullable=False, comment='主订单ID'
    )
    product_id: Mapped[int] = mapped_column(
        Integer, ForeignKey('product.id'), nullable=False, comment='产品ID'
    )
    product_name: Mapped[str | None] = mapped_column(String(200), nullable=True, comment='冗余产品名称，便于历史查询')
    product_barcode: Mapped[str | None] = mapped_column(String(100), nullable=True, comment='冗余产品条码')
    quantity: Mapped[int] = mapped_column(Integer, nullable=False, comment='订单数量')
    deduct_stock: Mapped[bool] = mapped_column(Boolean, default=False, comment='是否扣减库存')
    deduct_quantity: Mapped[int] = mapped_column(Integer, default=0, comment='扣减库存数量')
    note: Mapped[str | None] = mapped_column(Text, nullable=True, comment='备注')
    created_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), comment='创建时间'
    )
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
        comment='更新时间',
    )

    order: Mapped[Order] = relationship('Order', back_populates='items')
    product: Mapped[Product] = relationship('Product')

    __table_args__ = (
        Index('ix_order_item_order_id', 'order_id'),
        Index('ix_order_item_product_id', 'product_id'),
        Index('ix_order_item_order_product', 'order_id', 'product_id'),
    )

    def __repr__(self):
        return f'<OrderItem order_id={self.order_id} product_id={self.product_id} qty={self.quantity}>'
