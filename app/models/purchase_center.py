"""
采购中心辅助模型
包含修改历史、保存查询
"""
from datetime import datetime
from app import db
import json


class ModificationLog(db.Model):
    """修改历史记录"""
    __tablename__ = 'modification_log'

    id = db.Column(db.Integer, primary_key=True)
    target_type = db.Column(db.String(50), nullable=False, index=True, comment='目标类型: purchase_order/purchase_order_item/material')
    target_id = db.Column(db.Integer, nullable=False, index=True, comment='目标ID')
    field_name = db.Column(db.String(100), nullable=False, comment='字段名称')
    old_value = db.Column(db.Text, comment='修改前值')
    new_value = db.Column(db.Text, comment='修改后值')
    modifier_id = db.Column(db.Integer, db.ForeignKey('user.id'), comment='修改人ID')
    modifier_name = db.Column(db.String(100), comment='修改人姓名')
    modify_time = db.Column(db.DateTime, default=datetime.now, index=True, comment='修改时间')
    modify_reason = db.Column(db.Text, comment='修改原因')

    __table_args__ = (
        db.Index('idx_mod_target', 'target_type', 'target_id'),
        db.Index('idx_mod_time', 'modify_time'),
    )

    def to_dict(self):
        return {
            'id': self.id,
            'target_type': self.target_type,
            'target_id': self.target_id,
            'field_name': self.field_name,
            'old_value': self.old_value,
            'new_value': self.new_value,
            'modifier_id': self.modifier_id,
            'modifier_name': self.modifier_name,
            'modify_time': self.modify_time.strftime('%Y-%m-%d %H:%M:%S') if self.modify_time else None,
            'modify_reason': self.modify_reason,
        }


class SavedQuery(db.Model):
    """保存查询条件"""
    __tablename__ = 'saved_query'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False, comment='查询名称')
    query_type = db.Column(db.String(50), nullable=False, index=True, comment='查询类型: purchase_order/material')
    conditions = db.Column(db.Text, nullable=False, comment='查询条件JSON')
    creator_id = db.Column(db.Integer, db.ForeignKey('user.id'), comment='创建人ID')
    creator_name = db.Column(db.String(100), comment='创建人姓名')
    create_time = db.Column(db.DateTime, default=datetime.now, comment='创建时间')
    use_count = db.Column(db.Integer, default=0, comment='使用次数')
    last_use_time = db.Column(db.DateTime, comment='最后使用时间')

    __table_args__ = (
        db.Index('idx_saved_query_type', 'query_type'),
        db.Index('idx_saved_query_creator', 'creator_id'),
    )

    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'query_type': self.query_type,
            'conditions': json.loads(self.conditions) if self.conditions else None,
            'creator_id': self.creator_id,
            'creator_name': self.creator_name,
            'create_time': self.create_time.strftime('%Y-%m-%d %H:%M:%S') if self.create_time else None,
            'use_count': self.use_count,
            'last_use_time': self.last_use_time.strftime('%Y-%m-%d %H:%M:%S') if self.last_use_time else None,
        }
