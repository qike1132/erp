"""
订单模型 - 纯 SQLAlchemy 2.0 声明式

映射到 'order' 表。
"""
from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, Text, desc, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from fastapi_app.shared_models import Base

if TYPE_CHECKING:
    from fastapi_app.shared_models.order_item import OrderItem
    from fastapi_app.shared_models.product import Product
    from fastapi_app.shared_models.user import User

# 订单状态的唯一权威定义：业务代码一律引用这些常量，禁止新增字面量（保持单一来源）
ORDER_STATUS_PENDING_STOCK = '待备货'
ORDER_STATUS_PARTIAL_STOCK = '部分备货'
ORDER_STATUS_STOCKED = '已备货'
ORDER_STATUS_PENDING_SHIPMENT = '待出货'
ORDER_STATUS_SHIPPED = '已出货'
ORDER_STATUS_CANCELLED = '已取消'
ORDER_STATUS_BATCH_COMPLETED = '批次已完成'

VALID_ORDER_STATUSES = frozenset({
    ORDER_STATUS_PENDING_STOCK,
    ORDER_STATUS_PARTIAL_STOCK,
    ORDER_STATUS_STOCKED,
    ORDER_STATUS_PENDING_SHIPMENT,
    ORDER_STATUS_SHIPPED,
    ORDER_STATUS_CANCELLED,
    ORDER_STATUS_BATCH_COMPLETED,
})


def compute_status_from_stockouts(order, deducted_qty: int, shipped_qty: int) -> str:
    """
    根据订单业务数据（备货量、出货量）派生订单状态。

    状态由业务事实推导，而非手动推进状态机：
    - deducted_qty: 净备货抵扣量（StockOut.stockin_id IS NOT NULL 的 quantity-returned_quantity 之和）
    - shipped_qty: 净独立出货量（StockOut.stockin_id IS NULL 的 quantity-returned_quantity 之和）

    TODO(multi-sku-order): 多 SKU 模型下 order.quantity 为兼容值（sum of items），状态计算
    语义需重新设计（按 OrderItem 维度还是按聚合 quantity？），待后续 spec 改造。
    """
    if order.batch_completed_at:
        result = ORDER_STATUS_BATCH_COMPLETED
    elif shipped_qty >= order.quantity:
        result = ORDER_STATUS_SHIPPED
    elif shipped_qty > 0:
        result = ORDER_STATUS_PENDING_SHIPMENT
    elif deducted_qty >= order.quantity:
        result = ORDER_STATUS_STOCKED
    elif deducted_qty > 0:
        result = ORDER_STATUS_PARTIAL_STOCK
    else:
        result = ORDER_STATUS_PENDING_STOCK
    Order.validate_status(result)
    return result


