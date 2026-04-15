"""SKU批次管理模型"""
from sqlalchemy import String, Integer, DateTime, Index, Numeric
from sqlalchemy.orm import Mapped, mapped_column
from datetime import datetime

from fastapi_app.shared_models import Base


class SkuBatch(Base):
    """SKU批次表"""
    __tablename__ = 'sku_batch'

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    sku_code: Mapped[str] = mapped_column(String(50), nullable=False, index=True, comment='SKU编号')
    batch_no: Mapped[str] = mapped_column(String(50), nullable=False, index=True, comment='批次号')
    status: Mapped[str] = mapped_column(String(20), default='active', comment='批次状态: active-在用, frozen-冻结, expired-过期')
    quantity: Mapped[float | None] = mapped_column(Numeric(12, 2), default=0, comment='批次数量')
    remark: Mapped[str | None] = mapped_column(String(200), comment='备注')
    create_time: Mapped[datetime | None] = mapped_column(DateTime, default=datetime.now, index=True, comment='批次创建时间')
    update_time: Mapped[datetime | None] = mapped_column(DateTime, default=datetime.now, onupdate=datetime.now, comment='更新时间')

    __table_args__ = (
        Index('idx_sku_batch_code_no', 'sku_code', 'batch_no'),
    )

    def to_dict(self):
        return {
            'id': self.id,
            'sku_code': self.sku_code,
            'batch_no': self.batch_no,
            'status': self.status,
            'quantity': float(self.quantity or 0),
            'remark': self.remark or '',
            'create_time': self.create_time.strftime('%Y-%m-%d %H:%M:%S') if self.create_time else '',
            'update_time': self.update_time.strftime('%Y-%m-%d %H:%M:%S') if self.update_time else '',
        }
