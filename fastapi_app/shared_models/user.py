"""
用户模型 - 纯 SQLAlchemy 2.0 声明式

映射到 'user' 表。
"""
from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String, Table
from sqlalchemy.orm import Mapped, mapped_column, relationship

from fastapi_app.shared_models import Base

if TYPE_CHECKING:
    from fastapi_app.shared_models.permission import Permission

# 用户-权限多对多关联表
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
    factory: Mapped[str | None] = mapped_column(String(20), nullable=True, comment='所属工厂：东莞/湖北/NULL')
    create_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC), comment='创建时间')
    update_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC), onupdate=lambda: datetime.now(UTC), comment='更新时间')

    permissions: Mapped[list[Permission]] = relationship('Permission', secondary=user_permission, backref='users')

    def has_permission(self, permission_code: str) -> bool:
        """检查用户是否拥有指定权限

        权限继承规则：
        - user_ 前缀的敏感权限仅超级管理员可访问
        - 超级管理员拥有所有权限
        - 拥有 xxx_manage 顶级管理权限时，自动拥有 xxx_view 查看权限
          （manage 是 view 的超集，避免业务页面因缺少 view 权限被阻断）
        - 例外：NO_MANAGE_INHERIT 中的业务子码**必须显式授权**，manage 不放行。
          背景（第十一轮落地分析）：outsource_ship / outsource_receive 是外发
          发货/收货的职责分离码（迁移 043 刻意按用户名回填授权以落实四眼原则），
          若允许持 outsource_manage 者经 children 继承同时通过两端，则该设计被绕过。
        """
        SENSITIVE_PREFIXES = ['user_']

        # manage 不得经继承放行的业务子码（须逐个显式授权）
        NO_MANAGE_INHERIT = {'outsource_ship', 'outsource_receive'}

        for prefix in SENSITIVE_PREFIXES:
            if permission_code.startswith(prefix):
                return self.is_super

        if self.is_super:
            return True

        for p in self.permissions:
            if p.code == permission_code:
                return True
            if p.children and permission_code not in NO_MANAGE_INHERIT:
                for child in p.children:
                    if child.code == permission_code:
                        return True
            # 拥有顶级 xxx_manage 权限时，自动通过 xxx_view 检查
            if (
                p.parent_id is None
                and p.code.endswith('_manage')
                and permission_code == p.code.rsplit('_', 1)[0] + '_view'
            ):
                return True

        return False

    def __repr__(self):
        return f'<User {self.username}>'
