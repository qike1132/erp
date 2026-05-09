"""
订单状态日志模型 - 纯 SQLAlchemy 2.0 声明式

映射到与 Flask-SQLAlchemy OrderStatusLog 相同的表。
"""
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from fastapi_app.shared_models import Base


class OrderStatusLog(Base):
    """订单状态变更日志表"""
    __tablename__ = 'order_status_log'

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    target_type: Mapped[str] = mapped_column(String(50), nullable=False, index=True, comment='目标类型: unprocessed_order/purchase_order')
    target_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True, comment='目标ID')
    order_no: Mapped[str | None] = mapped_column(String(20), comment='订单编号')
    from_status: Mapped[str | None] = mapped_column(String(50), comment='变更前状态')
    to_status: Mapped[str] = mapped_column(String(50), nullable=False, comment='变更后状态')
    action: Mapped[str] = mapped_column(String(50), nullable=False, comment='操作类型: start_process/complete/ignore/reopen')
    action_label: Mapped[str | None] = mapped_column(String(100), comment='操作标签(中文)')
    operator_id: Mapped[int | None] = mapped_column(Integer, ForeignKey('user.id'), comment='操作人ID')
    operator_name: Mapped[str | None] = mapped_column(String(100), comment='操作人姓名')
    action_time: Mapped[datetime | None] = mapped_column(DateTime, default=datetime.now, index=True, comment='操作时间')
    action_result: Mapped[str | None] = mapped_column(String(20), default='success', comment='操作结果: success/failed')
    remark: Mapped[str | None] = mapped_column(Text, comment='备注说明')
    related_data: Mapped[str | None] = mapped_column(Text, comment='关联数据JSON')
    updated_at: Mapped[datetime | None] = mapped_column(DateTime, default=datetime.now, onupdate=datetime.now, comment='更新时间')

    __table_args__ = (
        Index('idx_status_target', 'target_type', 'target_id'),
        Index('idx_status_time', 'action_time'),
        Index('idx_status_order', 'order_no'),
    )

    def to_dict(self):
        return {
            'id': self.id,
            'target_type': self.target_type,
            'target_id': self.target_id,
            'order_no': self.order_no,
            'from_status': self.from_status,
            'to_status': self.to_status,
            'action': self.action,
            'action_label': self.action_label,
            'operator_id': self.operator_id,
            'operator_name': self.operator_name,
            'action_time': self.action_time.isoformat() if self.action_time else None,
            'action_result': self.action_result,
            'remark': self.remark,
            'related_data': self.related_data,
        }
