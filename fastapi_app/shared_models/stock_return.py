"""
退货模型 - 纯 SQLAlchemy 2.0 声明式

用于记录出货后的退货事件，保留完整审计轨迹。
"""
from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, backref, mapped_column, relationship

from fastapi_app.shared_models import Base

if TYPE_CHECKING:
    from fastapi_app.shared_models.order import Order
    from fastapi_app.shared_models.product import Product
    from fastapi_app.shared_models.stock_out import StockOut


class StockReturn(Base):
    """退货模型"""
    __tablename__ = 'stock_return'

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    return_no: Mapped[str] = mapped_column(String(20), unique=True, nullable=False, comment='退货编号')
    return_date: Mapped[datetime | None] = mapped_column(DateTime, default=datetime.now, comment='退货时间')
    product_id: Mapped[int] = mapped_column(Integer, ForeignKey('product.id'), nullable=False, comment='产品ID')
    quantity: Mapped[int] = mapped_column(Integer, nullable=False, comment='退货数量')
    customer: Mapped[str | None] = mapped_column(String(100), nullable=True, comment='客户名称')
    stockout_id: Mapped[int] = mapped_column(Integer, ForeignKey('stock_out.id'), nullable=False, comment='关联出货ID')
    order_id: Mapped[int | None] = mapped_column(Integer, ForeignKey('order.id', ondelete='SET NULL'), nullable=True, comment='关联订单ID')
    reason: Mapped[str | None] = mapped_column(String(200), comment='退货原因')
    note: Mapped[str | None] = mapped_column(Text, comment='备注')
    updated_at: Mapped[datetime | None] = mapped_column(DateTime, default=datetime.now, onupdate=datetime.now, comment='更新时间')

    product: Mapped["Product"] = relationship('Product', backref='stock_returns')
    stockout: Mapped["StockOut"] = relationship('StockOut', backref='returns')
    order: Mapped["Order | None"] = relationship('Order', backref=backref('stock_returns', passive_deletes=True))

    __table_args__ = (
        Index('idx_stockreturn_stockout', 'stockout_id'),
        Index('idx_stockreturn_order', 'order_id'),
        Index('idx_stockreturn_product_date', 'product_id', 'return_date'),
        Index('idx_stockreturn_customer_date', 'customer', 'return_date'),
    )

    def __repr__(self):
        return f'<StockReturn {self.return_no}>'
