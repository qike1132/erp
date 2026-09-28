"""
暂存区 Pydantic 数据模型

用于暂存订单、备货、出货的请求/响应模型。
"""

from pydantic import BaseModel, Field

# ==================== 通用响应 ====================

class StagingResponse(BaseModel):
    """通用暂存操作响应"""
    success: bool = Field(..., description="是否成功")
    message: str = Field(..., description="结果消息")


class StagingListResponse(BaseModel):
    """暂存列表响应"""
    success: bool = Field(True, description="是否成功")
    data: list[dict] = Field(default_factory=list, description="暂存数据列表")
    total: int = Field(default=0, description="总数")


# ==================== 暂存订单 ====================

class StagingOrderUpdate(BaseModel):
    """更新暂存订单请求"""
    customer: str | None = Field(None, description="客户名称")
    product_name: str | None = Field(None, description="产品名称")
    quantity: int | None = Field(None, gt=0, description="订单数量")
    deduct_stock: bool | None = Field(None, description="是否抵扣备货")
    deduct_quantity: int | None = Field(None, ge=0, description="抵扣备货数量")
    note: str | None = Field(None, description="备注")


class StagingOrderConfirmResult(BaseModel):
    """暂存订单确认结果"""
    success: bool = Field(..., description="是否成功")
    message: str = Field(..., description="结果消息")
    confirmed: int = Field(default=0, description="确认数量")
    errors: list[str] = Field(default_factory=list, description="错误列表")


class StagingOrderImportResult(BaseModel):
    """暂存订单导入结果"""
    success: bool = Field(..., description="是否成功")
    message: str = Field(..., description="结果消息")
    imported: int = Field(default=0, description="导入数量")
    session_id: str | None = Field(None, description="会话ID")
    errors: list[str] = Field(default_factory=list, description="错误列表")


# ==================== 暂存备货 ====================

class StagingStockInUpdate(BaseModel):
    """更新暂存备货请求"""
    customer: str | None = Field(None, description="客户名称")
    product_name: str | None = Field(None, description="产品名称")
    quantity: int | None = Field(None, gt=0, description="备货数量")
    stockin_date: str | None = Field(None, description="备货时间")
    note: str | None = Field(None, description="备注")


class StagingStockInConfirmResult(BaseModel):
    """暂存备货确认结果"""
    success: bool = Field(..., description="是否成功")
    message: str = Field(..., description="结果消息")
    confirmed: int = Field(default=0, description="确认数量")
    errors: list[str] = Field(default_factory=list, description="错误列表")


class StagingStockInImportResult(BaseModel):
    """暂存备货导入结果"""
    success: bool = Field(..., description="是否成功")
    message: str = Field(..., description="结果消息")
    imported: int = Field(default=0, description="导入数量")
    errors: list[str] = Field(default_factory=list, description="错误列表")


# ==================== 暂存出货 ====================

class StagingStockOutUpdate(BaseModel):
    """更新暂存出货请求"""
    customer: str | None = Field(None, description="客户名称")
    product_name: str | None = Field(None, description="产品名称")
    quantity: int | None = Field(None, gt=0, description="出货数量")
    stockout_date: str | None = Field(None, description="出货时间")
    note: str | None = Field(None, description="备注")


class StagingStockOutConfirmResult(BaseModel):
    """暂存出货确认结果"""
    success: bool = Field(..., description="是否成功")
    message: str = Field(..., description="结果消息")
    confirmed: int = Field(default=0, description="确认数量")
    errors: list[str] = Field(default_factory=list, description="错误列表")


class StagingStockOutImportResult(BaseModel):
    """暂存出货导入结果"""
    success: bool = Field(..., description="是否成功")
    message: str = Field(..., description="结果消息")
    imported: int = Field(default=0, description="导入数量")
    errors: list[str] = Field(default_factory=list, description="错误列表")


# ==================== 清空响应 ====================

class StagingClearResponse(BaseModel):
    """暂存清空响应"""
    success: bool = Field(True, description="是否成功")
    message: str = Field(..., description="结果消息")
    deleted: int | None = Field(None, description="删除数量")
