"""
库存管理 Pydantic 数据模型

用于入库、出库、库存查看的请求/响应模型。
"""
from datetime import datetime

from pydantic import BaseModel, Field, field_validator


def _validate_date_format(v: str) -> str:
    """验证日期格式为 YYYY-MM-DD"""
    if v is not None:
        datetime.strptime(v, '%Y-%m-%d')
    return v


# ==================== 入库 ====================

class StockInCreate(BaseModel):
    """创建入库请求"""
    product_id: int = Field(..., gt=0, description="产品ID")
    quantity: int = Field(..., gt=0, le=9999999, description="入库数量")
    customer: str = Field(..., min_length=1, max_length=100, description="客户名称")
    stockin_date: str = Field(..., description="入库日期 (YYYY-MM-DD)")
    note: str | None = Field(None, max_length=500, description="备注")

    @field_validator('stockin_date')
    @classmethod
    def validate_stockin_date(cls, v):
        return _validate_date_format(v)


class StockInUpdate(BaseModel):
    """更新入库请求"""
    quantity: int | None = Field(None, gt=0, le=9999999, description="入库数量")
    customer: str | None = Field(None, min_length=1, max_length=100, description="客户名称")
    stockin_date: str | None = Field(None, description="入库日期 (YYYY-MM-DD)")
    note: str | None = Field(None, max_length=500, description="备注")

    @field_validator('stockin_date')
    @classmethod
    def validate_stockin_date(cls, v):
        return _validate_date_format(v)


# ==================== 出库 ====================

class StockOutCreate(BaseModel):
    """创建出库请求"""
    product_id: int = Field(..., gt=0, description="产品ID")
    quantity: int = Field(..., gt=0, le=9999999, description="出库数量")
    customer: str = Field(..., min_length=1, max_length=100, description="客户名称")
    stockout_date: str = Field(..., description="出库日期 (YYYY-MM-DD)")
    note: str | None = Field(None, max_length=500, description="备注")

    @field_validator('stockout_date')
    @classmethod
    def validate_stockout_date(cls, v):
        return _validate_date_format(v)


class StockOutUpdate(BaseModel):
    """更新出库请求"""
    quantity: int | None = Field(None, gt=0, le=9999999, description="出库数量")
    customer: str | None = Field(None, min_length=1, max_length=100, description="客户名称")
    stockout_date: str | None = Field(None, description="出库日期 (YYYY-MM-DD)")
    note: str | None = Field(None, max_length=500, description="备注")

    @field_validator('stockout_date')
    @classmethod
    def validate_stockout_date(cls, v):
        return _validate_date_format(v)


# ==================== 通用响应 ====================

class StockListResponse(BaseModel):
    """库存列表响应"""
    success: bool = True
    data: list[dict]
    total: int = 0
    page: int = 1
    per_page: int = 50


class StockActionResponse(BaseModel):
    """库存操作响应"""
    success: bool
    message: str


class InventoryResponse(BaseModel):
    """库存查看响应"""
    success: bool = True
    data: list[dict]
    total_order_quantity: int = 0
    total_stockin_quantity: int = 0
    total_stock: int = 0
    total_available_stock: int = 0
    all_customers: list[str] = []
    total_items: int = 0
    page: int = 1
    per_page: int = 50
