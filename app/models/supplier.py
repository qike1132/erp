"""
供应商模型
"""
from datetime import datetime
from app import db


class Supplier(db.Model):
    """供应商模型"""
    __tablename__ = 'supplier'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False, unique=True, index=True, comment='供应商名称')
    contact_person = db.Column(db.String(50), comment='联系人')
    phone = db.Column(db.String(20), comment='联系电话')
    address = db.Column(db.String(200), comment='地址')
    bank_name = db.Column(db.String(100), comment='开户银行')
    bank_account = db.Column(db.String(50), comment='银行账号')
    remark = db.Column(db.Text, comment='备注')
    status = db.Column(db.Boolean, default=True, comment='状态')
    created_at = db.Column(db.DateTime, default=datetime.now, comment='创建时间')
    updated_at = db.Column(db.DateTime, default=datetime.now, onupdate=datetime.now, comment='更新时间')

    purchase_orders = db.relationship('PurchaseOrder', backref='supplier', lazy='dynamic')

    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'contact_person': self.contact_person,
            'phone': self.phone,
            'address': self.address,
            'bank_name': self.bank_name,
            'bank_account': self.bank_account,
            'remark': self.remark,
            'status': self.status,
            'created_at': self.created_at.strftime('%Y-%m-%d %H:%M:%S') if self.created_at else None
        }
