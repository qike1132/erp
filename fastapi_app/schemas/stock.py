"""
库存管理 Pydantic 数据模型

用于入库、出库、库存查看的请求/响应模型。
"""
from pydantic import BaseModel, Field
from typing import Optional, List


# ==================== 入库 ====================

class StockInCreate(BaseModel):
    """创建入库请求"""
    product_id: int = Field(..., gt=0, description="产品ID")
    quantity: int = Field(..., gt=0, le=100000, description="入库数量")
    customer: str = Field(..., min_length=1, max_length=100, description="客户名称")
    stockin_date: str = Field(..., description="入库日期 (YYYY-MM-DD)")
    note: Optional[str] = Field(None, max_length=500, description="备注")


class StockInUpdate(BaseModel):
    """更新入库请求"""
    quantity: Optional[int] = Field(None, gt=0, le=100000, description="入库数量")
    customer: Optional[str] = Field(None, min_length=1, max_length=100, description="客户名称")
    stockin_date: Optional[str] = Field(None, description="入库日期 (YYYY-MM-DD)")
    note: Optional[str] = Field(None, max_length=500, description="备注")


# ==================== 出库 ====================

class StockOutCreate(BaseModel):
    """创建出库请求"""
    product_id: int = Field(..., gt=0, description="产品ID")
    quantity: int = Field(..., gt=0, le=100000, description="出库数量")
    customer: str = Field(..., min_length=1, max_length=100, description="客户名称")
    stockout_date: str = Field(..., description="出库日期 (YYYY-MM-DD)")
    note: Optional[str] = Field(None, max_length=500, description="备注")


class StockOutUpdate(BaseModel):
    """更新出库请求"""
    quantity: Optional[int] = Field(None, gt=0, le=100000, description="出库数量")
    customer: Optional[str] = Field(None, max_length=100, description="客户名称")
    stockout_date: Optional[str] = Field(None, description="出库日期 (YYYY-MM-DD)")
    note: Optional[str] = Field(None, max_length=500, description="备注")


# ==================== 通用响应 ====================

class StockListResponse(BaseModel):
    """库存列表响应"""
    success: bool = True
    data: List[dict]
    total: int = 0


class StockActionResponse(BaseModel):
    """库存操作响应"""
    success: bool
    message: str


class InventoryResponse(BaseModel):
    """库存查看响应"""
    success: bool = True
    data: List[dict]
    total_order_quantity: int = 0
    total_stockin_quantity: int = 0
    total_stock: int = 0
