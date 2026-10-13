"""
暂存订单模型 - 纯 SQLAlchemy 2.0 声明式

映射到 'staging_order' 表。
"""
from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from fastapi_app.core.business_time import fmt_business
from fastapi_app.shared_models import Base

if TYPE_CHECKING:
    from fastapi_app.shared_models.product import Product


class StagingOrder(Base):
    """暂存订单模型"""
    __tablename__ = 'staging_order'

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    session_id: Mapped[str] = mapped_column(String(64), index=True, comment='会话ID，用于标识同一批导入')
    customer: Mapped[str] = mapped_column(String(100), nullable=False, index=True, comment='客户名称')
    order_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC), comment='下单时间')
    product_name: Mapped[str] = mapped_column(String(200), nullable=False, comment='产品名称（冗余存储）')
    product_barcode: Mapped[str | None] = mapped_column(String(50), comment='产品69码（冗余存储）')
    product_id: Mapped[int | None] = mapped_column(Integer, ForeignKey('product.id'), comment='产品ID（确认后填充）')
    quantity: Mapped[int] = mapped_column(Integer, nullable=False, comment='订单数量')
    deduct_stock: Mapped[bool | None] = mapped_column(Boolean, default=False, comment='是否抵扣备货')
    deduct_quantity: Mapped[int | None] = mapped_column(Integer, default=0, comment='抵扣备货数量')
    note: Mapped[str | None] = mapped_column(Text, comment='备注')
    status: Mapped[str | None] = mapped_column(String(20), default='pending', comment='状态：pending=待审核, approved=已确认, rejected=已拒绝')
    is_validated: Mapped[bool | None] = mapped_column(Boolean, default=False, comment='是否已验证产品存在')
    validation_error: Mapped[str | None] = mapped_column(String(500), comment='验证错误信息')
    created_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC), comment='创建时间')
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC), onupdate=lambda: datetime.now(UTC), comment='更新时间')
    import_batch_id: Mapped[str | None] = mapped_column(String(64), index=True, comment='导入批次ID')

    product: Mapped[Product | None] = relationship('Product', backref='staging_orders')

    __table_args__ = (
        Index('idx_staging_session', 'session_id'),
        Index('idx_staging_status', 'status'),
        Index('idx_staging_created', 'created_at'),
        Index('idx_staging_order_product', 'product_id'),
    )

    def __repr__(self):
        return f'<StagingOrder {self.id} - {self.customer} - {self.product_name}>'

    def to_dict(self):
        """转换为字典"""
        return {
            'id': self.id,
            'customer': self.customer,
            'order_date': fmt_business(self.order_date),
            'product_name': self.product_name,
            'product_barcode': self.product_barcode or '',
            'product_id': self.product_id,
            'quantity': self.quantity,
            'deduct_stock': self.deduct_stock,
            'deduct_quantity': self.deduct_quantity,
            'note': self.note or '',
            'status': self.status,
            'is_validated': self.is_validated,
            'validation_error': self.validation_error or '',
            'created_at': fmt_business(self.created_at, '%Y-%m-%d %H:%M:%S'),
            'import_batch_id': self.import_batch_id or ''
        }
