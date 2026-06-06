"""
修改日志 & 保存查询模型 - 纯 SQLAlchemy 2.0 声明式

映射到与 Flask-SQLAlchemy 相同的表。
"""
from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from fastapi_app.shared_models import Base


class ModificationLog(Base):
    """修改日志表"""
    __tablename__ = 'modification_log'

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    target_type: Mapped[str] = mapped_column(String(50), nullable=False, index=True, comment='目标类型: purchase_order/purchase_order_item/material')
    target_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True, comment='目标ID')
    field_name: Mapped[str] = mapped_column(String(100), nullable=False, comment='字段名称')
    old_value: Mapped[str | None] = mapped_column(Text, comment='修改前值')
    new_value: Mapped[str | None] = mapped_column(Text, comment='修改后值')
    modifier_id: Mapped[int | None] = mapped_column(Integer, ForeignKey('user.id'), comment='修改人ID')
    modifier_name: Mapped[str | None] = mapped_column(String(100), comment='修改人姓名')
    modify_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), index=True, comment='修改时间')
    modify_reason: Mapped[str | None] = mapped_column(Text, comment='修改原因')
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), comment='更新时间')

    __table_args__ = (
        Index('idx_mod_target', 'target_type', 'target_id'),
        Index('idx_mod_time', 'modify_time'),
        Index('idx_modification_log_modifier', 'modifier_id'),
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


class SavedQuery(Base):
    """保存的查询条件表"""
    __tablename__ = 'saved_query'

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False, comment='查询名称')
    query_type: Mapped[str] = mapped_column(String(50), nullable=False, index=True, comment='查询类型: purchase_order/material')
    conditions: Mapped[str] = mapped_column(Text, nullable=False, comment='查询条件JSON')
    creator_id: Mapped[int | None] = mapped_column(Integer, ForeignKey('user.id'), comment='创建人ID')
    creator_name: Mapped[str | None] = mapped_column(String(100), comment='创建人姓名')
    create_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), comment='创建时间')
    use_count: Mapped[int | None] = mapped_column(Integer, default=0, comment='使用次数')
    last_use_time: Mapped[datetime | None] = mapped_column(DateTime, comment='最后使用时间')
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), comment='更新时间')

    __table_args__ = (
        Index('idx_saved_query_type', 'query_type'),
        Index('idx_saved_query_creator', 'creator_id'),
    )

    def to_dict(self):
        import json
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
