"""
版师模型 - 纯 SQLAlchemy 2.0 声明式

映射到 'pattern_maker' 表。
版师为板房打样（/pattern-room）模块的分类维度，替代原「客户」。
"""
from datetime import UTC, datetime

from sqlalchemy import DateTime, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from fastapi_app.shared_models import Base


class PatternMaker(Base):
    """版师模型"""
    __tablename__ = 'pattern_maker'

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False, comment='版师姓名')
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        nullable=False,
        comment='创建时间',
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
        nullable=False,
        comment='更新时间',
    )

    __table_args__ = (
        # pg_trgm GIN 索引：使 ILIKE '%keyword%' 走索引
        Index('idx_pattern_maker_name_trgm', 'name', postgresql_using='gin',
              postgresql_ops={'name': 'gin_trgm_ops'}),
    )

    def __repr__(self):
        return f'<PatternMaker {self.name}>'

    def to_dict(self) -> dict:
        return {
            'id': self.id,
            'name': self.name,
            'created_at': self.created_at.strftime('%Y-%m-%d %H:%M:%S') if self.created_at else '',
            'updated_at': self.updated_at.strftime('%Y-%m-%d %H:%M:%S') if self.updated_at else '',
        }
