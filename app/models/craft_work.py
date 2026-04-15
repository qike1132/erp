"""手工部生产记录模型"""
from datetime import datetime
from app import db


class CraftWork(db.Model):
    """手工部生产记录"""
    __tablename__ = 'craft_work'

    id = db.Column(db.Integer, primary_key=True)
    worker_name = db.Column(db.String(50), nullable=False, comment='工人姓名')
    quantity = db.Column(db.Integer, nullable=False, comment='生产数量')
    work_date = db.Column(db.Date, nullable=False, comment='生产日期')
    remark = db.Column(db.String(500), nullable=True, comment='备注')
    create_time = db.Column(db.DateTime, default=datetime.now, comment='创建时间')
    created_by = db.Column(db.String(50), nullable=True, comment='创建人')

    __table_args__ = (
        db.Index('idx_craft_work_date', 'work_date'),
        db.Index('idx_craft_work_worker_date', 'worker_name', 'work_date'),
    )

    def to_dict(self):
        return {
            'id': self.id,
            'worker_name': self.worker_name,
            'quantity': self.quantity,
            'work_date': self.work_date.isoformat() if self.work_date else '',
            'remark': self.remark or '',
            'create_time': self.create_time.strftime('%Y-%m-%d %H:%M:%S') if self.create_time else '',
            'created_by': self.created_by or '',
        }
