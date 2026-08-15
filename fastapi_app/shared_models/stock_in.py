"""
备货模型 - 纯 SQLAlchemy 2.0 声明式

映射到 'stock_in' 表。
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, desc
from sqlalchemy.orm import Mapped, mapped_column, relationship

from fastapi_app.shared_models import Base

if TYPE_CHECKING:
    from fastapi_app.shared_models.product import Product
    from fastapi_app.shared_models.stock_out import StockOut


class StockIn(Base):
    """备货模型"""
    __tablename__ = 'stock_in'

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    stockin_no: Mapped[str] = mapped_column(String(20), unique=True, nullable=False, comment='备货编号')
    stockin_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), index=True, comment='备货时间')
    customer: Mapped[str] = mapped_column(String(100), nullable=False, index=True, comment='客户名称')
    product_id: Mapped[int] = mapped_column(Integer, ForeignKey('product.id', ondelete='RESTRICT'), nullable=False, index=True, comment='产品ID')
    quantity: Mapped[int] = mapped_column(Integer, nullable=False, comment='备货数量')
    order_type: Mapped[str] = mapped_column(String(20), default='regular', nullable=False, comment='订单类型：regular=常规订单, custom=定制订单')
    country: Mapped[str | None] = mapped_column(String(100), comment='国家名称（仅定制订单使用）')
    note: Mapped[str | None] = mapped_column(Text, comment='备注')
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), comment='更新时间')

    product: Mapped["Product"] = relationship('Product', backref='stockins')
    stockin_stockouts: Mapped[list["StockOut"]] = relationship('StockOut', backref='stockin')

    __table_args__ = (
        Index('idx_stockin_customer_product', 'customer', 'product_id'),
        Index('idx_stockin_product_date', 'product_id', 'stockin_date'),
        Index('idx_stockin_customer_date', 'customer', 'stockin_date'),
        Index('idx_stockin_customer_product_date', 'customer', 'product_id', 'stockin_date'),
        Index('idx_perf_stockin_product_date', 'product_id', desc('stockin_date')),
    )

    def __repr__(self):
        return f'<StockIn {self.stockin_no}>'
