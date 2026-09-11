"""
采购中心 Pydantic 请求模型
"""


from pydantic import BaseModel, Field


class OrderIdsRequest(BaseModel):
    """订单ID列表请求"""
    ids: list[int] = Field(..., min_length=1, max_length=500, description="订单ID列表")

class OrderIdRequest(BaseModel):
    """单个订单ID请求"""
    order_id: int = Field(..., description="订单ID")

class OrderIdsAltRequest(BaseModel):
    """订单ID列表请求(备用字段名)"""
    order_ids: list[int] = Field(..., min_length=1, max_length=500, description="订单ID列表")

class CompositeIdsRequest(BaseModel):
    """复合ID列表请求，格式为 'order:5' 或 'stockin:3'"""
    composite_ids: list[str] = Field(..., min_length=1, max_length=500, description="复合ID列表")

class CustomerSyncRequest(BaseModel):
    """客户同步请求"""
    customer_ids: list[int] | None = Field(None, max_length=500, description="客户ID列表，为空则全量同步")
    force: bool = False

class CustomerBatchRequest(BaseModel):
    """客户批量查询请求"""
    ids: list[int] = Field(..., min_length=1, max_length=500, description="客户ID列表")

class FillingItem(BaseModel):
    """BOM 填充物明细（ProductMaterial）。

    允许额外字段以兼容前端未声明的扩展字段。
    """
    model_config = {"extra": "allow"}
    id: int | None = None
    role_id: int | None = None
    role_key: str | None = None
    cotton_usage: float = 0
    supplier_id: int | None = None
    supplier_name: str = ''
    specification: str = ''
    unit: str = ''
    remark: str = ''


class FabricItem(BaseModel):
    """BOM 面料明细（ProductFabric）。

    允许额外字段以兼容前端未声明的扩展字段。
    """
    model_config = {"extra": "allow"}
    id: int | None = None
    role_id: int | None = None
    role_key: str | None = None
    fabric_name: str = ''
    specification: str = ''
    unit: str = ''
    quantity: float = 0
    supplier_id: int | None = None
    supplier_name: str = ''
    remark: str = ''


class AccessoryItem(BaseModel):
    """BOM 辅料明细（ProductAccessory）。

    允许额外字段以兼容前端未声明的扩展字段。
    """
    model_config = {"extra": "allow"}
    id: int | None = None
    role_id: int | None = None
    role_key: str | None = None
    accessory_name: str = ''
    specification: str = ''
    unit: str = ''
    quantity: float = 0
    supplier_id: int | None = None
    supplier_name: str = ''
    remark: str = ''


class PackagingItem(BaseModel):
    """BOM 包装明细（预留字段，允许额外字段）。"""
    model_config = {"extra": "allow"}


class RoleItem(BaseModel):
    """BOM 角色明细（ProductRole）。

    允许额外字段以兼容前端未声明的扩展字段。
    """
    model_config = {"extra": "allow"}
    id: int | None = None
    role_key: str | None = None
    role_name: str = ''
    name: str | None = None


class BomSaveRequest(BaseModel):
    """保存BOM请求"""
    filling: FillingItem | None = None
    fabrics: list[FabricItem] = []
    accessories: list[AccessoryItem] = []
    packagings: list[PackagingItem] = []
    roles: list[RoleItem] = []
    fillings: list[FillingItem] = []

class BomCopyRequest(BaseModel):
    """复制BOM请求"""
    source_product_id: int = Field(..., description="源产品ID")
    overwrite: bool = False

class MaterialOrderItem(BaseModel):
    """物料计算单个订单项"""
    product_id: int = Field(..., gt=0, description="产品ID")
    quantity: float = Field(..., gt=0, description="订单数量，必须大于0")

class CalculateMaterialRequest(BaseModel):
    """物料计算请求"""
    orders: list[MaterialOrderItem] = Field(..., min_length=1, description="订单物料列表")

class PurchaseOrderMaterialItem(BaseModel):
    """采购订单物料明细。

    允许额外字段以兼容前端未声明的扩展字段。
    """
    model_config = {"extra": "allow"}
    material_name: str = ''
    material_code: str = ''
    specification: str = ''
    unit: str = ''
    unit_price: float = 0
    quantity: float = 0
    supplier_id: int | None = None
    supplier_name: str = ''
    customer_name: str = ''
    category: str = ''
    remark: str = ''


class PurchaseOrderCreateRequest(BaseModel):
    """创建采购订单请求"""
    materials: list[PurchaseOrderMaterialItem] = Field(..., min_length=1, description="物料列表")
    customer_id: int | None = None
    customer_name: str = ''
    customer_code: str = ''
    remark: str = ''
    unprocessed_order_id: int | None = None

class PurchaseOrderUpdateRequest(BaseModel):
    """更新采购订单请求"""
    status: str | None = None
    remark: str | None = None
    supplier_name: str | None = None
    customer_name: str | None = None
    modify_reason: str = ''

class BatchCompleteRequest(BaseModel):
    """批量完成订单请求"""
    ids: list[int] = Field(..., min_length=1, max_length=500, description="订单ID列表")

class OneClickGenerateRequest(BaseModel):
    """一键生成采购订单请求"""
    composite_ids: list[str] = Field(..., min_length=1, max_length=500, description="复合ID列表，格式为 'order:5' 或 'stockin:3'")

class ExportCompletedRequest(BaseModel):
    """导出已完成订单请求"""
    order_no: str | None = None
    customer_name: str | None = None
    product_name: str | None = None
    start_date: str | None = None
    end_date: str | None = None

class FactorySummaryEditItem(BaseModel):
    """工厂订单汇总编辑项。

    允许额外字段以兼容前端未声明的扩展字段。
    """
    model_config = {"extra": "allow"}
    item_ids: list[int] = []
    quantity: float | None = None


class FactorySummarySaveRequest(BaseModel):
    """保存工厂订单编辑请求"""
    edits: list[FactorySummaryEditItem] = Field(..., min_length=1, description="编辑列表")

class SummaryPrintRequest(BaseModel):
    """汇总打印请求"""
    ids: list[int] = Field(..., min_length=1, max_length=500, description="订单ID列表")
    format: str = 'print'

class QueryCondition(BaseModel):
    """查询条件（动态结构，允许额外字段）。

    查询条件为前端动态构造的过滤参数，结构不固定，因此允许任意额外字段。
    """
    model_config = {"extra": "allow"}


class SaveQueryRequest(BaseModel):
    """保存查询请求"""
    name: str = Field(..., min_length=1, description="查询名称")
    query_type: str = 'purchase_order'
    conditions: QueryCondition = Field(..., description="查询条件")
