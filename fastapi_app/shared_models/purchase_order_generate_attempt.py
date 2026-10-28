"""采购单人工生成尝试的持久化幂等登记。"""
from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from fastapi_app.shared_models import Base


class PurchaseOrderGenerateAttempt(Base):
    """按操作者与请求键保存首次生成结果，与采购单写入同事务提交。"""

    __tablename__ = 'purchase_order_generate_attempt'

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    actor_id: Mapped[int] = mapped_column(
        Integer, ForeignKey('user.id'), nullable=False, comment='发起人工生成的用户ID',
    )
    idempotency_key: Mapped[str] = mapped_column(String(64), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    response_body: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
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
        UniqueConstraint(
            'actor_id', 'idempotency_key',
            name='uq_po_generate_attempt_actor_key',
        ),
    )
