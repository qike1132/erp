"""皮套模型 - 纯 SQLAlchemy 2.0 声明式"""
from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from fastapi_app.shared_models import Base

if TYPE_CHECKING:
    from fastapi_app.shared_models.product import Product


class Case(Base):
    """皮套模型"""
    __tablename__ = 'case'
    __table_args__ = (
        Index('idx_case_product', 'product_id'),
        Index('idx_case_barcode', 'barcode'),
        Index('idx_case_name_trgm', 'name', postgresql_using='gin',
              postgresql_ops={'name': 'gin_trgm_ops'}),
        Index('idx_case_barcode_trgm', 'barcode', postgresql_using='gin',
              postgresql_ops={'barcode': 'gin_trgm_ops'}),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    product_id: Mapped[int | None] = mapped_column(Integer, ForeignKey('product.id', ondelete='SET NULL'), nullable=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    barcode: Mapped[str | None] = mapped_column(String(50))
    image: Mapped[str | None] = mapped_column(String(200))
    initial_stock: Mapped[int] = mapped_column(Integer, default=0)
    current_stock: Mapped[int] = mapped_column(Integer, default=0)
    version: Mapped[int] = mapped_column(Integer, default=0, server_default='0')
    create_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC), index=True)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC), onupdate=lambda: datetime.now(UTC), comment='更新时间')

    product: Mapped[Product | None] = relationship('Product', back_populates='cases')

    @property
    def sync_name(self) -> str:
        """同步产品名称"""
        if self.product_id and self.product:
            return self.product.name
        return self.name or ''

    @property
    def sync_barcode(self) -> str:
        """同步产品条码"""
        if self.product_id and self.product:
            return self.product.barcode or ''
        return self.barcode or ''
