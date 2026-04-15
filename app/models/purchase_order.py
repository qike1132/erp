"""
采购订单模型
"""
from datetime import datetime
from app import db


class PurchaseOrder(db.Model):
    """采购订单主表"""
    __tablename__ = 'purchase_order'
    
    id = db.Column(db.Integer, primary_key=True)
    order_no = db.Column(db.String(30), nullable=False, unique=True, index=True, comment='订单编号')
    supplier_id = db.Column(db.Integer, db.ForeignKey('supplier.id'), comment='供应商ID')
    supplier_name = db.Column(db.String(100), comment='供应商名称(冗余)')
    supplier_contact_person = db.Column(db.String(50), comment='供应商联系人(冗余)')
    supplier_phone = db.Column(db.String(20), comment='供应商电话(冗余)')
    supplier_address = db.Column(db.String(200), comment='供应商地址(冗余)')
    customer_id = db.Column(db.Integer, db.ForeignKey('customer.id'), comment='客户ID')
    customer_name = db.Column(db.String(100), comment='客户名称(冗余)')
    customer_code = db.Column(db.String(50), comment='客户编码')
    order_date = db.Column(db.Date, nullable=False, default=datetime.now().date, comment='下单日期')
    status = db.Column(db.String(20), default='pending', comment='状态: pending/completed/cancelled')
    remark = db.Column(db.Text, comment='备注')
    source_order_id = db.Column(db.Integer, comment='关联的原始订单ID(来自订单管理)')
    product_name = db.Column(db.String(200), comment='产品名称')
    product_quantity = db.Column(db.Numeric(12, 2), comment='订单数量')
    create_time = db.Column(db.DateTime, default=datetime.now, comment='创建时间')
    update_time = db.Column(db.DateTime, default=datetime.now, onupdate=datetime.now, comment='更新时间')
    created_by = db.Column(db.Integer, db.ForeignKey('user.id'), comment='创建人')
    completed_at = db.Column(db.DateTime, comment='完成时间')
    completed_by = db.Column(db.String(50), comment='完成人')
    
    items = db.relationship('PurchaseOrderItem', backref='order', cascade='all, delete-orphan', lazy='select')

    def to_dict(self, source_orders=None):
        product_name = self.product_name
        quantity = self.product_quantity
        if self.source_order_id:
            source_order = None
            if source_orders and self.source_order_id in source_orders:
                source_order = source_orders[self.source_order_id]
            else:
                from app.models.order import Order
                source_order = Order.query.get(self.source_order_id)
            if source_order:
                if not product_name and source_order.product:
                    product_name = source_order.product.name
                if not quantity:
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
            'item_count': len(self.items),
            'items': [item.to_dict() for item in self.items],
            'quantity': float(quantity) if quantity else None
        }


class PurchaseOrderItem(db.Model):
    """采购订单明细表"""
    __tablename__ = 'purchase_order_item'

    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.Integer, db.ForeignKey('purchase_order.id'), nullable=False, comment='采购订单ID')
    material_code = db.Column(db.String(50), comment='物料编码')
    material_name = db.Column(db.String(100), nullable=False, comment='物料名称')
    specification = db.Column(db.String(100), comment='规格型号')
    unit = db.Column(db.String(20), comment='计量单位')
    quantity = db.Column(db.Numeric(12, 2), nullable=False, default=0, comment='采购数量')
    unit_usage = db.Column(db.Numeric(10, 4), default=0, comment='单SKU标准用量')
    material_category = db.Column(db.String(20), comment='物料分类: fabric/filling/accessory/packaging')
    remark = db.Column(db.Text, comment='备注')
    supplier_name = db.Column(db.String(100), comment='供应商名称(明细级)')
    create_time = db.Column(db.DateTime, default=datetime.now, comment='创建时间')

    def to_dict(self):
        return {
            'id': self.id,
            'order_id': self.order_id,
            'material_code': self.material_code,
            'material_name': self.material_name,
            'specification': self.specification,
            'unit': self.unit,
            'quantity': float(self.quantity) if self.quantity else 0,
            'unit_usage': float(self.unit_usage) if self.unit_usage else 0,
            'material_category': self.material_category,
            'supplier_name': self.supplier_name,
            'remark': self.remark
        }
