"""
权限模型 - 纯 SQLAlchemy 2.0 声明式

映射到与 Flask-SQLAlchemy Permission 相同的 'permission' 表。
"""
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from fastapi_app.shared_models import Base


class Permission(Base):
    """权限模型"""
    __tablename__ = 'permission'

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(50), nullable=False, comment='权限名称')
    code: Mapped[str] = mapped_column(String(50), unique=True, nullable=False, comment='权限标识')
    parent_id: Mapped[int | None] = mapped_column(Integer, ForeignKey('permission.id'), comment='父权限ID')

    icon: Mapped[str | None] = mapped_column(String(50), comment='导航图标')
    url: Mapped[str | None] = mapped_column(String(200), comment='导航链接')
    section: Mapped[str | None] = mapped_column(String(50), comment='所属板块')
    section_name: Mapped[str | None] = mapped_column(String(50), comment='板块显示名')
    sort_order: Mapped[int] = mapped_column(Integer, default=0, comment='排序')
    is_nav: Mapped[bool] = mapped_column(Boolean, default=True, comment='是否显示在导航栏')
    updated_at: Mapped[datetime | None] = mapped_column(DateTime, default=datetime.now, onupdate=datetime.now, comment='更新时间')

    # 自引用关系：与 Flask 端一样使用 remote_side=[id] 指定方向
    parent: Mapped["Permission | None"] = relationship(
        "Permission",
        back_populates="children",
        remote_side="Permission.id",
    )
    children: Mapped[list["Permission"]] = relationship(
        "Permission",
        back_populates="parent",
        foreign_keys="Permission.parent_id",
    )

    def __repr__(self):
        return f'<Permission {self.name}>'
