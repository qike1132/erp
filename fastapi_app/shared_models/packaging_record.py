"""
包装部生产记录模型 - 纯 SQLAlchemy 2.0 声明式
"""
from datetime import datetime, timezone

from sqlalchemy import Date, DateTime, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from fastapi_app.shared_models import Base


class PackagingRecord(Base):
    """包装部生产记录"""
    __tablename__ = 'packaging_record'
    __table_args__ = (
        Index('idx_packaging_date', 'pack_date'),
        Index('idx_packaging_customer_date', 'customer', 'pack_date'),
        Index('idx_packaging_barcode', 'barcode'),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    customer: Mapped[str] = mapped_column(String(100), nullable=False, comment='客户')
    product_name: Mapped[str] = mapped_column(String(100), nullable=False, comment='产品名称')
    barcode: Mapped[str] = mapped_column(String(50), nullable=False, comment='69码')
    quantity: Mapped[int] = mapped_column(Integer, nullable=False, comment='数量')
    pack_date: Mapped[datetime] = mapped_column(Date, nullable=False, comment='包装日期')
    remark: Mapped[str | None] = mapped_column(Text, nullable=True, comment='备注')
    upload_batch: Mapped[str | None] = mapped_column(String(64), nullable=True, comment='上传批次ID')
    create_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), comment='创建时间')
    created_by: Mapped[str | None] = mapped_column(String(50), nullable=True, comment='创建人')
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), comment='更新时间')

    def to_dict(self):
        return {
            'id': self.id,
            'customer': self.customer,
            'product_name': self.product_name,
            'barcode': self.barcode,
            'quantity': self.quantity,
            'pack_date': self.pack_date.isoformat() if self.pack_date else '',
            'remark': self.remark or '',
            'upload_batch': self.upload_batch or '',
            'create_time': self.create_time.strftime('%Y-%m-%d %H:%M:%S') if self.create_time else '',
            'created_by': self.created_by or '',
        }