class Order(Base):
    """订单模型"""
    __tablename__ = 'order'

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    order_no: Mapped[str] = mapped_column(String(20), unique=True, nullable=False, comment='订单编号')
    customer: Mapped[str] = mapped_column(String(100), nullable=False, index=True, comment='客户名称')
    order_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC), index=True, comment='下单时间')
    product_id: Mapped[int | None] = mapped_column(Integer, ForeignKey('product.id', ondelete='SET NULL'), nullable=True, index=True, comment='产品ID')
    quantity: Mapped[int] = mapped_column(Integer, nullable=False, comment='订单数量')
    status: Mapped[str | None] = mapped_column(String(20), default=None, nullable=True, index=True, comment='订单状态')
    note: Mapped[str | None] = mapped_column(Text, comment='备注')
    batch_no: Mapped[str | None] = mapped_column(String(100), comment='批次号')
    is_locked: Mapped[bool | None] = mapped_column(Boolean, default=False, comment='是否被审批锁定')
    locked_by_id: Mapped[int | None] = mapped_column(Integer, ForeignKey('user.id', ondelete='SET NULL'), comment='锁定人ID')
    lock_time: Mapped[datetime | None] = mapped_column(DateTime, comment='锁定时间')

    batch_completed_at: Mapped[datetime | None] = mapped_column(DateTime, comment='批次完成时间')
    batch_completed_by_id: Mapped[int | None] = mapped_column(Integer, ForeignKey('user.id', ondelete='SET NULL'), comment='批次完成操作人ID')

    # 湖北订单确认流程（与派生状态机正交）
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime, comment='订单确认时间（湖北订单确认流程）')
    confirmed_by_id: Mapped[int | None] = mapped_column(Integer, ForeignKey('user.id', ondelete='SET NULL'), comment='订单确认人ID')

    is_deleted: Mapped[bool | None] = mapped_column(Boolean, default=False, index=True, comment='是否已删除')
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime, comment='删除时间')
    deleted_by_id: Mapped[int | None] = mapped_column(Integer, ForeignKey('user.id', ondelete='SET NULL'), comment='删除人ID')
    delete_reason: Mapped[str | None] = mapped_column(String(500), comment='删除原因')
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC), onupdate=lambda: datetime.now(UTC), comment='更新时间')


    product: Mapped[Product] = relationship('Product', backref='orders')
    locked_by: Mapped[User | None] = relationship('User', foreign_keys=[locked_by_id], backref='locked_orders')
    deleted_by: Mapped[User | None] = relationship('User', foreign_keys=[deleted_by_id], backref='deleted_orders')
    batch_completed_by: Mapped[User | None] = relationship('User', foreign_keys=[batch_completed_by_id], backref='batch_completed_orders')
    confirmed_by: Mapped[User | None] = relationship('User', foreign_keys=[confirmed_by_id], backref='confirmed_orders')
    items: Mapped[list[OrderItem]] = relationship(
        'OrderItem',
        cascade='all, delete-orphan',
        back_populates='order',
        order_by='OrderItem.id',
    )

    __table_args__ = (
        Index('idx_order_customer_status', 'customer', 'status'),
        Index('idx_order_product_status', 'product_id', 'status'),
        Index('idx_order_status_date', 'status', 'order_date'),
        Index('idx_order_batch_no', 'batch_no'),
        Index('idx_order_locked_by', 'locked_by_id'),
        Index('idx_order_customer_trgm', 'customer', postgresql_using='gin',
              postgresql_ops={'customer': 'gin_trgm_ops'}),
        Index('idx_perf_order_status_date_covering', 'status', desc('order_date'), 'id',
              postgresql_where=text("is_deleted = false")),
        Index('idx_perf_order_customer_date', 'customer', desc('order_date'),
              postgresql_where=text("is_deleted = false")),
        Index('idx_order_batch_completed', desc('batch_completed_at'),
              postgresql_where=text("batch_completed_at IS NOT NULL")),
        # 订单列表游标分页主路径：ORDER BY order_date DESC, id DESC
        # WHERE is_deleted IS NOT TRUE（见 services/order/queries.py:141-157）。
        # 谓词必须与库中一致写作 `is_deleted IS NOT TRUE`（而非 ORM 别处的 `= false`），
        # 否则 alembic 视为不同索引。
        Index('idx_order_date_id_desc', desc('order_date'), desc('id'),
              postgresql_where=text("is_deleted IS NOT TRUE")),
        {'quote': True},
    )

    @classmethod
    def validate_status(cls, status: str | None) -> None:
        if status is not None and status not in VALID_ORDER_STATUSES:
            raise ValueError(f"无效的订单状态: '{status}'，合法值: {', '.join(sorted(VALID_ORDER_STATUSES))}")

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
            'is_locked': self.is_locked,
            'is_deleted': self.is_deleted,
            'created_at': self.order_date.isoformat() if self.order_date else None,
            'deleted_at': self.deleted_at.isoformat() if self.deleted_at else None,
            'delete_reason': self.delete_reason,
            'factories': sorted({item.product.factory for item in self.items if item.product and item.product.factory}),
        }
