"""
供应商模型 - 纯 SQLAlchemy 2.0 声明式

映射到 'supplier' 表。
"""
from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from fastapi_app.shared_models import Base

if TYPE_CHECKING:
    from fastapi_app.shared_models.purchase_order import PurchaseOrder


class Supplier(Base):
    """供应商模型"""
    __tablename__ = 'supplier'

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False, unique=True, comment='供应商名称')
    contact_person: Mapped[str | None] = mapped_column(String(50), comment='联系人')
    phone: Mapped[str | None] = mapped_column(String(20), comment='联系电话')
    address: Mapped[str | None] = mapped_column(String(200), comment='地址')
    bank_name: Mapped[str | None] = mapped_column(String(100), comment='开户银行')
    bank_account: Mapped[str | None] = mapped_column(String(50), comment='银行账号')
    remark: Mapped[str | None] = mapped_column(Text, comment='备注')
    status: Mapped[bool | None] = mapped_column(Boolean, default=True, comment='状态')
    created_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC), comment='创建时间')
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC), onupdate=lambda: datetime.now(UTC), comment='更新时间')

    purchase_orders: Mapped[list[PurchaseOrder]] = relationship(
        "PurchaseOrder", back_populates="supplier_rel", lazy="select"
    )

    def __repr__(self):
        return f'<Supplier {self.name}>'

    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'contact_person': self.contact_person,
            'phone': self.phone,
            'address': self.address,
            'remark': self.remark,
            'status': self.status,
            'created_at': self.created_at.strftime('%Y-%m-%d %H:%M:%S') if self.created_at else None,
            'updated_at': self.updated_at.strftime('%Y-%m-%d %H:%M:%S') if self.updated_at else None,
        }
