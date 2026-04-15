"""
供应商模型 - 纯 SQLAlchemy 2.0 声明式

映射到与 Flask-SQLAlchemy Supplier 相同的 'supplier' 表。
"""
from sqlalchemy import String, Integer, Boolean, Text, DateTime, Index
from sqlalchemy.orm import Mapped, mapped_column, relationship
from datetime import datetime

from fastapi_app.shared_models import Base


class Supplier(Base):
    """供应商模型"""
    __tablename__ = 'supplier'

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False, unique=True, index=True, comment='供应商名称')
    contact_person: Mapped[str | None] = mapped_column(String(50), comment='联系人')
    phone: Mapped[str | None] = mapped_column(String(20), comment='联系电话')
    address: Mapped[str | None] = mapped_column(String(200), comment='地址')
    bank_name: Mapped[str | None] = mapped_column(String(100), comment='开户银行')
    bank_account: Mapped[str | None] = mapped_column(String(50), comment='银行账号')
    remark: Mapped[str | None] = mapped_column(Text, comment='备注')
    status: Mapped[bool | None] = mapped_column(Boolean, default=True, comment='状态')
    created_at: Mapped[datetime | None] = mapped_column(DateTime, default=datetime.now, comment='创建时间')
    updated_at: Mapped[datetime | None] = mapped_column(DateTime, default=datetime.now, onupdate=datetime.now, comment='更新时间')

    __table_args__ = (
        Index('idx_supplier_name', 'name'),
    )

    purchase_orders: Mapped[list["PurchaseOrder"]] = relationship(
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
            'bank_name': self.bank_name,
            'bank_account': self.bank_account,
            'remark': self.remark,
            'status': self.status,
            'created_at': self.created_at.strftime('%Y-%m-%d %H:%M:%S') if self.created_at else None,
            'updated_at': self.updated_at.strftime('%Y-%m-%d %H:%M:%S') if self.updated_at else None,
        }
