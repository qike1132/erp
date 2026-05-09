"""
采购订单模型 - 纯 SQLAlchemy 2.0 声明式

映射到与 Flask-SQLAlchemy PurchaseOrder/PurchaseOrderItem 相同的表。
"""
from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Date, DateTime, ForeignKey, Index, Integer, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from fastapi_app.shared_models import Base

if TYPE_CHECKING:
    from fastapi_app.shared_models.product import Product
    from fastapi_app.shared_models.supplier import Supplier


class PurchaseOrder(Base):
    """采购订单主表"""
    __tablename__ = 'purchase_order'

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    order_no: Mapped[str] = mapped_column(String(30), nullable=False, unique=True, index=True, comment='订单编号')
    supplier_id: Mapped[int | None] = mapped_column(Integer, ForeignKey('supplier.id'), comment='供应商ID')
    supplier_name: Mapped[str | None] = mapped_column(String(100), comment='供应商名称(冗余)')
    supplier_contact_person: Mapped[str | None] = mapped_column(String(50), comment='供应商联系人(冗余)')
    supplier_phone: Mapped[str | None] = mapped_column(String(20), comment='供应商电话(冗余)')
    supplier_address: Mapped[str | None] = mapped_column(String(200), comment='供应商地址(冗余)')
    customer_id: Mapped[int | None] = mapped_column(Integer, ForeignKey('customer.id'), comment='客户ID')
    customer_name: Mapped[str | None] = mapped_column(String(100), comment='客户名称(冗余)')
    customer_code: Mapped[str | None] = mapped_column(String(50), comment='客户编码')
    order_date: Mapped[datetime | None] = mapped_column(Date, comment='下单日期')
    status: Mapped[str | None] = mapped_column(String(20), default='pending', comment='状态')
    remark: Mapped[str | None] = mapped_column(Text, comment='备注')
    source_order_id: Mapped[int | None] = mapped_column(Integer, index=True, comment='关联的原始订单ID(单)')
    source_order_ids: Mapped[str | None] = mapped_column(Text, comment='关联的原始订单IDs(JSON数组)')
    product_name: Mapped[str | None] = mapped_column(String(200), comment='产品名称')
    product_quantity: Mapped[float | None] = mapped_column(Numeric(12, 2), comment='订单数量')
    total_amount: Mapped[float | None] = mapped_column(Numeric(12, 2), default=0, comment='订单总金额')
    create_time: Mapped[datetime | None] = mapped_column(DateTime, default=datetime.now, comment='创建时间')
    update_time: Mapped[datetime | None] = mapped_column(DateTime, default=datetime.now, onupdate=datetime.now, comment='更新时间')
    created_by: Mapped[int | None] = mapped_column(Integer, ForeignKey('user.id'), comment='创建人')
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, comment='完成时间')
    completed_by: Mapped[str | None] = mapped_column(String(50), comment='完成人')

    items: Mapped[list["PurchaseOrderItem"]] = relationship(
        'PurchaseOrderItem', backref='order', cascade='all, delete-orphan', lazy='selectin'
    )
    supplier_rel: Mapped["Supplier | None"] = relationship(
        "Supplier", back_populates="purchase_orders", lazy="selectin"
    )

    __table_args__ = (
        Index('idx_purchase_order_supplier', 'supplier_id'),
        Index('idx_purchase_order_customer', 'customer_id'),
        Index('idx_purchase_order_status', 'status'),
        Index('idx_purchase_order_date', 'order_date'),
        Index('idx_purchase_order_created_by', 'created_by'),
        Index('idx_purchase_order_source_order_id', 'source_order_id'),
    )

    def __repr__(self):
        return f'<PurchaseOrder {self.order_no}>'

    def to_dict(self, source_orders=None):
        product_name = self.product_name
        quantity = self.product_quantity
        if self.source_order_id:
            source_order = None
            if source_orders and self.source_order_id in source_orders:
                source_order = source_orders[self.source_order_id]
            if source_order:
                if not product_name and hasattr(source_order, 'product') and source_order.product:
                    product_name = source_order.product.name
                if not quantity and hasattr(source_order, 'quantity'):
                    quantity = source_order.quantity

        return {
            'id': self.id,
            'order_no': self.order_no,
            'supplier_id': self.supplier_id,
            'supplier_name': self.supplier_name,
            'supplier_contact_person': self.supplier_contact_person,
            'supplier_phone': self.supplier_phone,
            'supplier_address': self.supplier_address,
            'customer_id': self.customer_id,
            'customer_name': self.customer_name,
            'customer_code': self.customer_code,
            'order_date': self.order_date.strftime('%Y-%m-%d') if self.order_date else None,
            'status': self.status,
            'remark': self.remark,
            'source_order_id': self.source_order_id,
            'product_name': product_name,
            'product_quantity': float(self.product_quantity) if self.product_quantity else None,
            'create_time': self.create_time.strftime('%Y-%m-%d %H:%M:%S') if self.create_time else None,
            'update_time': self.update_time.strftime('%Y-%m-%d %H:%M:%S') if self.update_time else None,
            'completed_at': self.completed_at.strftime('%Y-%m-%d %H:%M:%S') if self.completed_at else None,
            'completed_by': self.completed_by,
            'item_count': len(self.items) if self.items else 0,
            'items': [item.to_dict() for item in self.items] if self.items else [],
            'quantity': float(quantity) if quantity else None
        }


