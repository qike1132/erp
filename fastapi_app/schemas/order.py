"""
订单管理 Pydantic 数据模型

用于订单 CRUD 及审批流程的请求/响应模型。
"""

from pydantic import BaseModel, Field, model_validator


class OrderCreate(BaseModel):
    product_id: int = Field(..., gt=0, description="产品ID")
    quantity: int = Field(..., gt=0, le=9999999, description="订单数量")
    customer: str = Field(..., min_length=1, max_length=100, description="客户名称")
    note: str | None = Field(None, max_length=500, description="备注")
    order_type: str = Field("regular", pattern="^(regular|custom)$", description="订单类型")
    country: str | None = Field(None, max_length=100, description="国家名称（定制订单必填）")

    @model_validator(mode='after')
    def validate_custom_order(self):
        if self.order_type == 'custom' and not self.country:
            raise ValueError('定制订单必须填写国家名称')
        return self


class OrderUpdate(BaseModel):
    product_id: int | None = Field(None, gt=0, description="产品ID")
    quantity: int | None = Field(None, gt=0, le=9999999, description="订单数量")
    customer: str | None = Field(None, min_length=1, max_length=100, description="客户名称")
    note: str | None = Field(None, max_length=500, description="备注")
    order_type: str | None = Field(None, pattern="^(regular|custom)$", description="订单类型")
    country: str | None = Field(None, max_length=100, description="国家名称")

    @model_validator(mode='after')
    def validate_custom_order(self):
        if self.order_type == 'custom' and not self.country:
            raise ValueError('定制订单必须填写国家名称')
        return self


class OrderDetailResponse(BaseModel):
    """单个订单详情响应"""
    id: int
    order_no: str
    customer: str
    order_date: str = ""
    product: dict | None = None
    quantity: int
    deduct_quantity: int = 0
    status: str
    note: str = ""
    order_type: str = "regular"
    country: str = ""
    is_locked: bool | None = None
    locked_by_name: str | None = None


class OrderListResponse(BaseModel):
    """订单列表响应"""
    success: bool = True
    data: list[dict]
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
    data: list[dict]
    total: int = 0
