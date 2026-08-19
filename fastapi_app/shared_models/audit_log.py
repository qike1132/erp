"""
审计日志模型 - 记录所有写操作的系统级审计轨迹
与业务领域日志（InventoryLog/OrderStatusLog等）互补，
提供统一的跨域操作审计视图
"""
from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import DateTime, Index, Integer, String, Text, desc, text
from sqlalchemy.orm import Mapped, mapped_column

from fastapi_app.shared_models import Base


class AuditLog(Base):
    """系统级审计日志"""
    __tablename__ = 'audit_log'

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int | None] = mapped_column(Integer, index=True, comment='操作用户ID')
    username: Mapped[str | None] = mapped_column(String(50), comment='操作用户名')
    action: Mapped[str] = mapped_column(String(20), nullable=False, index=True, comment='操作类型: CREATE/UPDATE/DELETE/LOGIN/LOGOUT')
    resource_type: Mapped[str] = mapped_column(String(50), nullable=False, index=True, comment='资源类型: order/product/user等')
    resource_id: Mapped[str | None] = mapped_column(String(100), comment='资源ID(支持复合ID)')
    detail: Mapped[str | None] = mapped_column(Text, comment='操作详情JSON')
    ip_address: Mapped[str | None] = mapped_column(String(45), comment='客户端IP(v4/v6)')
    user_agent: Mapped[str | None] = mapped_column(String(500), comment='客户端User-Agent')
    request_id: Mapped[str | None] = mapped_column(String(36), comment='请求追踪ID')
    status_code: Mapped[int | None] = mapped_column(Integer, comment='响应状态码')
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False, index=True, comment='操作时间',
    )

    __table_args__ = (
        Index('idx_audit_user_action', 'user_id', 'action'),
        Index('idx_audit_resource', 'resource_type', 'resource_id'),
        Index('idx_audit_action_date', 'action', 'created_at'),
        Index('idx_audit_created_desc', desc('created_at')),
        Index('idx_audit_resource_date', 'resource_type', desc('created_at')),
        Index('idx_audit_not_login', desc('created_at'),
              postgresql_where=text("action != 'LOGIN'")),
    )
