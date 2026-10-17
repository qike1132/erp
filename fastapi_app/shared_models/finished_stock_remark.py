"""成品库存备注模型 — 按 (客户, 产品, 批次) 一行一条

页面级自由文本备注，独立于包装记录（packaging_record / daily_production_record）
的 remark：那一侧是生产录入时写的，本表是成品库存页自己维护的。
一行 = 成品库存页的一个聚合行，故键与聚合口径一致：
(customer_name, product_id, batch_no)；batch_no 空串 = 未分批次行。
"""
from datetime import UTC, datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from fastapi_app.shared_models import Base


class FinishedStockRemark(Base):
    """成品库存备注"""
    __tablename__ = 'finished_stock_remark'
    __table_args__ = (
        # UPSERT 的落点：同名 (客户,产品,批次) 只有一行；空批次的未分批次行也由空串参与唯一
        Index('uq_fs_remark_cust_prod_batch', 'customer_name', 'product_id', 'batch_no', unique=True),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    customer_name: Mapped[str] = mapped_column(String(100), nullable=False, default='', server_default='', comment='客户名称（与聚合行展示值一致；空=未指定客户）')
    product_id: Mapped[int] = mapped_column(Integer, ForeignKey('product.id', ondelete='CASCADE'), nullable=False, comment='产品ID')
    batch_no: Mapped[str] = mapped_column(String(100), nullable=False, default='', server_default='', comment='批次号（空串=未分批次）')
    remark: Mapped[str] = mapped_column(Text, nullable=False, default='', server_default='', comment='备注内容')
    create_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC), comment='创建时间')
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC), onupdate=lambda: datetime.now(UTC), comment='更新时间')
