"""
暂存备货模型 - 纯 SQLAlchemy 2.0 声明式

映射到与 Flask-SQLAlchemy StagingStockIn 相同的 'staging_stock_in' 表。
"""
from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from fastapi_app.shared_models import Base

if TYPE_CHECKING:
    from fastapi_app.shared_models.product import Product


class StagingStockIn(Base):
    """暂存备货模型"""
    __tablename__ = 'staging_stock_in'

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    session_id: Mapped[str] = mapped_column(String(64), index=True, comment='会话ID，用于标识同一批导入')
    customer: Mapped[str] = mapped_column(String(100), nullable=False, index=True, comment='客户名称')
    stockin_date: Mapped[datetime | None] = mapped_column(DateTime, default=datetime.now, comment='备货时间')
    product_name: Mapped[str] = mapped_column(String(200), nullable=False, comment='产品名称（冗余存储）')
    product_barcode: Mapped[str | None] = mapped_column(String(50), comment='产品69码（冗余存储）')
    product_id: Mapped[int | None] = mapped_column(Integer, ForeignKey('product.id'), comment='产品ID（确认后填充）')
    quantity: Mapped[int] = mapped_column(Integer, nullable=False, comment='备货数量')
    note: Mapped[str | None] = mapped_column(Text, comment='备注')
    status: Mapped[str | None] = mapped_column(String(20), default='pending', comment='状态：pending=待审核, approved=已确认, rejected=已拒绝')
    is_validated: Mapped[bool | None] = mapped_column(Boolean, default=False, comment='是否已验证产品存在')
    validation_error: Mapped[str | None] = mapped_column(String(500), comment='验证错误信息')
    created_at: Mapped[datetime | None] = mapped_column(DateTime, default=datetime.now, comment='创建时间')
    updated_at: Mapped[datetime | None] = mapped_column(DateTime, default=datetime.now, onupdate=datetime.now, comment='更新时间')

    product: Mapped["Product | None"] = relationship('Product', backref='staging_stockins')

    __table_args__ = (
        Index('idx_staging_stockin_session', 'session_id'),
        Index('idx_staging_stockin_status', 'status'),
        Index('idx_staging_stockin_created', 'created_at'),
        Index('idx_staging_stockin_product', 'product_id'),
    )

    def __repr__(self):
        return f'<StagingStockIn {self.id} - {self.customer} - {self.product_name}>'

    def to_dict(self):
        """转换为字典"""
        return {
            'id': self.id,
            'customer': self.customer,
            'stockin_date': self.stockin_date.strftime('%Y-%m-%d') if self.stockin_date else '',
            'product_name': self.product_name,
            'product_barcode': self.product_barcode or '',
            'product_id': self.product_id,
            'quantity': self.quantity,
            'note': self.note or '',
            'status': self.status,
            'is_validated': self.is_validated,
            'validation_error': self.validation_error or '',
            'created_at': self.created_at.strftime('%Y-%m-%d %H:%M:%S') if self.created_at else ''
        }
