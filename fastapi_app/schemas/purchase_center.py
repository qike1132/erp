"""
采购中心 Pydantic 请求/响应模型
"""

from typing import Any

from pydantic import BaseModel

# ============================================================
# 产品/BOM 相关
# ============================================================

class ProductBomInfo(BaseModel):
    filling_count: int = 0
    fabric_count: int = 0
    accessory_count: int = 0
    packaging_count: int = 0


class ProductListItem(BaseModel):
    id: int
    name: str
    barcode: str | None = None
    has_bom: bool = False
    bom_info: ProductBomInfo | None = None
    current_stock: int = 0


class ProductListResponse(BaseModel):
    success: bool = True
    products: list[ProductListItem] = []
    total: int = 0
    pages: int = 0
    current_page: int = 1


class ProductBomResponse(BaseModel):
    success: bool = True
    product: dict | None = None
    materials: list[dict] = []


class ProductStatisticsResponse(BaseModel):
    success: bool = True
    statistics: dict | None = None


class SearchSuggestionItem(BaseModel):
    id: int
    name: str
    barcode: str | None = None
    has_bom: bool | None = None


class SearchSuggestionResponse(BaseModel):
    success: bool = True
    suggestions: list[SearchSuggestionItem] = []


class BomSaveRequest(BaseModel):
    """保存BOM请求"""
    filling: dict | None = None
    fabrics: list[dict] = []
    accessories: list[dict] = []
    packagings: list[dict] = []
    roles: list[dict] = []
    fillings: list[dict] = []
    default_bom_label: str | None = None


class MaterialCalculateRequest(BaseModel):
    orders: list[dict]


class MaterialCalculateResponse(BaseModel):
    success: bool = True
    filling: list = []
    fabric: list = []
    accessory: list = []
    packaging: list = []
    total_categories: dict | None = None
    message: str | None = None


# ============================================================
# 供应商相关
# ============================================================

class SupplierCreate(BaseModel):
    name: str
    contact_person: str | None = ''
    phone: str | None = ''
    address: str | None = ''
    remark: str | None = ''


class SupplierResponse(BaseModel):
    id: int
    name: str
    contact_person: str | None = None
    phone: str | None = None
    address: str | None = None


# ============================================================
# 客户相关
# ============================================================

class CustomerSyncRequest(BaseModel):
    customer_ids: list[int] | None = None
    force: bool = False


class CustomerBatchRequest(BaseModel):
    ids: list[int]


class CustomerStatisticsResponse(BaseModel):
    success: bool = True
    statistics: dict | None = None


# ============================================================
# 采购订单相关
# ============================================================

class PurchaseOrderCreate(BaseModel):
    materials: list[dict]
    customer_id: int | None = None
    customer_name: str | None = ''
    customer_code: str | None = ''
    remark: str | None = ''
    unprocessed_order_id: int | None = None


class PurchaseOrderUpdate(BaseModel):
    status: str | None = None
    remark: str | None = None
    supplier_name: str | None = None
    customer_name: str | None = None
    modify_reason: str | None = ''


class PurchaseOrderComplete(BaseModel):
    order_id: int


class PurchaseOrderBatchComplete(BaseModel):
    ids: list[int]


class PurchaseOrderListResponse(BaseModel):
    success: bool = True
    orders: list[dict] = []
    total: int = 0
    pages: int = 0
    current_page: int = 1


class PurchaseOrderDetailResponse(BaseModel):
    success: bool = True
    order: dict | None = None


class PurchaseOrderActionResponse(BaseModel):
    success: bool = True
    message: str | None = None
    orders: list[dict] | None = None
    order: dict | None = None
    # 一键生成时返回的创建数量
    created_count: int | None = None
    # 是否命中唯一约束后回查的幂等结果
    idempotent: bool | None = None


class OneClickGenerateRequest(BaseModel):
    order_ids: list[int]


class CompletedOrdersExportRequest(BaseModel):
    order_no: str | None = ''
    customer_name: str | None = ''
    product_name: str | None = ''
    start_date: str | None = ''
    end_date: str | None = ''


class BatchPrintRequest(BaseModel):
    ids: list[int]


# ============================================================
# 工厂内部采购订单
# ============================================================

class FactorySummaryRequest(BaseModel):
    ids: list[int]


class FactorySummarySaveRequest(BaseModel):
    edits: list[dict]


class GenerateFactoryOrderRequest(BaseModel):
    ids: list[int]


class GenerateSupplierOrderRequest(BaseModel):
    supplier_id: int


# ============================================================
# 供应商汇总
# ============================================================

class SupplierSummaryItem(BaseModel):
    material_name: str
    specification: str | None = ""
    unit: str | None = ""
    quantity: float
    material_category: str | None = ""
    order_count: int


class SupplierSummary(BaseModel):
    supplier_name: str
    supplier_id: int | None = None
    items: list[SupplierSummaryItem]
    orders: list[str]
    order_count: int


class SupplierSummaryRequest(BaseModel):
    ids: list[int]
    format: str | None = "print"


class SupplierSummaryResponse(BaseModel):
    success: bool = True
    suppliers: list[SupplierSummary] | None = None
    supplier_count: int | None = None
    order_count: int | None = None
    html: str | None = None
    message: str | None = None


class SupplierSummaryExportRequest(BaseModel):
    ids: list[int]


class SupplierOrderSummaryRequest(BaseModel):
    ids: list[int]


class SupplierOrderSummaryResponse(BaseModel):
    success: bool = True
    materials: list[dict] | None = None
    order_count: int | None = None
    material_count: int | None = None
    message: str | None = None


# ============================================================
# 汇总打印
# ============================================================

class SummaryPrintRequest(BaseModel):
    ids: list[int]
    format: str | None = "print"


# ============================================================
# 修改历史
# ============================================================

class ModificationLogResponse(BaseModel):
    success: bool = True
    logs: list[dict] = []
    total: int = 0


# ============================================================
# 保存查询
# ============================================================

class SavedQueryCreate(BaseModel):
    name: str
    query_type: str | None = 'purchase_order'
    conditions: Any


class SavedQueryResponse(BaseModel):
    success: bool = True
    queries: list[dict] = []
    query: dict | None = None


# ============================================================
# 状态日志
# ============================================================

class StatusLogResponse(BaseModel):
    success: bool = True
    logs: list[dict] = []
    total: int = 0


# ============================================================
# 未处理订单
# ============================================================

class UnprocessedOrdersResponse(BaseModel):
    success: bool = True
    orders: list[dict] = []
    total: int = 0
    pages: int = 0
    current_page: int = 1
    latest_sync_time: str | None = None


# ============================================================
# 智能联想 & 快捷筛选
# ============================================================

class SuggestionResponse(BaseModel):
    success: bool = True
    suggestions: list[dict] = []


class QuickFilterResponse(BaseModel):
    success: bool = True
    quick_filters: dict[str, int] = {}


# ============================================================
# 通用操作响应
# ============================================================

class ActionResponse(BaseModel):
    success: bool = True
    message: str | None = None
    copied_count: int | None = None
    deleted_count: int | None = None

    model_config = {'extra': 'allow'}


class CacheClearResponse(BaseModel):
    success: bool = True
    message: str = ''


class CategoriesResponse(BaseModel):
    success: bool = True
    categories: dict = {}
