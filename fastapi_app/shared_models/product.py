"""
产品模型 - 纯 SQLAlchemy 2.0 声明式

映射到与 Flask-SQLAlchemy Product 相同的 'product' 表。
"""
from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, Index, Integer, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from fastapi_app.shared_models import Base

if TYPE_CHECKING:
    from fastapi_app.shared_models.case import Case
    from fastapi_app.shared_models.product_material import (
        ProductAccessory,
        ProductFabric,
        ProductMaterial,
        ProductPackaging,
    )


class Product(Base):
    """产品模型"""
    __tablename__ = 'product'

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False, unique=True, index=True, comment='产品名称')
    barcode: Mapped[str | None] = mapped_column(String(50), index=True, comment='69码/商品条码')
    price: Mapped[float | None] = mapped_column(Numeric(10, 2), default=0, server_default='0', comment='产品价格')
    image: Mapped[str | None] = mapped_column(String(200), comment='产品图片路径')
    initial_stock: Mapped[int] = mapped_column(Integer, default=0, comment='初始库存')
    current_stock: Mapped[int] = mapped_column(Integer, default=0, comment='当前库存')
    version: Mapped[int] = mapped_column(Integer, default=0, server_default='0', comment='乐观锁版本号')
    create_time: Mapped[datetime | None] = mapped_column(DateTime, default=datetime.now, index=True, comment='创建时间')

    __table_args__ = (
        Index('idx_product_name_barcode', 'name', 'barcode'),
        # pg_trgm GIN 索引：使 ILIKE '%keyword%' 和 % 运算符走索引
        Index('idx_product_name_trgm', 'name', postgresql_using='gin',
              postgresql_ops={'name': 'gin_trgm_ops'}),
        Index('idx_product_barcode_trgm', 'barcode', postgresql_using='gin',
              postgresql_ops={'barcode': 'gin_trgm_ops'}),
    )

    # 皮套关联（由 Case 模型 backref 自动创建，此处显式声明以确保类型检查）
    cases: Mapped[list["Case"]] = relationship("Case", back_populates="product")

    # BOM 物料关联
    material: Mapped["ProductMaterial | None"] = relationship(
        "ProductMaterial", back_populates="product", uselist=False, cascade="all, delete-orphan"
    )
    fabrics: Mapped[list["ProductFabric"]] = relationship(
        "ProductFabric", back_populates="product", cascade="all, delete-orphan"
    )
    accessories: Mapped[list["ProductAccessory"]] = relationship(
        "ProductAccessory", back_populates="product", cascade="all, delete-orphan"
    )
    packagings: Mapped[list["ProductPackaging"]] = relationship(
        "ProductPackaging", back_populates="product", cascade="all, delete-orphan"
    )

    def __repr__(self):
        return f'<Product {self.name}>'

    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'barcode': self.barcode,
            'price': float(self.price) if self.price else 0,
            'image': self.image,
            'initial_stock': self.initial_stock,
            'current_stock': self.current_stock,
            'create_time': self.create_time.strftime('%Y-%m-%d %H:%M:%S') if self.create_time else None
        }

    def has_bom(self):
        """检查产品是否有BOM数据"""
        has_material = self.material and self.material.cotton_usage and self.material.cotton_usage > 0
        has_fabric = len(self.fabrics) > 0
        has_accessory = len(self.accessories) > 0
        has_packaging = len(self.packagings) > 0
        return has_material or has_fabric or has_accessory or has_packaging

    def get_all_materials(self):
        """获取产品所有物料（包括填充物、面料、辅料、包装）"""
        materials = []

        if self.material and self.material.cotton_usage and self.material.cotton_usage > 0:
            materials.append(self.material.to_dict())

        for fabric in self.fabrics:
            materials.append(fabric.to_dict())

        for accessory in self.accessories:
            materials.append(accessory.to_dict())

        for packaging in self.packagings:
            materials.append(packaging.to_dict())

        return materials
