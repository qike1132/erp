"""导入文件指纹登记模型 - 纯 SQLAlchemy 2.0 声明式

映射到 ``import_file_registry`` 表（迁移 pg_standalone_067）。

用途：文件上传型导入的幂等闸门。``UNIQUE (file_hash, import_type)``
在 DB 层原子拦截「完全相同的文件重复导入」——含并发双击（第二个事务
违反唯一约束回滚）。详见 migrations/versions/pg_standalone_067_*.py。
"""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from fastapi_app.shared_models import Base


class ImportFileRegistry(Base):
    """导入文件指纹登记（第 1 层幂等闸门）"""
    __tablename__ = 'import_file_registry'

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    file_hash: Mapped[str] = mapped_column(Text, nullable=False, comment='文件内容 sha256')
    import_type: Mapped[str] = mapped_column(
        Text, nullable=False, comment='导入类型：orders/stockins/stockouts/case_*/products/comprehensive'
    )
    original_filename: Mapped[str] = mapped_column(Text, nullable=False, comment='原始文件名')
    uploaded_by: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey('user.id'), nullable=True, comment='上传用户ID'
    )
    row_total: Mapped[int | None] = mapped_column(Integer, nullable=True, comment='导入行数')
    result_summary: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True, comment='结果摘要')
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
        server_default=func.now(),
    )

    __table_args__ = (
        UniqueConstraint('file_hash', 'import_type', name='uq_import_file'),
        Index('idx_import_registry_type_time', 'import_type', text('created_at DESC')),
    )

    def __repr__(self):
        return f'<ImportFileRegistry {self.import_type}:{self.file_hash[:8]}>'
