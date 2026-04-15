"""
来料登记模型
"""
from datetime import datetime
from app import db


class MaterialRegistration(db.Model):
    """来料登记主表"""
    __tablename__ = 'material_registration'

    id = db.Column(db.Integer, primary_key=True)
    purchase_order_id = db.Column(db.Integer, db.ForeignKey('purchase_order.id'), nullable=False, comment='采购订单ID')
    purchase_order_no = db.Column(db.String(30), nullable=False, comment='采购订单号')
    supplier_id = db.Column(db.Integer, db.ForeignKey('supplier.id'), comment='供应商ID')
    supplier_name = db.Column(db.String(100), comment='供应商名称')
    registration_date = db.Column(db.Date, nullable=False, default=datetime.now().date, comment='登记日期')
    remark = db.Column(db.Text, comment='备注')
    status = db.Column(db.String(20), default='pending', comment='状态: pending/partial/completed')
    create_time = db.Column(db.DateTime, default=datetime.now, comment='创建时间')
    update_time = db.Column(db.DateTime, default=datetime.now, onupdate=datetime.now, comment='更新时间')
    created_by = db.Column(db.Integer, db.ForeignKey('user.id'), comment='创建人')

    items = db.relationship('MaterialRegistrationItem', backref='registration', cascade='all, delete-orphan', lazy='select')
    purchase_order = db.relationship('PurchaseOrder', backref='registrations')

    @property
    def computed_status(self):
        """根据进度计算状态: pending/partial/completed
        必须每个物料项都 individually 完成才算 completed，
        避免单项超收导致总和达标但其他项未完成的误判。
        """
        items_list = list(self.items)
        if not items_list:
            return 'pending'
        total_ordered = sum(float(item.ordered_quantity or 0) for item in items_list)
        total_received = sum(float(item.received_quantity or 0) for item in items_list)
        if total_ordered <= 0:
            return 'pending'
        all_items_complete = all(
            float(item.received_quantity or 0) >= float(item.ordered_quantity or 0)
            for item in items_list if float(item.ordered_quantity or 0) > 0
        )
        if all_items_complete:
            return 'completed'
        elif total_received > 0:
            return 'partial'
        return 'pending'

    @property
    def progress(self):
        """计算总进度百分比，未全部完成时上限99.9%"""
        items_list = list(self.items)
        total_ordered = sum(float(item.ordered_quantity or 0) for item in items_list)
        total_received = sum(float(item.received_quantity or 0) for item in items_list)
        if total_ordered <= 0:
            return 0
        all_complete = all(
            float(item.received_quantity or 0) >= float(item.ordered_quantity or 0)
            for item in items_list if float(item.ordered_quantity or 0) > 0
        )
        if all_complete:
            return 100.0
        return min(round(total_received / total_ordered * 100, 1), 99.9)

    def update_status(self):
        """根据明细项重新计算并更新status字段
        必须每个物料项都 individually 完成才算 completed。
        """
        items_list = list(self.items)
        total_ordered = sum(float(item.ordered_quantity or 0) for item in items_list)
        total_received = sum(float(item.received_quantity or 0) for item in items_list)
        if total_ordered <= 0:
            self.status = 'pending'
        elif all(
            float(item.received_quantity or 0) >= float(item.ordered_quantity or 0)
            for item in items_list if float(item.ordered_quantity or 0) > 0
        ):
            self.status = 'completed'
        elif total_received > 0:
            self.status = 'partial'
        else:
            self.status = 'pending'

    def to_dict(self):
        items_list = list(self.items)
        total_ordered = sum(float(item.ordered_quantity or 0) for item in items_list)
        total_received = sum(float(item.received_quantity or 0) for item in items_list)

        # 状态判断：必须每个物料项都 individually 完成才算 completed，
        # 避免单项超收导致总和达标但其他项未完成的误判
        if total_ordered <= 0:
            computed_status = 'pending'
        elif all(
            float(item.received_quantity or 0) >= float(item.ordered_quantity or 0)
            for item in items_list if float(item.ordered_quantity or 0) > 0
        ):
            computed_status = 'completed'
        elif total_received > 0:
            computed_status = 'partial'
        else:
            computed_status = 'pending'

        # 进度百分比：未完成时上限为99.9，避免四舍五入到100%
        if total_ordered <= 0:
            progress = 0
        elif computed_status == 'completed':
            progress = 100.0
        else:
            progress = min(round(total_received / total_ordered * 100, 1), 99.9)

        # 同步更新缓存的status字段
        if self.status != computed_status:
            self.status = computed_status

        customer_name = None
        product_name = None
        product_quantity = None
        po_status = None
        if self.purchase_order:
            customer_name = self.purchase_order.customer_name
            product_name = self.purchase_order.product_name
            po_status = self.purchase_order.status
            if self.purchase_order.product_quantity:
                product_quantity = float(self.purchase_order.product_quantity)

        return {
            'id': self.id,
            'purchase_order_id': self.purchase_order_id,
            'purchase_order_no': self.purchase_order_no,
            'supplier_id': self.supplier_id,
            'supplier_name': self.supplier_name,
            'customer_name': customer_name,
            'product_name': product_name,
            'product_quantity': product_quantity,
            'po_status': po_status,
            'registration_date': self.registration_date.strftime('%Y-%m-%d') if self.registration_date else None,
            'status': computed_status,
            'remark': self.remark,
            'create_time': self.create_time.strftime('%Y-%m-%d %H:%M:%S') if self.create_time else None,
            'update_time': self.update_time.strftime('%Y-%m-%d %H:%M:%S') if self.update_time else None,
            'item_count': len(self.items),
            'total_ordered': round(total_ordered, 2),
            'total_received': round(total_received, 2),
            'total_remaining': round(total_ordered - total_received, 2),
            'progress': round(progress, 1),
            'items': [item.to_dict() for item in self.items]
        }


