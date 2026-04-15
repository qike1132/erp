"""SKU批次管理模型（Flask-SQLAlchemy）"""
from app import db


class SkuBatch(db.Model):
    """SKU批次表"""
    __tablename__ = 'sku_batch'

    id = db.Column(db.Integer, primary_key=True)
    sku_code = db.Column(db.String(50), nullable=False, index=True, comment='SKU编号')
    batch_no = db.Column(db.String(50), nullable=False, index=True, comment='批次号')
    status = db.Column(db.String(20), default='active', comment='批次状态: active-在用, frozen-冻结, expired-过期')
    quantity = db.Column(db.Numeric(12, 2), default=0, comment='批次数量')
    remark = db.Column(db.String(200), comment='备注')
    create_time = db.Column(db.DateTime, default=db.func.now(), index=True, comment='批次创建时间')
    update_time = db.Column(db.DateTime, default=db.func.now(), onupdate=db.func.now(), comment='更新时间')

    def to_dict(self):
        return {
            'id': self.id,
            'sku_code': self.sku_code,
            'batch_no': self.batch_no,
            'status': self.status,
            'quantity': float(self.quantity or 0),
            'remark': self.remark or '',
            'create_time': self.create_time.strftime('%Y-%m-%d %H:%M:%S') if self.create_time else '',
            'update_time': self.update_time.strftime('%Y-%m-%d %H:%M:%S') if self.update_time else '',
        }
