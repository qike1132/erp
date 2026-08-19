"""
每日生产报表 Pydantic 数据模型

统一三部门（充棉部、手工部、包装部）的请求/响应模型。
"""

from pydantic import BaseModel, Field

# ==================== 生产记录 CRUD ====================

class ProductionRecordCreate(BaseModel):
    """创建生产记录"""
    department: str = Field(..., pattern=r'^(filling|handcraft|packaging)$', description="部门")
    product_id: int | None = Field(None, description="关联产品ID")
    product_name: str = Field(..., min_length=1, max_length=100, description="产品名称")
    barcode: str = Field('', max_length=50, description="69码")
    unit_price: float = Field(0, ge=0, description="单价")
    quantity: int = Field(..., gt=0, le=999999, description="生产数量")
    production_date: str = Field(..., description="生产日期 (YYYY-MM-DD)")
    remark: str | None = Field(None, max_length=500, description="备注")


class ProductionRecordUpdate(BaseModel):
    """更新生产记录"""
    department: str | None = Field(None, pattern=r'^(filling|handcraft|packaging)$', description="部门")
    product_id: int | None = Field(None, description="关联产品ID")
    product_name: str | None = Field(None, min_length=1, max_length=100, description="产品名称")
    barcode: str | None = Field(None, max_length=50, description="69码")
    unit_price: float | None = Field(None, ge=0, description="单价")
    quantity: int | None = Field(None, gt=0, le=999999, description="生产数量")
    production_date: str | None = Field(None, description="生产日期 (YYYY-MM-DD)")
    remark: str | None = Field(None, max_length=500, description="备注")


class ProductionRecordItem(BaseModel):
    """生产记录条目"""
    id: int
    department: str
    product_id: int | None = None
    product_name: str
    barcode: str = ''
    unit_price: float = 0
    quantity: int
    production_value: float = 0
    production_date: str
    remark: str | None = None
    create_time: str | None = None
    created_by: str | None = None


class ProductionRecordListResponse(BaseModel):
    """生产记录列表响应"""
    success: bool = True
    data: list[dict] = []
    total: int = 0
    page: int = 1
    per_page: int = 50
    pages: int = 0
    stats: dict | None = None


class ProductionRecordActionResponse(BaseModel):
    """生产记录操作响应"""
    success: bool
    message: str


# ==================== 每日汇总 ====================

class DepartmentDailySummary(BaseModel):
    """部门当日汇总"""
    department: str
    department_label: str
    total_quantity: int = 0
    total_value: float = 0
    sku_count: int = 0


class DailySummaryResponse(BaseModel):
    """当日汇总响应"""
    success: bool = True
    date: str = ''
    departments: list[dict] = []
    overall_quantity: int = 0
    overall_value: float = 0
    overall_sku_count: int = 0


# ==================== 月度汇总 ====================

class MonthlySummaryResponse(BaseModel):
    """月度汇总响应"""
    success: bool = True
    year: int
    month: int
    daily_data: list[dict] = []
    monthly_departments: list[dict] = []
    monthly_total_quantity: int = 0
    monthly_total_value: float = 0


class ProductInfoResponse(BaseModel):
    success: bool = True
    data: dict = {}
