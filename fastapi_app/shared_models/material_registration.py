"""来料登记模型"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING

from sqlalchemy import Date, DateTime, ForeignKey, Index, Integer, Numeric, String, Text, desc
from sqlalchemy.orm import Mapped, mapped_column, relationship

from fastapi_app.shared_models import Base

if TYPE_CHECKING:
    from fastapi_app.shared_models.purchase_order import PurchaseOrder


class MaterialRegistration(Base):
    """来料登记主表"""
    __tablename__ = 'material_registration'

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    purchase_order_id: Mapped[int] = mapped_column(Integer, ForeignKey('purchase_order.id'), nullable=False)
    purchase_order_no: Mapped[str] = mapped_column(String(30), nullable=False)
    supplier_id: Mapped[int | None] = mapped_column(Integer, ForeignKey('supplier.id'))
    supplier_name: Mapped[str | None] = mapped_column(String(100))
    registration_date: Mapped[datetime | None] = mapped_column(Date, nullable=False, default=lambda: datetime.now(timezone.utc).date())
    remark: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default='pending')
    create_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    update_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
    created_by: Mapped[int | None] = mapped_column(Integer, ForeignKey('user.id'))

    items: Mapped[list["MaterialRegistrationItem"]] = relationship(
        "MaterialRegistrationItem", back_populates="registration",
        cascade="all, delete-orphan"
    )
    purchase_order: Mapped["PurchaseOrder"] = relationship("PurchaseOrder", backref="registrations")

    __table_args__ = (
        Index('idx_material_reg_purchase_order', 'purchase_order_id'),
        Index('idx_material_reg_supplier', 'supplier_id'),
        Index('idx_material_reg_status', 'status'),
        Index('idx_material_reg_date', 'registration_date'),
        Index('idx_material_reg_status_date', 'status', 'registration_date'),
        Index('idx_material_registration_created_by', 'created_by'),
        Index('idx_material_reg_create_time', desc('create_time')),
        Index('idx_material_reg_supplier_name', 'supplier_name'),
        Index('idx_material_reg_order_no', 'purchase_order_no'),
    )

    def _calc_items_stats(self):
        """计算物料项汇总统计（内部方法，供 computed_status/progress/to_dict 复用）"""
        items_list = list(self.items) if self.items else []
        total_ordered = sum(float(item.ordered_quantity or 0) for item in items_list)
        total_received = sum(float(item.received_quantity or 0) for item in items_list)
        all_complete = all(
            float(item.received_quantity or 0) >= float(item.ordered_quantity or 0)
            for item in items_list if float(item.ordered_quantity or 0) > 0
        )
        return items_list, total_ordered, total_received, all_complete

    @property
    def computed_status(self) -> str:
        """计算状态 - 必须每个物料项 individually 完成才算 completed"""
        items_list, total_ordered, total_received, all_complete = self._calc_items_stats()
        if not items_list:
            return 'pending'
        if all_complete:
            return 'completed'
        elif total_received > 0:
            return 'partial'
        return 'pending'

    @property
    def progress(self) -> float:
        """完成进度百分比，未全部完成时上限99.9%"""
        items_list, total_ordered, total_received, all_complete = self._calc_items_stats()
        if not total_ordered:
            return 0.0
        if all_complete:
            return 100.0
        return min(round(total_received / total_ordered * 100, 1), 99.9)

    def update_status(self):
        """根据明细更新状态"""
        self.status = self.computed_status

    def to_dict(self):
        items_list, total_ordered, total_received, _ = self._calc_items_stats()
        return {
            'id': self.id,
            'purchase_order_id': self.purchase_order_id,
            'purchase_order_no': self.purchase_order_no,
            'supplier_id': self.supplier_id,
            'supplier_name': self.supplier_name,
            'registration_date': self.registration_date.strftime('%Y-%m-%d') if self.registration_date else '',
            'remark': self.remark or '',
            'status': self.computed_status,
            'progress': self.progress,
            'create_time': self.create_time.strftime('%Y-%m-%d %H:%M:%S') if self.create_time else '',
            'update_time': self.update_time.strftime('%Y-%m-%d %H:%M:%S') if self.update_time else '',
            'items': [item.to_dict() for item in items_list],
            'customer_name': self.purchase_order.customer_name if self.purchase_order else None,
            'product_name': self.purchase_order.product_name if self.purchase_order else None,
            'product_quantity': float(self.purchase_order.product_quantity) if self.purchase_order and self.purchase_order.product_quantity else None,
            'po_status': self.purchase_order.status if self.purchase_order else None,
            'item_count': len(items_list),
            'total_ordered': total_ordered,
            'total_received': total_received,
            'total_remaining': total_ordered - total_received,
        }


class MaterialRegistrationItem(Base):
    """来料登记明细"""
    __tablename__ = 'material_registration_item'

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    registration_id: Mapped[int] = mapped_column(Integer, ForeignKey('material_registration.id'), nullable=False)
    order_item_id: Mapped[int | None] = mapped_column(Integer, ForeignKey('purchase_order_item.id'))
    material_code: Mapped[str | None] = mapped_column(String(50))
    material_name: Mapped[str] = mapped_column(String(100), nullable=False)
    specification: Mapped[str | None] = mapped_column(String(100))
    unit: Mapped[str | None] = mapped_column(String(20))
    ordered_quantity: Mapped[float] = mapped_column(Numeric(12, 2), default=0)
    received_quantity: Mapped[float] = mapped_column(Numeric(12, 2), default=0)
    material_category: Mapped[str | None] = mapped_column(String(20))
    remark: Mapped[str | None] = mapped_column(Text)
    create_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    registration: Mapped["MaterialRegistration"] = relationship(
        "MaterialRegistration", back_populates="items"
    )

    __table_args__ = (
        Index('idx_material_reg_item_name', 'material_name'),
        Index('idx_material_reg_item_registration', 'registration_id'),
        Index('idx_material_reg_item_order_item', 'order_item_id'),
    )

    def to_dict(self):
        ordered = float(self.ordered_quantity or 0)
        received = float(self.received_quantity or 0)
        remaining = ordered - received
        item_progress = min(round(received / ordered * 100, 1), 99.9) if ordered > 0 and received < ordered else (100.0 if received >= ordered and ordered > 0 else 0)
        return {
            'id': self.id,
            'registration_id': self.registration_id,
            'order_item_id': self.order_item_id,
            'material_code': self.material_code or '',
            'material_name': self.material_name,
            'specification': self.specification or '',
            'unit': self.unit or '',
            'ordered_quantity': ordered,
            'received_quantity': received,
            'remaining_quantity': remaining,
            'progress': item_progress,
            'material_category': self.material_category or '',
            'remark': self.remark or '',
            'create_time': self.create_time.strftime('%Y-%m-%d %H:%M:%S') if self.create_time else '',
        }
