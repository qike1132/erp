"""
用户模型 - 纯 SQLAlchemy 2.0 声明式

映射到与 Flask-SQLAlchemy User 相同的 'user' 表。
列名必须与 Flask 模型完全一致。
"""
from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String, Table
from sqlalchemy.orm import Mapped, mapped_column, relationship

from fastapi_app.shared_models import Base

# 用户-权限多对多关联表（与 Flask 端映射同一张表）
user_permission = Table(
    'user_permission',
    Base.metadata,
    Column('user_id', Integer, ForeignKey('user.id'), primary_key=True),
    Column('permission_id', Integer, ForeignKey('permission.id'), primary_key=True),
)


class User(Base):
    """用户模型"""
    __tablename__ = 'user'

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(50), unique=True, nullable=False, comment='用户名')
    phone: Mapped[str | None] = mapped_column(String(20), comment='手机号')
    password: Mapped[str] = mapped_column(String(200), nullable=False, comment='密码')
    is_super: Mapped[bool] = mapped_column(Boolean, default=False, comment='是否超级用户')
    status: Mapped[bool] = mapped_column(Boolean, default=True, comment='是否启用')
    create_time: Mapped[datetime | None] = mapped_column(DateTime, default=datetime.now, comment='创建时间')
    update_time: Mapped[datetime | None] = mapped_column(DateTime, default=datetime.now, onupdate=datetime.now, comment='更新时间')

    permissions: Mapped[list["Permission"]] = relationship('Permission', secondary=user_permission, backref='users')

    def has_permission(self, permission_code: str) -> bool:
        """检查用户是否拥有指定权限（与 Flask 端逻辑一致）"""
        SENSITIVE_PREFIXES = ['user_']

        for prefix in SENSITIVE_PREFIXES:
            if permission_code.startswith(prefix):
                return self.is_super

        if self.is_super:
            return True

        for p in self.permissions:
            if p.code == permission_code:
                return True
            if p.children:
                for child in p.children:
                    if child.code == permission_code:
                        return True
            if p.parent_id is None and permission_code.startswith(p.code.split('_')[0] + '_'):
                return True

        return False

    def __repr__(self):
        return f'<User {self.username}>'
