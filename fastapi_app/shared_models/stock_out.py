"""
出货模型 - 纯 SQLAlchemy 2.0 声明式

映射到与 Flask-SQLAlchemy StockOut 相同的 'stock_out' 表。
"""
from sqlalchemy import String, Integer, Text, DateTime, ForeignKey, Index
from sqlalchemy.orm import Mapped, mapped_column, relationship
from datetime import datetime

from fastapi_app.shared_models import Base


class StockOut(Base):
    """出货模型"""
    __tablename__ = 'stock_out'

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    stockout_no: Mapped[str] = mapped_column(String(20), unique=True, nullable=False, comment='出货编号')
    stockout_date: Mapped[datetime | None] = mapped_column(DateTime, default=datetime.now, index=True, comment='出货时间')
    product_id: Mapped[int] = mapped_column(Integer, ForeignKey('product.id'), nullable=False, comment='产品ID')
    quantity: Mapped[int] = mapped_column(Integer, nullable=False, comment='出货数量')
    customer: Mapped[str | None] = mapped_column(String(100), nullable=True, comment='客户名称')
    order_id: Mapped[int | None] = mapped_column(Integer, ForeignKey('order.id', ondelete='CASCADE'), nullable=True, comment='关联订单ID')
    stockin_id: Mapped[int | None] = mapped_column(Integer, ForeignKey('stock_in.id', ondelete='SET NULL'), comment='关联备货ID')
    note: Mapped[str | None] = mapped_column(Text, comment='备注')

    product: Mapped["Product"] = relationship('Product', backref='stockouts')
    order: Mapped["Order | None"] = relationship('Order', backref='order_stockouts')

    __table_args__ = (
        Index('idx_stockout_stockin', 'stockin_id'),
        Index('idx_stockout_order', 'order_id'),
        Index('idx_stockout_product_date', 'product_id', 'stockout_date'),
        Index('idx_stockout_customer_date', 'customer', 'stockout_date'),
        Index('idx_stockout_product_customer_type', 'product_id', 'customer', 'stockin_id'),
        Index('idx_stockout_order_type', 'order_id', 'stockin_id'),
    )

    def __repr__(self):
        return f'<StockOut {self.stockout_no}>'
