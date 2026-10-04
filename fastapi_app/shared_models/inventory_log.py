"""
库存日志模型 - 纯 SQLAlchemy 2.0 声明式

映射到 'inventory_log' 表。
"""
from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, desc, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from fastapi_app.shared_models import Base

if TYPE_CHECKING:
    from fastapi_app.shared_models.product import Product


class InventoryLog(Base):
    """库存日志模型"""
    __tablename__ = 'inventory_log'

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    product_id: Mapped[int] = mapped_column(Integer, ForeignKey('product.id', ondelete='CASCADE'), nullable=False, index=True, comment='产品ID')
    change_type: Mapped[str] = mapped_column(String(20), nullable=False, index=True, comment='变化类型')
    change_quantity: Mapped[int] = mapped_column(Integer, nullable=False, comment='变化数量')
    change_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC), index=True, comment='变化时间')
    related_id: Mapped[str | None] = mapped_column(String(50), comment='关联单据编号')
    idem_key: Mapped[str | None] = mapped_column(Text, comment='导入幂等键（部分唯一索引 uq_inventory_log_idem；手工路径留空）')
    note: Mapped[str | None] = mapped_column(Text, comment='备注')
    customer: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True, comment='客户名称')
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC), onupdate=lambda: datetime.now(UTC), comment='更新时间')

    product: Mapped[Product] = relationship('Product', backref='inventory_logs')

    __table_args__ = (
        Index('idx_inventory_log_product_date', 'product_id', desc('change_date')),
        Index(
            'uq_inventory_log_idem',
            'idem_key',
            unique=True,
            postgresql_where=text('idem_key IS NOT NULL'),
        ),
    )

    def __repr__(self):
        return f'<InventoryLog {self.id}>'
