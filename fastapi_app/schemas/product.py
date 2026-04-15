"""
产品管理 Pydantic 数据模型

用于产品 CRUD 的请求/响应模型。
"""
from pydantic import BaseModel, Field
from typing import Optional, List


class ProductCreate(BaseModel):
    """创建产品请求"""
    name: str = Field(..., min_length=1, max_length=100, description="产品名称")
    barcode: Optional[str] = Field(None, max_length=50, description="69码/商品条码")
    price: Optional[float] = Field(None, ge=0, description="产品价格")
    image: Optional[str] = Field(None, max_length=200, description="产品图片路径")
    initial_stock: int = Field(0, ge=0, le=100000, description="初始库存")


class ProductUpdate(BaseModel):
    """更新产品请求"""
    name: Optional[str] = Field(None, min_length=1, max_length=100, description="产品名称")
    barcode: Optional[str] = Field(None, max_length=50, description="69码/商品条码")
    price: Optional[float] = Field(None, ge=0, description="产品价格")
    image: Optional[str] = Field(None, max_length=200, description="产品图片路径")
    initial_stock: Optional[int] = Field(None, ge=0, le=100000, description="初始库存")


class ProductResponse(BaseModel):
    """产品响应"""
    id: int
    name: str
    barcode: Optional[str] = None
    price: Optional[float] = 0
    image: Optional[str] = None
    initial_stock: int
    current_stock: int
    create_time: Optional[str] = None

    class Config:
        from_attributes = True


class ProductListResponse(BaseModel):
    """产品列表响应"""
    success: bool = True
    data: List[dict]
    total: int = 0


class ProductActionResponse(BaseModel):
    """产品操作响应"""
    success: bool
    message: str


class ProductSearchItem(BaseModel):
    """产品搜索结果项"""
    id: int
    name: str
    barcode: Optional[str] = None
    price: Optional[float] = 0
    current_stock: int = 0


class ProductStockInfo(BaseModel):
    """产品库存信息"""
    product_id: int
    name: str
    current_stock: int
    available_stock: int
