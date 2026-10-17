"""
产品模型 - 纯 SQLAlchemy 2.0 声明式

映射到 'product' 表。
"""
from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, DateTime, Index, Integer, Numeric, String, desc
from sqlalchemy.orm import Mapped, mapped_column, relationship

from fastapi_app.shared_models import Base

if TYPE_CHECKING:
    from fastapi_app.shared_models.case import Case
    from fastapi_app.shared_models.product_material import (
        ProductAccessory,
        ProductFabric,
        ProductMaterial,
        ProductRole,
    )


class Product(Base):
    """产品模型"""
    __tablename__ = 'product'

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False, unique=True, comment='产品名称')
    barcode: Mapped[str | None] = mapped_column(String(50), index=True, comment='69码/商品条码')
    # 2026-10-17 审计 P2-27：列为 Numeric，注解必须是 Decimal（此前写 float，
    # 与实际运行时类型不符，mypy/IDE 会误推）。
    price: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), default=0, server_default='0', comment='产品价格')
    image: Mapped[str | None] = mapped_column(String(200), comment='产品图片路径')
    factory: Mapped[str | None] = mapped_column(String(50), comment='所属工厂')
    initial_stock: Mapped[int] = mapped_column(Integer, default=0, comment='初始库存')
    current_stock: Mapped[int] = mapped_column(Integer, default=0, comment='当前库存')
    default_bom_label: Mapped[str | None] = mapped_column(String(50), comment='默认BOM自定义名称(NULL=显示"默认BOM")')
    version: Mapped[int] = mapped_column(Integer, default=0, server_default='0', comment='乐观锁版本号')
    create_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC), index=True, comment='创建时间')
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC), onupdate=lambda: datetime.now(UTC), comment='更新时间')


    __table_args__ = (
        Index('idx_product_name_barcode', 'name', 'barcode'),
        Index('idx_product_name_trgm', 'name', postgresql_using='gin',
              postgresql_ops={'name': 'gin_trgm_ops'}),
        Index('idx_product_barcode_trgm', 'barcode', postgresql_using='gin',
              postgresql_ops={'barcode': 'gin_trgm_ops'}),
        Index('idx_perf_product_name_date', desc('create_time'), 'id'),
        # 库存非负兜底（P1-6）：DB 级约束，防止绕过应用层校验的写点落负值；
        # 对应的 Alembic 迁移见 migrations/versions/pg_standalone_061_add_product_stock_check.py
        CheckConstraint('current_stock >= 0', name='ck_product_current_stock_nonneg'),
    )

    # 皮套关联（由 Case 模型 backref 自动创建，此处显式声明以确保类型检查）
    cases: Mapped[list[Case]] = relationship("Case", back_populates="product")

    # BOM 物料关联（lazy="raise" 强制显式 selectinload，避免不需要 BOM 的查询产生 N+1）
    material: Mapped[ProductMaterial | None] = relationship(
        "ProductMaterial", back_populates="product", uselist=False, cascade="all, delete-orphan",
        lazy="raise",
    )
    # 全部填充物行（含各角色 role_id≠NULL 的行）；material 仅为产品级 1:1 兼容视图
    material_rows: Mapped[list[ProductMaterial]] = relationship(
        "ProductMaterial", lazy="raise", viewonly=True,
        foreign_keys="ProductMaterial.product_id",
    )
    fabrics: Mapped[list[ProductFabric]] = relationship(
        "ProductFabric", back_populates="product", cascade="all, delete-orphan",
        lazy="raise",
    )
    accessories: Mapped[list[ProductAccessory]] = relationship(
        "ProductAccessory", back_populates="product", cascade="all, delete-orphan",
        lazy="raise",
    )
    roles: Mapped[list[ProductRole]] = relationship(
        "ProductRole", back_populates="product", cascade="all, delete-orphan",
        lazy="raise",
    )

    def __repr__(self):
        return f'<Product {self.name}>'

    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'barcode': self.barcode,
            'price': float(self.price) if self.price is not None else 0,
            'image': self.image,
            'factory': self.factory,
            'initial_stock': self.initial_stock,
            'current_stock': self.current_stock,
            'create_time': self.create_time.strftime('%Y-%m-%d %H:%M:%S') if self.create_time else None
        }

    def has_bom(self):
        """检查产品是否有BOM数据（含各角色物料行）"""
        has_material = any(
            m.cotton_usage and m.cotton_usage > 0 for m in self.material_rows
        )
        has_fabric = len(self.fabrics) > 0
        has_accessory = len(self.accessories) > 0
        return has_material or has_fabric or has_accessory

    def get_all_materials(self):
        """获取产品所有物料（含各角色的填充物/面料/辅料）"""
        materials = []

        for material in self.material_rows:
            if material.cotton_usage and material.cotton_usage > 0:
                materials.append(material.to_dict())

        for fabric in self.fabrics:
            materials.append(fabric.to_dict())

        for accessory in self.accessories:
            materials.append(accessory.to_dict())

        return materials
