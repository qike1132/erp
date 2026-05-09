"""
App版本管理模型 - 纯 SQLAlchemy 2.0 声明式
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from fastapi_app.shared_models import Base


class AppVersion(Base):
    __tablename__ = 'app_version'

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    platform: Mapped[str] = mapped_column(String(20), nullable=False, default='android', comment='平台: android/ios')
    version_code: Mapped[int] = mapped_column(Integer, nullable=False, index=True, comment='整数版本号（用于对比）')
    version_name: Mapped[str] = mapped_column(String(50), nullable=False, comment='显示版本号，如 1.0.1')
    download_url: Mapped[str] = mapped_column(String(500), nullable=False, comment='APK下载地址（相对路径或完整URL）')
    changelog: Mapped[str | None] = mapped_column(Text, comment='更新日志')
    file_size: Mapped[int | None] = mapped_column(Integer, comment='文件大小（字节）')
    md5_hash: Mapped[str | None] = mapped_column(String(64), comment='MD5校验值')
    force_update: Mapped[bool] = mapped_column(Boolean, default=False, server_default='0', comment='是否强制更新')
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default='1', comment='是否当前有效版本')
    pushed: Mapped[bool] = mapped_column(Boolean, default=False, server_default='0', comment='是否已推送FCM通知')
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, comment='创建时间')
    updated_at: Mapped[datetime | None] = mapped_column(DateTime, default=datetime.now, onupdate=datetime.now, comment='更新时间')

    def __repr__(self):
        return f'<AppVersion {self.platform} v{self.version_name}({self.version_code})>'

    def to_dict(self):
        return {
            'id': self.id,
            'platform': self.platform,
            'version_code': self.version_code,
            'version_name': self.version_name,
            'download_url': self.download_url,
            'changelog': self.changelog,
            'file_size': self.file_size,
            'md5_hash': self.md5_hash,
            'force_update': self.force_update,
            'is_active': self.is_active,
            'pushed': self.pushed,
            'created_at': self.created_at.strftime('%Y-%m-%d %H:%M:%S') if self.created_at else None,
        }
