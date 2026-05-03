"""
生产计划模块 Pydantic 数据模型

手工部录入、包装部录入、汇总动态报表的请求/响应模型。
"""

from pydantic import BaseModel, Field

# ==================== 手工部 ====================

class CraftWorkCreate(BaseModel):
    """创建手工部生产记录"""
    worker_name: str = Field(..., min_length=1, max_length=50, description="工人姓名")
    quantity: int = Field(..., gt=0, le=999999, description="生产数量")
    work_date: str = Field(..., description="生产日期 (YYYY-MM-DD)")
    remark: str | None = Field(None, max_length=500, description="备注")


class CraftWorkUpdate(BaseModel):
    """更新手工部生产记录"""
    worker_name: str | None = Field(None, min_length=1, max_length=50, description="工人姓名")
    quantity: int | None = Field(None, gt=0, le=999999, description="生产数量")
    work_date: str | None = Field(None, description="生产日期 (YYYY-MM-DD)")
    remark: str | None = Field(None, max_length=500, description="备注")


class CraftWorkItem(BaseModel):
    """手工部生产记录条目"""
    id: int
    worker_name: str
    quantity: int
    work_date: str
    remark: str | None = None
    create_time: str | None = None
    created_by: str | None = None


class CraftWorkListResponse(BaseModel):
    """手工部记录列表响应"""
    success: bool = True
    data: list[dict] = []
    daily_summary: dict = {}
    total: int = 0


class CraftWorkActionResponse(BaseModel):
    """手工部操作响应"""
    success: bool
    message: str


# ==================== 包装部 ====================

class PackagingRecordCreate(BaseModel):
    """创建包装部记录"""
    customer: str = Field(..., min_length=1, max_length=100, description="客户")
    product_name: str = Field(..., min_length=1, max_length=100, description="产品名称")
    barcode: str = Field(..., min_length=1, max_length=50, description="69码")
    quantity: int = Field(..., gt=0, le=999999, description="数量")
    pack_date: str = Field(..., description="包装日期 (YYYY-MM-DD)")
    remark: str | None = Field(None, max_length=500, description="备注")


class PackagingRecordUpdate(BaseModel):
    """更新包装部记录"""
    customer: str | None = Field(None, min_length=1, max_length=100, description="客户")
    product_name: str | None = Field(None, min_length=1, max_length=100, description="产品名称")
    barcode: str | None = Field(None, min_length=1, max_length=50, description="69码")
    quantity: int | None = Field(None, gt=0, le=999999, description="数量")
    pack_date: str | None = Field(None, description="包装日期 (YYYY-MM-DD)")
    remark: str | None = Field(None, max_length=500, description="备注")


class PackagingRecordListResponse(BaseModel):
    """包装部记录列表响应"""
    success: bool = True
    data: list[dict] = []
    total: int = 0


class PackagingRecordActionResponse(BaseModel):
    """包装部操作响应"""
    success: bool
    message: str


# ==================== 汇总报表 ====================

class ProductionSummaryResponse(BaseModel):
    """汇总动态报表响应"""
    success: bool = True
    data: list[dict] = []
    monthly_summary: dict = {}
    total: int = 0


class CraftExportRequest(BaseModel):
    """手工部导出请求"""
    start_date: str | None = Field(None, description="起始日期 (YYYY-MM-DD)")
    end_date: str | None = Field(None, description="结束日期 (YYYY-MM-DD)")


class PackagingExportRequest(BaseModel):
    """包装部导出请求"""
    start_date: str | None = Field(None, description="起始日期 (YYYY-MM-DD)")
    end_date: str | None = Field(None, description="结束日期 (YYYY-MM-DD)")
