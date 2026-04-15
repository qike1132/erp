"""
客户模型
"""
from datetime import datetime
from app import db


class Customer(db.Model):
    """客户模型"""
    __tablename__ = 'customer'
    
    id = db.Column(db.Integer, primary_key=True)
    customer_code = db.Column(db.String(50), unique=True, index=True, comment='客户编码')
    name = db.Column(db.String(100), unique=True, nullable=False, index=True, comment='客户名称')
    contact = db.Column(db.String(50), nullable=True, comment='联系人')
    phone = db.Column(db.String(20), nullable=True, comment='联系电话')
    address = db.Column(db.String(200), nullable=True, comment='地址')
    note = db.Column(db.Text, nullable=True, comment='备注')
    icon_url = db.Column(db.String(200), nullable=True, comment='客户图标URL')
    status = db.Column(db.Boolean, default=True, comment='是否启用')
    create_time = db.Column(db.DateTime, default=datetime.now, comment='创建时间')
    update_time = db.Column(db.DateTime, default=datetime.now, onupdate=datetime.now, comment='更新时间')
    
    def __repr__(self):
        return f'<Customer {self.name}>'
    
    def to_dict(self):
        """转换为字典"""
        return {
            'id': self.id,
            'customer_code': self.customer_code,
            'name': self.name,
            'contact': self.contact,
            'phone': self.phone,
            'address': self.address,
            'note': self.note,
            'icon_url': self.icon_url,
            'status': self.status,
            'create_time': self.create_time.isoformat() if self.create_time else None,
            'update_time': self.update_time.isoformat() if self.update_time else None
        }
