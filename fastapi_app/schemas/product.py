"""
产品管理 Pydantic 数据模型

用于产品 CRUD 的请求/响应模型。
"""
from datetime import datetime

from pydantic import BaseModel, Field, field_validator

from utils.sanitizer import sanitize_url

# 允许的工厂选项（与前端下拉框保持一致）
VALID_FACTORIES = ('东莞', '湖北')


def _validate_factory(v: str | None) -> str | None:
    """校验工厂值必须属于允许的选项集合，允许为空"""
    if v and v not in VALID_FACTORIES:
        raise ValueError(f'工厂值无效，必须是 {"/".join(VALID_FACTORIES)} 之一')
    return v


class ProductCreate(BaseModel):
    """创建产品请求"""
    name: str = Field(..., min_length=1, max_length=100, description="产品名称")
    barcode: str | None = Field(None, max_length=50, description="69码/商品条码")
    price: float | None = Field(None, ge=0, description="产品价格")
    image: str | None = Field(None, max_length=200, description="产品图片路径")
    factory: str | None = Field(None, max_length=50, description="所属工厂")
    initial_stock: int = Field(0, ge=0, le=100000, description="初始库存")

    @field_validator('image')
    @classmethod
    def sanitize_image_url(cls, v: str | None) -> str | None:
        if v:
            sanitized = sanitize_url(v)
            if not sanitized:
                raise ValueError('图片URL包含不安全的协议')
            return sanitized
        return v

    @field_validator('factory')
    @classmethod
    def validate_factory(cls, v: str | None) -> str | None:
        return _validate_factory(v)


class ProductUpdate(BaseModel):
    """更新产品请求"""
    name: str | None = Field(None, min_length=1, max_length=100, description="产品名称")
    barcode: str | None = Field(None, max_length=50, description="69码/商品条码")
    price: float | None = Field(None, ge=0, description="产品价格")
    image: str | None = Field(None, max_length=200, description="产品图片路径")
    factory: str | None = Field(None, max_length=50, description="所属工厂")
    initial_stock: int | None = Field(None, ge=0, le=100000, description="初始库存")

    @field_validator('image')
    @classmethod
    def sanitize_image_url(cls, v: str | None) -> str | None:
        if v:
            sanitized = sanitize_url(v)
            if not sanitized:
                raise ValueError('图片URL包含不安全的协议')
            return sanitized
        return v

    @field_validator('factory')
    @classmethod
    def validate_factory(cls, v: str | None) -> str | None:
        return _validate_factory(v)


class ProductResponse(BaseModel):
    """产品响应"""
    id: int
    name: str
    barcode: str | None = None
    price: float | None = 0
    image: str | None = None
    factory: str | None = None
    initial_stock: int
    current_stock: int
    create_time: datetime | str | None = None

    class Config:
        from_attributes = True


class ProductListResponse(BaseModel):
    """产品列表响应"""
    success: bool = True
    items: list[dict]
    total: int = 0


class ProductActionResponse(BaseModel):
    """产品操作响应"""
    success: bool
    message: str


class ProductSearchItem(BaseModel):
    """产品搜索结果项"""
    id: int
    name: str
    barcode: str | None = None
    price: float | None = 0
    current_stock: int = 0


class ProductStockInfo(BaseModel):
    """产品库存信息"""
    product_id: int
    name: str
    current_stock: int
    available_stock: int
