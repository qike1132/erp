"""
每日生产记录模型 - 统一三部门（充棉部、手工部、包装部）

替代原先分散的 CraftWork + PackagingRecord，统一记录每日各部门生产数据。
"""
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import Date, DateTime, Index, Integer, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from fastapi_app.core.float_utils import round_money
from fastapi_app.shared_models import Base


class DailyProductionRecord(Base):
    """每日生产记录"""
    __tablename__ = 'daily_production_record'
    __table_args__ = (
        Index('idx_dpr_date', 'production_date'),
        Index('idx_dpr_dept_date', 'department', 'production_date'),
        Index('idx_dpr_barcode', 'barcode'),
        Index('idx_dpr_product_id', 'product_id'),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    department: Mapped[str] = mapped_column(
        String(20), nullable=False,
        comment='部门: filling=充棉部, handcraft=手工部, packaging=包装部'
    )
    product_id: Mapped[int | None] = mapped_column(Integer, nullable=True, comment='关联产品ID')
    product_name: Mapped[str] = mapped_column(String(100), nullable=False, comment='产品名称')
    barcode: Mapped[str] = mapped_column(String(50), nullable=False, default='', comment='69码')
    # 注解用 Decimal 而非 float：列类型是 Numeric(10, 2)，SQLAlchemy 实际返回
    # Decimal。此前标注为 float 与运行时不符（会让 mypy 误判金额运算类型，
    # 也会误导调用方以为可以按浮点处理）。
    unit_price: Mapped[Decimal] = mapped_column(
        Numeric(10, 2), nullable=False, default=0,
        comment='单价（录入时快照）'
    )
    quantity: Mapped[int] = mapped_column(Integer, nullable=False, comment='生产数量')
    production_date: Mapped[datetime] = mapped_column(Date, nullable=False, comment='生产日期')
    remark: Mapped[str | None] = mapped_column(String(500), nullable=True, comment='备注')
    create_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC), comment='创建时间')
    created_by: Mapped[str | None] = mapped_column(String(50), nullable=True, comment='创建人')
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC), onupdate=lambda: datetime.now(UTC), comment='更新时间')

    def to_dict(self, price_fallback: dict[int, Decimal] | None = None):
        # 对外 JSON 输出转 float（JSON 无 Decimal 原生类型）；
        # 两位小数金额在 float 下可精确表示，此处转换不引入误差。
        up = float(self.unit_price or 0)
        if up == 0 and price_fallback and self.product_id and self.product_id in price_fallback:
            up = price_fallback[self.product_id]
        return {
            'id': self.id,
            'department': self.department,
            'product_id': self.product_id,
            'product_name': self.product_name,
            'barcode': self.barcode or '',
            'unit_price': up,
            'quantity': self.quantity,
            'production_value': round_money(up * self.quantity),
            'production_date': self.production_date.isoformat() if self.production_date else '',
            'remark': self.remark or '',
            'create_time': self.create_time.strftime('%Y-%m-%d %H:%M:%S') if self.create_time else '',
            'created_by': self.created_by or '',
        }