class MaterialRegistrationItem(db.Model):
    """来料登记明细表"""
    __tablename__ = 'material_registration_item'

    id = db.Column(db.Integer, primary_key=True)
    registration_id = db.Column(db.Integer, db.ForeignKey('material_registration.id'), nullable=False, comment='来料登记ID')
    order_item_id = db.Column(db.Integer, db.ForeignKey('purchase_order_item.id'), comment='采购订单明细ID')
    material_code = db.Column(db.String(50), comment='物料编码')
    material_name = db.Column(db.String(100), nullable=False, comment='物料名称')
    specification = db.Column(db.String(100), comment='规格型号')
    unit = db.Column(db.String(20), comment='计量单位')
    ordered_quantity = db.Column(db.Numeric(12, 2), nullable=False, default=0, comment='采购数量')
    received_quantity = db.Column(db.Numeric(12, 2), default=0, comment='已收货数量')
    material_category = db.Column(db.String(20), comment='物料分类: fabric/filling/accessory/packaging')
    remark = db.Column(db.Text, comment='备注')
    create_time = db.Column(db.DateTime, default=datetime.now, comment='创建时间')

    def to_dict(self):
        ordered = float(self.ordered_quantity) if self.ordered_quantity else 0
        received = float(self.received_quantity) if self.received_quantity else 0
        remaining = ordered - received

        # 进度百分比：未完成时上限为99.9，避免四舍五入到100%
        if ordered <= 0:
            item_progress = 0
        elif received >= ordered:
            item_progress = 100.0
        else:
            item_progress = min(round(received / ordered * 100, 1), 99.9)

        return {
            'id': self.id,
            'registration_id': self.registration_id,
            'order_item_id': self.order_item_id,
            'material_code': self.material_code,
            'material_name': self.material_name,
            'specification': self.specification,
            'unit': self.unit,
            'ordered_quantity': ordered,
            'received_quantity': received,
            'remaining_quantity': round(remaining, 2),
            'progress': round(item_progress, 1),
            'material_category': self.material_category,
            'remark': self.remark,
            'create_time': self.create_time.strftime('%Y-%m-%d %H:%M:%S') if self.create_time else None
        }
