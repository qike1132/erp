"""
出货模型 - 纯 SQLAlchemy 2.0 声明式

映射到 'stock_out' 表。
"""
from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, desc, text
from sqlalchemy.orm import Mapped, backref, mapped_column, relationship

from fastapi_app.shared_models import Base

if TYPE_CHECKING:
    from fastapi_app.shared_models.order import Order
    from fastapi_app.shared_models.product import Product


class StockOut(Base):
    """出货模型"""
    __tablename__ = 'stock_out'

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    stockout_no: Mapped[str] = mapped_column(String(20), unique=True, nullable=False, comment='出货编号')
    stockout_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC), index=True, comment='出货时间')
    product_id: Mapped[int] = mapped_column(Integer, ForeignKey('product.id', ondelete='RESTRICT'), nullable=False, comment='产品ID')
    quantity: Mapped[int] = mapped_column(Integer, nullable=False, comment='出货数量')
    returned_quantity: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default='0', comment='退货数量')
    customer: Mapped[str | None] = mapped_column(String(100), nullable=True, comment='客户名称')
    order_id: Mapped[int | None] = mapped_column(Integer, ForeignKey('order.id', ondelete='CASCADE'), nullable=True, comment='关联订单ID')
    stockin_id: Mapped[int | None] = mapped_column(Integer, ForeignKey('stock_in.id', ondelete='SET NULL'), comment='关联备货ID')
    batch_no: Mapped[str | None] = mapped_column(String(100), nullable=True, comment='批次号（指定则按该批次扣减成品库存）')
    note: Mapped[str | None] = mapped_column(Text, comment='备注')
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC), onupdate=lambda: datetime.now(UTC), comment='更新时间')

    product: Mapped[Product] = relationship('Product', backref='stockouts')
    order: Mapped[Order | None] = relationship('Order', backref=backref('order_stockouts', passive_deletes=True))

    __table_args__ = (
        Index('idx_stockout_stockin', 'stockin_id'),
        Index('idx_stockout_order', 'order_id'),
        Index('idx_stockout_product_date', 'product_id', 'stockout_date'),
        Index('idx_stockout_customer_date', 'customer', 'stockout_date'),
        Index('idx_stockout_product_customer_type', 'product_id', 'customer', 'stockin_id'),
        Index('idx_stockout_order_type', 'order_id', 'stockin_id'),
        Index('idx_perf_stockout_product_date', 'product_id', desc('stockout_date')),
        Index('idx_stockout_order_stockin_qty', 'order_id', 'stockin_id',
              postgresql_include=['quantity', 'returned_quantity']),
        Index('idx_stockout_deduction', 'product_id', desc('stockout_date'),
              postgresql_where=text("stockin_id IS NOT NULL")),
        # 独立出货（stockin_id IS NULL）的库存 CTE 聚合主路径：
        # WHERE stockin_id IS NULL AND product_id = ANY(..) AND customer = ..
        # （见 services/stock_inventory_service.py、inventory_service.py）。
        # ORM 原有的 idx_stockout_product_customer_type 是 (product_id, customer, stockin_id)，
        # 不是这条 partial 索引，故需单独声明。
        Index('idx_stockout_no_stockin', 'product_id', 'customer',
              postgresql_where=text("stockin_id IS NULL")),
        # 成品库存批次聚合的 partial 覆盖：出货聚合恒带 stockin_id IS NULL（排除备货抵扣行）。
        # 注：聚合按 coalesce(batch_no,'') 分组、且 group by 还带 product_id/customer，
        # 故 btree 不能用于该等值条件本身，本索引只加速 partial 谓词的扫描。
        Index('idx_stockout_batch_no', 'batch_no',
              postgresql_where=text("stockin_id IS NULL")),
    )

    def __repr__(self):
        return f'<StockOut {self.stockout_no}>'
