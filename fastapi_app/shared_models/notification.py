"""系统内消息通知模型

承载订单创建/修改等关键业务事件向指定工厂用户的系统内消息派发。
MVP 阶段仅做系统内消息，后续可扩展 channel 分发器接入邮件/短信等。
"""
from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from fastapi_app.shared_models import Base

if TYPE_CHECKING:
    from fastapi_app.shared_models.order import Order
    from fastapi_app.shared_models.user import User


class Notification(Base):
    """系统内消息通知"""
    __tablename__ = 'notification'

    __table_args__ = (
        Index('ix_notification_user_read', 'user_id', 'is_read'),
        Index('ix_notification_created_at', 'created_at'),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey('user.id'), nullable=False, index=True, comment='接收人ID')
    type: Mapped[str] = mapped_column(String(30), nullable=False, comment='通知类型：new_order/order_updated')
    title: Mapped[str] = mapped_column(String(200), nullable=False, comment='通知标题')
    content: Mapped[str | None] = mapped_column(Text, nullable=True, comment='通知内容')
    related_order_id: Mapped[int | None] = mapped_column(Integer, ForeignKey('order.id'), nullable=True, comment='关联订单ID')
    is_read: Mapped[bool] = mapped_column(Boolean, default=False, server_default='false', nullable=False, comment='是否已读')
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        nullable=False,
        comment='创建时间',
    )

    user: Mapped[User] = relationship('User')
    order: Mapped[Order | None] = relationship('Order')

    def to_dict(self) -> dict:
        """返回所有字段的字典表示"""
        return {
            'id': self.id,
            'user_id': self.user_id,
            'type': self.type,
            'title': self.title,
            'content': self.content,
            'related_order_id': self.related_order_id,
            'is_read': self.is_read,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }

    def __repr__(self):
        return f'<Notification id={self.id} user_id={self.user_id} type={self.type} is_read={self.is_read}>'
