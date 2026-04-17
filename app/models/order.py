"""
订单模型
"""
from datetime import datetime
from app import db


class Order(db.Model):
    """订单模型"""
    __tablename__ = 'order'
    
    id = db.Column(db.Integer, primary_key=True)
    order_no = db.Column(db.String(20), unique=True, nullable=False, comment='订单编号')
    customer = db.Column(db.String(100), nullable=False, index=True, comment='客户名称')
    order_date = db.Column(db.DateTime, default=datetime.now, index=True, comment='下单时间')
    product_id = db.Column(db.Integer, db.ForeignKey('product.id'), nullable=False, index=True, comment='产品ID')
    quantity = db.Column(db.Integer, nullable=False, comment='订单数量')
    status = db.Column(db.String(20), default='待备货', index=True, comment='订单状态：待备货、部分备货、已备货、待出货、已出货、已取消')
    note = db.Column(db.Text, comment='备注')
    order_type = db.Column(db.String(20), default='regular', nullable=False, comment='订单类型：regular=常规订单, custom=定制订单')
    country = db.Column(db.String(100), comment='国家名称（仅定制订单使用）')
    is_locked = db.Column(db.Boolean, default=False, comment='是否被审批锁定')
    locked_by_id = db.Column(db.Integer, db.ForeignKey('user.id'), comment='锁定人ID')
    lock_time = db.Column(db.DateTime, comment='锁定时间')
    
    is_deleted = db.Column(db.Boolean, default=False, index=True, comment='是否已删除（软删除）')
    deleted_at = db.Column(db.DateTime, comment='删除时间')
    deleted_by_id = db.Column(db.Integer, db.ForeignKey('user.id'), comment='删除人ID')
    delete_reason = db.Column(db.String(500), comment='删除原因')
    
    product = db.relationship('Product', backref=db.backref('orders', lazy=True))
    locked_by = db.relationship('User', foreign_keys=[locked_by_id], backref=db.backref('locked_orders', lazy=True))
    deleted_by = db.relationship('User', foreign_keys=[deleted_by_id], backref=db.backref('deleted_orders', lazy=True))
    
    # 复合索引 - 用于常见查询场景
    __table_args__ = (
        # 按客户和状态查询（如：查询某客户的待备货订单）
        db.Index('idx_order_customer_status', 'customer', 'status'),
        # 按产品和状态查询（如：查询某产品的待备货订单）
        db.Index('idx_order_product_status', 'product_id', 'status'),
        # 按状态和日期查询（如：查询待备货订单按日期排序）
        db.Index('idx_order_status_date', 'status', 'order_date'),
        # 按客户和产品查询（用于抵扣逻辑）
        db.Index('idx_order_customer_product', 'customer', 'product_id'),
        # 按锁定状态查询
        db.Index('idx_order_locked', 'is_locked'),
        db.Index('idx_order_type', 'order_type'),
    )

    def __repr__(self):
        return f'<Order {self.order_no}>'
    
    def lock(self, user_id):
        """锁定订单"""
        self.is_locked = True
        self.locked_by_id = user_id
        self.lock_time = datetime.now()
    
    def unlock(self):
        """解锁订单"""
        self.is_locked = False
        self.locked_by_id = None
        self.lock_time = None
    
    def to_dict(self):
        """将订单对象转换为字典"""
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
            'delete_reason': self.delete_reason
        }
    
    def is_locked_by_other(self, user_id):
        """检查是否被其他用户锁定"""
        return self.is_locked and self.locked_by_id != user_id
