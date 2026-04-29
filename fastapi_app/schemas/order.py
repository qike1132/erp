"""
订单管理 Pydantic 数据模型

用于订单 CRUD 及审批流程的请求/响应模型。
"""
from pydantic import BaseModel, Field
from typing import Optional, List


class OrderCreate(BaseModel):
    """创建订单请求"""
    product_id: int = Field(..., gt=0, description="产品ID")
    quantity: int = Field(..., gt=0, le=9999999, description="订单数量")
    customer: str = Field(..., min_length=1, max_length=100, description="客户名称")
    note: Optional[str] = Field(None, max_length=500, description="备注")
    order_type: str = Field("regular", pattern="^(regular|custom)$", description="订单类型")
    country: Optional[str] = Field(None, max_length=100, description="国家名称（定制订单必填）")


class OrderUpdate(BaseModel):
    """更新订单请求"""
    product_id: Optional[int] = Field(None, gt=0, description="产品ID")
    quantity: Optional[int] = Field(None, gt=0, le=9999999, description="订单数量")
    customer: Optional[str] = Field(None, min_length=1, max_length=100, description="客户名称")
    note: Optional[str] = Field(None, max_length=500, description="备注")
    order_type: Optional[str] = Field(None, pattern="^(regular|custom)$", description="订单类型")
    country: Optional[str] = Field(None, max_length=100, description="国家名称")


class OrderDetailResponse(BaseModel):
    """单个订单详情响应"""
    id: int
    order_no: str
    customer: str
    order_date: str = ""
    product: Optional[dict] = None
    quantity: int
    deduct_quantity: int = 0
    status: str
    note: str = ""
    order_type: str = "regular"
    country: str = ""
    is_locked: Optional[bool] = None
    locked_by_name: Optional[str] = None


class OrderListResponse(BaseModel):
    """订单列表响应"""
    success: bool = True
    data: List[dict]
    total: int = 0
    page: int = 1
    per_page: int = 50


class OrderActionResponse(BaseModel):
    """订单操作响应"""
    success: bool
    message: str


class ApprovalCancelResponse(BaseModel):
    """取消审批响应"""
    success: bool
    message: str


class ApprovalListResponse(BaseModel):
    """审批列表响应"""
    success: bool = True
    data: List[dict]
    total: int = 0
