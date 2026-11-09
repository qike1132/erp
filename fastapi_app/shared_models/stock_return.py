"""
退货模型 - 纯 SQLAlchemy 2.0 声明式

用于记录出货后的退货事件，保留完整审计轨迹。
"""
from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, Integer, String, Text, cast, func, text
from sqlalchemy.orm import Mapped, backref, mapped_column, relationship

from fastapi_app.shared.numbering_format import NUMBERING_FORMAT_REGEX
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
    return_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC), comment='退货时间')
    product_id: Mapped[int] = mapped_column(Integer, ForeignKey('product.id', ondelete='RESTRICT'), nullable=False, comment='产品ID')
    quantity: Mapped[int] = mapped_column(Integer, nullable=False, comment='退货数量')
    customer: Mapped[str | None] = mapped_column(String(100), nullable=True, comment='客户名称')
    stockout_id: Mapped[int | None] = mapped_column(Integer, ForeignKey('stock_out.id', ondelete='RESTRICT'), nullable=True, comment='关联出货ID（P1 起可空：按产品退货不关联出货，仅历史行有值）')
    order_id: Mapped[int | None] = mapped_column(Integer, ForeignKey('order.id', ondelete='SET NULL'), nullable=True, comment='关联订单ID')
    reason: Mapped[str | None] = mapped_column(String(200), comment='退货原因')
    note: Mapped[str | None] = mapped_column(Text, comment='备注')
    status: Mapped[str] = mapped_column(String(20), nullable=False, default='active', server_default='active', comment='状态：active正常/cancelled已取消')
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC), onupdate=lambda: datetime.now(UTC), comment='更新时间')

    product: Mapped[Product] = relationship('Product', backref='stock_returns')
    stockout: Mapped[StockOut] = relationship('StockOut', backref='returns')
    order: Mapped[Order | None] = relationship('Order', backref=backref('stock_returns', passive_deletes=True))

    __table_args__ = (
    # 2026-11-01 编号查询族表达式索引（P3，体检报告 §4）：
    # 取号 read_period_max / 巡检 numbering_audit_task / 对账 numbering_reconcile
    # 均按「日期段等值 + 序号段取 MAX」访问编号列。正则谓词与
    # NUMBERED_ENTITIES 白名单（numbering_reconcile.py）的格式约定强耦合——
    # 编号格式变更时必须同步重建本索引。
    Index(
        'idx_stockreturn_no_date_seq',
        func.split_part(return_no, '-', 2),
        cast(func.split_part(return_no, '-', 3), BigInteger),
        postgresql_where=text(f"return_no ~ '{NUMBERING_FORMAT_REGEX}'"),
    ),
        Index('idx_stockreturn_stockout', 'stockout_id'),
        Index('idx_stockreturn_order', 'order_id'),
        Index('idx_stockreturn_product_date', 'product_id', 'return_date'),
        Index('idx_stockreturn_customer_date', 'customer', 'return_date'),
    )

    def __repr__(self):
        return f'<StockReturn {self.return_no}>'
