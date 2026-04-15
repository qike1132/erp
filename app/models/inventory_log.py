"""
库存日志模型
"""
from datetime import datetime
from app import db


class InventoryLog(db.Model):
    """库存日志模型"""
    id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(db.Integer, db.ForeignKey('product.id', ondelete='CASCADE'), nullable=False, index=True, comment='产品ID')
    change_type = db.Column(db.String(20), nullable=False, index=True, comment='变化类型：初始库存、备货、出货、订单调整')
    change_quantity = db.Column(db.Integer, nullable=False, comment='变化数量（正数为增加，负数为减少）')
    change_date = db.Column(db.DateTime, default=datetime.now, index=True, comment='变化时间')
    related_id = db.Column(db.String(50), comment='关联单据编号')
    note = db.Column(db.Text, comment='备注')
    customer = db.Column(db.String(100), nullable=True, index=True, comment='客户名称')
    product = db.relationship('Product', backref=db.backref('inventory_logs', lazy=True))

    __table_args__ = (
        db.Index('idx_inventory_log_product_date', 'product_id', db.desc('change_date')),
    )

    def __repr__(self):
        return f'<InventoryLog {self.id}>'
