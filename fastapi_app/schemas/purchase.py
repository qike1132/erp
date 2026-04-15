
from pydantic import BaseModel, Field
from typing import List, Optional
from datetime import datetime


class SupplierSummaryItem(BaseModel):
    """供应商汇总明细项"""
    material_name: str = Field(..., description="商品名称")
    specification: Optional[str] = Field(default="", description="规格型号")
    unit: Optional[str] = Field(default="", description="单位")
    quantity: float = Field(..., description="数量")
    material_category: Optional[str] = Field(default="", description="物料分类")
    order_count: int = Field(..., description="订单数量")


class SupplierSummary(BaseModel):
    """供应商汇总"""
    supplier_name: str = Field(..., description="供应商名称")
    supplier_id: Optional[int] = Field(default=None, description="供应商ID")
    items: List[SupplierSummaryItem] = Field(..., description="商品明细列表")
    orders: List[str] = Field(..., description="关联订单号列表")
    order_count: int = Field(..., description="关联订单数量")


class SupplierSummaryRequest(BaseModel):
    """供应商汇总请求"""
    ids: List[int] = Field(..., description="采购订单ID列表")
    format: Optional[str] = Field(default="print", description="输出格式: print/json")


class SupplierSummaryResponse(BaseModel):
    """供应商汇总响应"""
    success: bool = Field(..., description="是否成功")
    suppliers: Optional[List[SupplierSummary]] = Field(default=None, description="供应商汇总列表")
    supplier_count: Optional[int] = Field(default=None, description="供应商数量")
    order_count: Optional[int] = Field(default=None, description="订单数量")
    html: Optional[str] = Field(default=None, description="打印HTML(print格式时返回)")
    message: Optional[str] = Field(default=None, description="错误信息")

