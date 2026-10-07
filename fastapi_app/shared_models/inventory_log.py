"""
库存日志模型 - 纯 SQLAlchemy 2.0 声明式

映射到 'inventory_log' 表。
"""
from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, desc, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from fastapi_app.shared_models import Base

if TYPE_CHECKING:
    from fastapi_app.shared_models.product import Product


class InventoryLog(Base):
    """库存日志模型"""
    __tablename__ = 'inventory_log'

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # R1（迁移 073）：外键由 CASCADE 改 SET NULL —— 产品删除不得抹掉库存流水。
    # 产品删除后 product_id 置空，历史靠 product_name/product_barcode 快照仍可读
    # （口径与 ERPNext 的 item_code 软引用、InvenTree 保留 tracking 记录一致）。
    product_id: Mapped[int | None] = mapped_column(Integer, ForeignKey('product.id', ondelete='SET NULL'), nullable=True, index=True, comment='产品ID（产品删除后置空，历史保留）')
    # 产品标识快照：写入时由调用方带出（多数写点已持有锁内 Product 对象），
    # product_service.delete_product 在删除前对存量流水统一补写，双保险。
    product_name: Mapped[str | None] = mapped_column(String(100), comment='产品名称快照（产品删除后仍可读）')
    product_barcode: Mapped[str | None] = mapped_column(String(50), comment='产品条码快照')
    change_type: Mapped[str] = mapped_column(String(20), nullable=False, index=True, comment='变化类型')
    change_quantity: Mapped[int] = mapped_column(Integer, nullable=False, comment='变化数量')
    change_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC), index=True, comment='变化时间')
    # 记账时序结存：反映**提交顺序**，不是业务单据日期顺序（change_date 为系统时刻，
    # 单据日期可由用户回溯填写）。ERPNext 的 qty_after_transaction 在并发/回溯下算错
    # （frappe/erpnext#51562）正是因为它用「此前流水 SUM」推导；本仓一律在行锁内
    # 由写入口返回的 current_stock 反推，禁止改用 SELECT 反查。
    quantity_before: Mapped[int | None] = mapped_column(Integer, comment='变动前库存（记账时序；历史行为 NULL）')
    quantity_after: Mapped[int | None] = mapped_column(Integer, comment='变动后库存（记账时序；历史行为 NULL）')
    operator_id: Mapped[int | None] = mapped_column(Integer, ForeignKey('user.id', ondelete='SET NULL'), nullable=True, index=True, comment='操作人ID（产品/脚本路径为 NULL）')
    # VARCHAR(500)（迁移 074）：出库 FIFO 多单把多条 stock_out.id 逗号拼接写入，
    # 5 位数 id 约 9 条即超 50 字符 → StringDataRightTruncation → 正常出货 500。
    # related_id 无索引，加宽为元数据级变更（与 067 提 idem_key 同范式）。
    related_id: Mapped[str | None] = mapped_column(String(500), comment='关联单据编号（出库 FIFO 多单为逗号拼接的 stock_out.id 串）')
    idem_key: Mapped[str | None] = mapped_column(Text, comment='导入幂等键（部分唯一索引 uq_inventory_log_idem；手工路径留空）')
    note: Mapped[str | None] = mapped_column(Text, comment='备注')
    customer: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True, comment='客户名称')
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC), onupdate=lambda: datetime.now(UTC), comment='更新时间')

    product: Mapped[Product | None] = relationship('Product', backref='inventory_logs')
    # 刻意不声明 operator 关系：查询层显式 LEFT JOIN user 取 username/姓名列即可，
    # 避免引入默认 lazy 加载带来的 N+1（本仓其它模型对非必需关系用 lazy="raise" 收紧）。

    __table_args__ = (
        Index('idx_inventory_log_product_date', 'product_id', desc('change_date')),
        Index(
            'uq_inventory_log_idem',
            'idem_key',
            unique=True,
            postgresql_where=text('idem_key IS NOT NULL'),
        ),
    )

    def __repr__(self):
        return f'<InventoryLog {self.id}>'
