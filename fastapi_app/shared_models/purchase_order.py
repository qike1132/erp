"""
采购订单模型 - 纯 SQLAlchemy 2.0 声明式
"""
from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import (
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    desc,
    func,
)
from sqlalchemy import inspect as sa_inspect
from sqlalchemy.orm import Mapped, mapped_column, relationship

from fastapi_app.shared_models import Base

if TYPE_CHECKING:
    from fastapi_app.shared_models.supplier import Supplier


class PurchaseOrderStatus:
    """采购订单状态唯一权威定义：业务代码引用常量，禁止新增字面量。

    DB 存在历史 'confirmed' 数据（见 uq_po_pending_dedup 索引注释），
    现行代码路径只产生 pending / completed 两种状态。
    """
    PENDING = 'pending'
    COMPLETED = 'completed'


class PurchaseOrder(Base):
    """采购订单主表"""
    __tablename__ = 'purchase_order'

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    order_no: Mapped[str] = mapped_column(String(30), nullable=False, unique=True, comment='订单编号')
    supplier_id: Mapped[int | None] = mapped_column(Integer, ForeignKey('supplier.id'), comment='供应商ID')
    supplier_name: Mapped[str | None] = mapped_column(String(100), comment='供应商名称(冗余)')
    supplier_contact_person: Mapped[str | None] = mapped_column(String(50), comment='供应商联系人(冗余)')
    supplier_phone: Mapped[str | None] = mapped_column(String(20), comment='供应商电话(冗余)')
    supplier_address: Mapped[str | None] = mapped_column(String(200), comment='供应商地址(冗余)')
    customer_id: Mapped[int | None] = mapped_column(Integer, ForeignKey('customer.id'), comment='客户ID')
    customer_name: Mapped[str | None] = mapped_column(String(100), comment='客户名称(冗余)')
    customer_code: Mapped[str | None] = mapped_column(String(50), comment='客户编码')
    order_date: Mapped[date | None] = mapped_column(Date, comment='下单日期')
    status: Mapped[str | None] = mapped_column(String(20), default='pending', comment='状态')
    remark: Mapped[str | None] = mapped_column(Text, comment='备注')
    source_order_id: Mapped[int | None] = mapped_column(Integer, index=True, comment='关联的原始订单ID(单)')
    source_order_ids: Mapped[str | None] = mapped_column(Text, comment='关联的原始订单IDs(JSON数组)')
    product_name: Mapped[str | None] = mapped_column(String(200), comment='产品名称')
    product_quantity: Mapped[float | None] = mapped_column(Numeric(12, 2), comment='订单数量')
    spare_quantity: Mapped[float | None] = mapped_column(
        Numeric(12, 2), comment='备品数量=ceil(订单数量×损耗率‰)，随下单/保存写入',
    )
    spare_rate: Mapped[float | None] = mapped_column(
        Numeric(8, 2), comment='损耗率快照(千分之几)，用于追溯备品按多少损耗率算出',
    )
    total_amount: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), default=0, comment='订单总金额')
    create_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC), comment='创建时间')
    update_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC), onupdate=lambda: datetime.now(UTC), comment='更新时间')
    created_by: Mapped[int | None] = mapped_column(Integer, ForeignKey('user.id'), comment='创建人')
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, comment='完成时间')
    completed_by: Mapped[str | None] = mapped_column(String(50), comment='完成人')

    items: Mapped[list[PurchaseOrderItem]] = relationship(
        'PurchaseOrderItem', backref='order', cascade='all, delete-orphan', lazy='raise'
    )
    # 逐 SKU 数量快照（方案 C）：本仓 ORM 约定 lazy='raise'，读取必须显式
    # selectinload / joinedload；删除采购单时随主表级联清理（含 DB 级 ondelete='CASCADE'）。
    skus: Mapped[list[PurchaseOrderSku]] = relationship(
        'PurchaseOrderSku', backref='order', cascade='all, delete-orphan', lazy='raise'
    )
    supplier_rel: Mapped[Supplier | None] = relationship(
        "Supplier", back_populates="purchase_orders", lazy="raise"
    )

    __table_args__ = (
        Index('idx_purchase_order_supplier', 'supplier_id'),
        Index('idx_purchase_order_customer', 'customer_id'),
        Index('idx_purchase_order_status', 'status'),
        Index('idx_purchase_order_date', 'order_date'),
        Index('idx_purchase_order_created_by', 'created_by'),
        Index('idx_purchase_order_source_order_id', 'source_order_id'),
        Index('idx_purchase_order_status_created', 'status', 'create_time'),
        Index('idx_purchase_order_supplier_status', 'supplier_id', 'status'),
        Index('idx_po_status_date_covering', 'status', desc('create_time'), 'id',
              postgresql_include=['order_no', 'supplier_name', 'customer_name']),
        # 防止一键审核产生重复 pending 采购单：同一客户 + 同一供应商 +
        # 同一 source_order_ids 集合，pending 状态下全局唯一。confirmed / completed
        # 不受此约束。使用 COALESCE 处理 NULL（PG 默认 NULL != NULL 导致约束失效）。
        # 注意：必须用 supplier_name 而非 supplier_id，因为业务层按 supplier_name
        # 分组生成采购单，而 BOM 物料的 supplier_id 普遍为 NULL，用 supplier_id 会
        # 把不同供应商的新订单合并到同一 bucket 互相冲突。
        # 配套 alembic 迁移 rebuild_po_dedup_use_supplier_name.py。
        Index(
            'uq_po_pending_dedup',
            func.coalesce(customer_id, 0), func.coalesce(supplier_name, ''), 'source_order_ids',
            unique=True,
            postgresql_where=(status == 'pending'),
        ),
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

        _has_items = 'items' not in sa_inspect(self).unloaded
        _items = self.items if _has_items else []

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
            'spare_quantity': float(self.spare_quantity) if self.spare_quantity is not None else None,
            'spare_rate': float(self.spare_rate) if self.spare_rate is not None else None,
            'create_time': self.create_time.strftime('%Y-%m-%d %H:%M:%S') if self.create_time else None,
            'update_time': self.update_time.strftime('%Y-%m-%d %H:%M:%S') if self.update_time else None,
            'completed_at': self.completed_at.strftime('%Y-%m-%d %H:%M:%S') if self.completed_at else None,
            'completed_by': self.completed_by,
            'item_count': len(_items),
            'items': [item.to_dict() for item in _items],
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
    quantity: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False, default=0, comment='采购数量')
    unit_usage: Mapped[float | None] = mapped_column(Numeric(10, 4), default=0, comment='单SKU标准用量')
    unit_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), default=0, comment='单价')
    total_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), default=0, comment='总价')
    loss_rate: Mapped[Decimal | None] = mapped_column(Numeric(8, 2), comment='材料损耗率快照(千分之几)，逐布料行配置')
    material_category: Mapped[str | None] = mapped_column(String(20), comment='物料分类')
    remark: Mapped[str | None] = mapped_column(Text, comment='备注')
    supplier_name: Mapped[str | None] = mapped_column(String(100), comment='供应商名称(明细级)')
    create_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC), comment='创建时间')
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC), onupdate=lambda: datetime.now(UTC), comment='更新时间')


    __table_args__ = (
        Index('idx_purchase_order_item_order', 'order_id'),
        Index('idx_purchase_order_item_material', 'material_name'),
        Index('idx_perf_poi_order_include', 'order_id',
              postgresql_include=['material_name', 'quantity', 'unit_price']),
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
            'loss_rate': float(self.loss_rate) if self.loss_rate is not None else None,
            'material_category': self.material_category,
            'supplier_name': self.supplier_name,
            'remark': self.remark
        }


