"""
订单模型 - 纯 SQLAlchemy 2.0 声明式

映射到与 Flask-SQLAlchemy Order 相同的 'order' 表。
"""
from sqlalchemy import String, Integer, Text, Boolean, DateTime, ForeignKey, Index
from sqlalchemy.orm import Mapped, mapped_column, relationship
from datetime import datetime

from fastapi_app.shared_models import Base


VALID_ORDER_STATUSES = {'待备货', '部分备货', '已备货', '待出货', '已出货', '已完成', '已取消'}

STATUS_TRANSITIONS = {
    '待备货': {'部分备货', '已备货', '已取消'},
    '部分备货': {'已备货', '待出货', '已取消'},
    '已备货': {'待出货', '已取消'},
    '待出货': {'已出货', '已取消'},
    '已出货': {'已完成'},
    '已完成': set(),
    '已取消': set(),
}

DELETABLE_STATUSES = {'待备货', '部分备货', '已取消'}
EDITABLE_STATUSES = {'待备货', '部分备货'}


class Order(Base):
    """订单模型"""
    __tablename__ = 'order'

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    order_no: Mapped[str] = mapped_column(String(20), unique=True, nullable=False, comment='订单编号')
    customer: Mapped[str] = mapped_column(String(100), nullable=False, index=True, comment='客户名称')
    order_date: Mapped[datetime | None] = mapped_column(DateTime, default=datetime.now, index=True, comment='下单时间')
    product_id: Mapped[int] = mapped_column(Integer, ForeignKey('product.id'), nullable=False, index=True, comment='产品ID')
    quantity: Mapped[int] = mapped_column(Integer, nullable=False, comment='订单数量')
    status: Mapped[str] = mapped_column(String(20), default='待备货', nullable=False, index=True, comment='订单状态')
    note: Mapped[str | None] = mapped_column(Text, comment='备注')
    batch_no: Mapped[str | None] = mapped_column(String(100), comment='批次号')
    order_type: Mapped[str] = mapped_column(String(20), default='regular', nullable=False, comment='订单类型：regular=常规订单, custom=定制订单')
    country: Mapped[str | None] = mapped_column(String(100), comment='国家名称（仅定制订单使用）')
    is_locked: Mapped[bool | None] = mapped_column(Boolean, default=False, comment='是否被审批锁定')
    locked_by_id: Mapped[int | None] = mapped_column(Integer, ForeignKey('user.id'), comment='锁定人ID')
    lock_time: Mapped[datetime | None] = mapped_column(DateTime, comment='锁定时间')

    is_deleted: Mapped[bool | None] = mapped_column(Boolean, default=False, index=True, comment='是否已删除')
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime, comment='删除时间')
    deleted_by_id: Mapped[int | None] = mapped_column(Integer, ForeignKey('user.id'), comment='删除人ID')
    delete_reason: Mapped[str | None] = mapped_column(String(500), comment='删除原因')

    product: Mapped["Product"] = relationship('Product', backref='orders')
    locked_by: Mapped["User | None"] = relationship('User', foreign_keys=[locked_by_id], backref='locked_orders')
    deleted_by: Mapped["User | None"] = relationship('User', foreign_keys=[deleted_by_id], backref='deleted_orders')

    __table_args__ = (
        Index('idx_order_customer_status', 'customer', 'status'),
        Index('idx_order_product_status', 'product_id', 'status'),
        Index('idx_order_status_date', 'status', 'order_date'),
        Index('idx_order_customer_product', 'customer', 'product_id'),
        Index('idx_order_locked', 'is_locked'),
        Index('idx_order_type', 'order_type'),
        {'quote': True},
    )

    @classmethod
    def validate_status(cls, status: str) -> None:
        if status not in VALID_ORDER_STATUSES:
            raise ValueError(f"无效的订单状态: '{status}'，合法值: {', '.join(sorted(VALID_ORDER_STATUSES))}")

    def can_transition_to(self, new_status: str) -> bool:
        self.validate_status(new_status)
        allowed = STATUS_TRANSITIONS.get(self.status, set())
        return new_status in allowed or self.status == new_status

    def transition_to(self, new_status: str) -> None:
        if not self.can_transition_to(new_status):
            allowed = STATUS_TRANSITIONS.get(self.status, set())
            raise ValueError(
                f"订单 {self.order_no} 不允许从 '{self.status}' 变更为 '{new_status}'，"
                f"允许的目标状态: {', '.join(sorted(allowed)) if allowed else '无（终态）'}"
            )
        self.status = new_status

    def is_deletable(self) -> bool:
        return self.status in DELETABLE_STATUSES

    def is_editable(self) -> bool:
        return self.status in EDITABLE_STATUSES

    def __repr__(self):
        return f'<Order {self.order_no}>'

    def to_dict(self):
        return {
            'id': self.id,
            'order_no': self.order_no,
            'customer': self.customer,
            'order_date': self.order_date.isoformat() if self.order_date else None,
            'product_id': self.product_id,
            'product_name': self.product.name if self.product else None,
            'quantity': self.quantity,
            'status': self.status,
            'note': self.note,
            'order_type': self.order_type,
            'country': self.country or '',
            'is_locked': self.is_locked,
            'is_deleted': self.is_deleted,
            'created_at': self.order_date.isoformat() if self.order_date else None,
            'deleted_at': self.deleted_at.isoformat() if self.deleted_at else None,
            'delete_reason': self.delete_reason,
        }
