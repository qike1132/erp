"""
审计日志模型 - 记录所有写操作的系统级审计轨迹
与业务领域日志（InventoryLog/OrderStatusLog等）互补，
提供统一的跨域操作审计视图
"""
from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from fastapi_app.shared_models import Base


class AuditLog(Base):
    """系统级审计日志"""
    __tablename__ = 'audit_log'

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # 2026-10-31 索引体检（docs/db-index-analysis-2026-10-31.md）：本表为纯追加
    # 表（audit_middleware 批量写入），无任何 SELECT 查询路径（读方仅备份校验，
    # 走 pkey 全表扫）。此前 user_id/action/resource_type/created_at 的索引与
    # __table_args__ 的 6 个复合索引全部删除：26 万行规模下每次审计 INSERT
    # 白付多次索引维护（9 天窗口 idx_scan 全为 0），模型与库同步删除。
    user_id: Mapped[int | None] = mapped_column(Integer, comment='操作用户ID')
    username: Mapped[str | None] = mapped_column(String(50), comment='操作用户名')
    action: Mapped[str] = mapped_column(String(20), nullable=False, comment='操作类型: CREATE/UPDATE/DELETE/LOGIN/LOGOUT')
    resource_type: Mapped[str] = mapped_column(String(50), nullable=False, comment='资源类型: order/product/user等')
    resource_id: Mapped[str | None] = mapped_column(String(100), comment='资源ID(支持复合ID)')
    detail: Mapped[str | None] = mapped_column(Text, comment='操作详情JSON')
    ip_address: Mapped[str | None] = mapped_column(String(45), comment='客户端IP(v4/v6)')
    user_agent: Mapped[str | None] = mapped_column(String(500), comment='客户端User-Agent')
    request_id: Mapped[str | None] = mapped_column(String(36), comment='请求追踪ID')
    status_code: Mapped[int | None] = mapped_column(Integer, comment='响应状态码')
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False, comment='操作时间',
    )
