"""订单创建的请求级幂等登记（POST /orders/create 重试防护）。"""
from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from fastapi_app.shared_models import Base


class OrderCreateAttempt(Base):
    """按操作者与请求键保存首次下单结果，与订单写入同事务提交。

    为什么需要它：下单路径每次都会 generate_order_number()，客户端超时重试
    必然拿到新单号、建出第二张单（无键可比对）。机制照搬采购单人工生成
    （PurchaseOrderGenerateAttempt）：同一 actor + 同一 Idempotency-Key 只落
    一行，首次成功后把响应体存进 response_body，后续同键同指纹的请求直接重放。
    """

    __tablename__ = 'order_create_attempt'

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    actor_id: Mapped[int] = mapped_column(
        Integer, ForeignKey('user.id'), nullable=False, comment='发起下单的用户ID',
    )
    idempotency_key: Mapped[str] = mapped_column(
        String(64), nullable=False, comment='客户端幂等键（Idempotency-Key 头）',
    )
    request_hash: Mapped[str] = mapped_column(
        String(64), nullable=False, comment='下单内容指纹（同键不同内容即 409）',
    )
    response_body: Mapped[dict | None] = mapped_column(
        JSONB, nullable=True, comment='首次成功响应体（重放用）',
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
        default=lambda: datetime.now(UTC), server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
        default=lambda: datetime.now(UTC), onupdate=lambda: datetime.now(UTC),
        server_default=func.now(),
    )

    __table_args__ = (
        # 同一个人同一把键只能有一条登记：并发重试在这里撞唯一约束，
        # 而不是靠应用层「先查后插」的竞态。
        UniqueConstraint(
            'actor_id', 'idempotency_key',
            name='uq_order_create_attempt_actor_key',
        ),
        # 键有过期语义（历史键需按时间裁剪），清理脚本按 created_at 扫，避免全表。
        Index('idx_order_create_attempt_created_at', 'created_at'),
    )
