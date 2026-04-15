"""
皮套库存日志模型
"""
from datetime import datetime
from app import db


class CaseInventoryLog(db.Model):
    """皮套库存日志模型"""
    __tablename__ = 'case_inventory_log'
    
    id = db.Column(db.Integer, primary_key=True)
    case_id = db.Column(db.Integer, db.ForeignKey('case.id', ondelete='CASCADE'), nullable=False, index=True, comment='皮套ID')
    change_type = db.Column(db.String(20), nullable=False, index=True, comment='变化类型：入库、出库、入库调整、出库调整、删除入库、删除出库')
    change_quantity = db.Column(db.Integer, nullable=False, comment='变化数量（正数为增加，负数为减少）')
    change_date = db.Column(db.DateTime, default=datetime.now, index=True, comment='变化时间')
    related_id = db.Column(db.String(50), comment='关联单据编号')
    note = db.Column(db.Text, comment='备注')
    customer = db.Column(db.String(100), nullable=True, index=True, comment='客户名称')
    
    case = db.relationship('Case', backref=db.backref('inventory_logs', lazy=True))

    __table_args__ = (
        db.Index('idx_case_inventory_log_case_date', 'case_id', db.desc('change_date')),
    )

    def __repr__(self):
        return f'<CaseInventoryLog {self.id}>'
