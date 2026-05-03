

from pydantic import BaseModel, Field


class SupplierSummaryItem(BaseModel):
    """供应商汇总明细项"""
    material_name: str = Field(..., description="商品名称")
    specification: str | None = Field(default="", description="规格型号")
    unit: str | None = Field(default="", description="单位")
    quantity: float = Field(..., description="数量")
    material_category: str | None = Field(default="", description="物料分类")
    order_count: int = Field(..., description="订单数量")


class SupplierSummary(BaseModel):
    """供应商汇总"""
    supplier_name: str = Field(..., description="供应商名称")
    supplier_id: int | None = Field(default=None, description="供应商ID")
    items: list[SupplierSummaryItem] = Field(..., description="商品明细列表")
    orders: list[str] = Field(..., description="关联订单号列表")
    order_count: int = Field(..., description="关联订单数量")


class SupplierSummaryRequest(BaseModel):
    """供应商汇总请求"""
    ids: list[int] = Field(..., description="采购订单ID列表")
    format: str | None = Field(default="print", description="输出格式: print/json")


class SupplierSummaryResponse(BaseModel):
    """供应商汇总响应"""
    success: bool = Field(..., description="是否成功")
    suppliers: list[SupplierSummary] | None = Field(default=None, description="供应商汇总列表")
    supplier_count: int | None = Field(default=None, description="供应商数量")
    order_count: int | None = Field(default=None, description="订单数量")
    html: str | None = Field(default=None, description="打印HTML(print格式时返回)")
    message: str | None = Field(default=None, description="错误信息")