class PurchaseOrderItem(Base):
    """采购订单明细表"""
    __tablename__ = 'purchase_order_item'

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    order_id: Mapped[int] = mapped_column(Integer, ForeignKey('purchase_order.id'), nullable=False, comment='采购订单ID')
    product_name: Mapped[str | None] = mapped_column(String(200), comment='产品名称')
    barcode: Mapped[str | None] = mapped_column(String(50), comment='产品条码')
    customer_name: Mapped[str | None] = mapped_column(String(100), comment='客户名称')
    material_code: Mapped[str | None] = mapped_column(String(50), comment='物料编码')
    material_name: Mapped[str] = mapped_column(String(100), nullable=False, comment='物料名称')
    specification: Mapped[str | None] = mapped_column(String(100), comment='规格型号')
    unit: Mapped[str | None] = mapped_column(String(20), comment='计量单位')
    quantity: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False, default=0, comment='采购数量')
    unit_usage: Mapped[float | None] = mapped_column(Numeric(10, 4), default=0, comment='单SKU标准用量')
    unit_price: Mapped[float | None] = mapped_column(Numeric(12, 2), default=0, comment='单价')
    total_price: Mapped[float | None] = mapped_column(Numeric(12, 2), default=0, comment='总价')
    material_category: Mapped[str | None] = mapped_column(String(20), comment='物料分类')
    remark: Mapped[str | None] = mapped_column(Text, comment='备注')
    supplier_name: Mapped[str | None] = mapped_column(String(100), comment='供应商名称(明细级)')
    create_time: Mapped[datetime | None] = mapped_column(DateTime, default=datetime.now, comment='创建时间')
    updated_at: Mapped[datetime | None] = mapped_column(DateTime, default=datetime.now, onupdate=datetime.now, comment='更新时间')


    __table_args__ = (
        Index('idx_purchase_order_item_order', 'order_id'),
        Index('idx_purchase_order_item_material', 'material_name'),
    )

    def __repr__(self):
        return f'<PurchaseOrderItem {self.material_name}>'

    def to_dict(self):
        return {
            'id': self.id,
            'order_id': self.order_id,
            'product_name': self.product_name,
            'barcode': self.barcode,
            'customer_name': self.customer_name,
            'material_code': self.material_code,
            'material_name': self.material_name,
            'specification': self.specification,
            'unit': self.unit,
            'quantity': float(self.quantity) if self.quantity else 0,
            'unit_usage': float(self.unit_usage) if self.unit_usage else 0,
            'unit_price': float(self.unit_price) if self.unit_price else 0,
            'total_price': float(self.total_price) if self.total_price else 0,
            'material_category': self.material_category,
            'supplier_name': self.supplier_name,
            'remark': self.remark
        }