class PurchaseOrderSku(Base):
    """采购订单逐 SKU 数量快照（方案 C：治本）。

    **背景**（见 evidence/beile_multisku/多SKU订单数量显示-根因与方案.md RC-1）：
    汇总下单时「1 个客户 = 1 张采购单」，多 SKU 的产品名被 '、'.join 拼接、
    数量被求和写入 ``purchase_order.product_quantity``，于是「每个 SKU 各自
    下单多少」自落库起即**不可还原**，下游 /beile-order 只能给出订单级标量。
    本表把逐 SKU 的订单数量/备品量快照落库，供逐 SKU 展示与备品拆分。

    **口径**：一行 = 一个来源记录中的**一个产品名**（同一来源同产品名的多行会
    在写路径合并，见 services/purchase_order_sku.write_po_sku_rows）。
    恒等式：``Σ order_qty == purchase_order.product_quantity``（同一采集口径）。

    **source_record_type 必须保留**：本仓 order.id 与 stockin.id 会撞号
    （见 services/order/beile.py 内既有注释），没有该判别列会导致读路径串号。
    """

    __tablename__ = 'purchase_order_sku'

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    po_id: Mapped[int] = mapped_column(
        Integer, ForeignKey('purchase_order.id', ondelete='CASCADE'),
        nullable=False, comment='所属采购单ID',
    )
    product_name: Mapped[str | None] = mapped_column(String(200), comment='该 SKU 产品名（单 SKU，不拼接）')
    product_barcode: Mapped[str | None] = mapped_column(String(50), comment='该 SKU 条码')
    order_qty: Mapped[float | None] = mapped_column(Numeric(12, 2), comment='该 SKU 在来源记录中的订单数量')
    spare_qty: Mapped[float | None] = mapped_column(
        Numeric(12, 2), comment='该 SKU 备品数量=ceil(order_qty×损耗率‰)',
    )
    spare_rate: Mapped[float | None] = mapped_column(Numeric(8, 2), comment='损耗率快照(千分之几)')
    source_order_id: Mapped[int | None] = mapped_column(Integer, comment='来源客户订单/备货 id')
    source_record_type: Mapped[str | None] = mapped_column(
        String(10), comment="来源记录类型: 'order' / 'stockin'",
    )
    create_time: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), comment='创建时间',
    )

    __table_args__ = (
        # 唯一约束：保证写路径幂等（重复生成/回填不产生重复行）。
        # 选 (po_id, source_record_type, source_order_id, product_name) 的理由：
        #   1) 写路径已按同一四元组合并（同来源同产品名合并为一行），故不会冲突；
        #   2) 回填脚本以「先删后插」实现幂等，唯一约束是第二道防线；
        #   3) 不纳入 product_barcode：条码可为 NULL，PG 下 NULL != NULL 会使约束失效。
        UniqueConstraint(
            'po_id', 'source_record_type', 'source_order_id', 'product_name',
            name='uq_po_sku_po_source_product',
        ),
        Index('idx_purchase_order_sku_po', 'po_id'),
        Index('idx_purchase_order_sku_source', 'source_record_type', 'source_order_id'),
    )

    def __repr__(self):
        return f'<PurchaseOrderSku po={self.po_id} {self.product_name}>'
