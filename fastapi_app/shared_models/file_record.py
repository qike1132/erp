"""
文件元数据模型

P2-1：static/uploads 迁移至 MinIO/S3 后，数据库仅保存文件元数据，
实际二进制数据存放在对象存储或本地文件系统中。
"""
from datetime import UTC, datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from fastapi_app.shared_models import Base


class FileRecord(Base):
    """上传文件元数据表"""
    __tablename__ = 'file_records'

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    original_filename: Mapped[str] = mapped_column(String(255), nullable=False, comment='原始文件名')
    storage_key: Mapped[str] = mapped_column(String(255), nullable=False, comment='对象存储 key 或本地相对路径')
    bucket: Mapped[str] = mapped_column(String(64), nullable=False, default='erp-uploads', comment='对象存储 bucket')
    storage_type: Mapped[str] = mapped_column(String(20), nullable=False, default='local', comment='存储后端: local/s3')
    size: Mapped[int] = mapped_column(Integer, nullable=False, default=0, comment='文件大小(字节)')
    content_type: Mapped[str | None] = mapped_column(String(128), nullable=True, comment='文件 MIME 类型')
    uploader_id: Mapped[int | None] = mapped_column(Integer, ForeignKey('user.id'), nullable=True, comment='上传用户ID')
    extra: Mapped[str | None] = mapped_column(Text, nullable=True, comment='额外 JSON 元数据')
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        comment='创建时间',
    )

    __table_args__ = (
        Index('idx_file_record_uploader', 'uploader_id'),
        Index('idx_file_record_storage_key', 'storage_key'),
        Index('idx_file_record_created_at', 'created_at'),
    )

    def __repr__(self):
        return f'<FileRecord {self.id} {self.original_filename}>'
