"""
订单管理 Pydantic 数据模型

用于订单 CRUD 及审批流程的请求/响应模型。
"""

from pydantic import BaseModel, Field


class OrderCreate(BaseModel):
    product_id: int = Field(..., gt=0, description="产品ID")
    quantity: int = Field(..., gt=0, le=9999999, description="订单数量")
    customer: str = Field(..., min_length=1, max_length=100, description="客户名称")
    note: str | None = Field(None, max_length=500, description="备注")


class OrderUpdate(BaseModel):
    product_id: int | None = Field(None, gt=0, description="产品ID")
    quantity: int | None = Field(None, gt=0, le=9999999, description="订单数量")
    customer: str | None = Field(None, min_length=1, max_length=100, description="客户名称")
    note: str | None = Field(None, max_length=500, description="备注")


class OrderItemSchema(BaseModel):
    """订单明细（SKU 粒度）响应 schema"""
    id: int
    order_id: int
    product_id: int
    product_name: str | None = None
    product_barcode: str | None = None
    quantity: int
    deduct_stock: bool = False
    deduct_quantity: int = 0
    note: str | None = None


class OrderItemCreate(BaseModel):
    """订单明细创建 schema（用于批量提交内部组装）"""
    product_id: int = Field(..., gt=0, description="产品ID")
    quantity: int = Field(..., gt=0, le=9999999, description="订单数量")
    deduct_stock: bool = False
    deduct_quantity: int = 0
    note: str | None = Field(None, max_length=500, description="备注")


class OrderItemUpdate(BaseModel):
    """单个订单明细（SKU）编辑 schema（报表流水行内编辑，2026-10-13）

    仅允许改该 SKU 的数量与备注；客户是订单级字段，不走此接口。
    未传字段沿用原值（部分更新语义）。
    """
    quantity: int | None = Field(None, gt=0, le=9999999, description="该 SKU 数量")
    note: str | None = Field(None, max_length=500, description="该 SKU 备注")


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
    is_locked: bool | None = None
    locked_by_name: str | None = None
    items: list[OrderItemSchema] = []


class OrderListResponse(BaseModel):
    """订单列表响应"""
    success: bool = True
    data: list[dict]
    total: int = 0
    page: int = 1
    per_page: int = 50
    # 未确认湖北订单总数（beile-list 专用，列表顶部横幅使用）
    unconfirmed_count: int = 0


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
