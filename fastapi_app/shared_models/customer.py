"""
客户模型 - 纯 SQLAlchemy 2.0 声明式

映射到 'customer' 表。
"""
from datetime import UTC, datetime

from sqlalchemy import Boolean, DateTime, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from fastapi_app.shared_models import Base


class Customer(Base):
    """客户模型"""
    __tablename__ = 'customer'

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    customer_code: Mapped[str | None] = mapped_column(String(50), unique=True, comment='客户编码')
    name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False, comment='客户名称')
    contact: Mapped[str | None] = mapped_column(String(50), comment='联系人')
    phone: Mapped[str | None] = mapped_column(String(20), comment='联系电话')
    address: Mapped[str | None] = mapped_column(String(200), comment='地址')
    note: Mapped[str | None] = mapped_column(Text, comment='备注')
    icon_url: Mapped[str | None] = mapped_column(String(200), comment='客户图标URL')
    status: Mapped[bool] = mapped_column(Boolean, default=True, comment='是否启用')
    create_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC), comment='创建时间')
    update_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC), onupdate=lambda: datetime.now(UTC), comment='更新时间')

    __table_args__ = (
        # pg_trgm GIN 索引：使 ILIKE '%keyword%' 和 % 运算符走索引
        Index('idx_customer_name_trgm', 'name', postgresql_using='gin',
              postgresql_ops={'name': 'gin_trgm_ops'}),
        Index('idx_customer_contact_trgm', 'contact', postgresql_using='gin',
              postgresql_ops={'contact': 'gin_trgm_ops'}),
        Index('idx_customer_phone_trgm', 'phone', postgresql_using='gin',
              postgresql_ops={'phone': 'gin_trgm_ops'}),
    )

    def __repr__(self):
        return f'<Customer {self.name}>'

    def to_dict(self):
        return {
            'id': self.id,
            'customer_code': self.customer_code,
            'name': self.name,
            'contact': self.contact,
            'phone': self.phone,
            'address': self.address,
            'note': self.note,
            'icon_url': self.icon_url,
            'status': self.status,
            'create_time': self.create_time.isoformat() if self.create_time else None,
            'update_time': self.update_time.isoformat() if self.update_time else None,
        }
