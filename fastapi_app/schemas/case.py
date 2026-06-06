"""皮套管理 Schema 定义"""
from pydantic import BaseModel, field_validator

from utils.sanitizer import sanitize_url


class CaseStockInCreate(BaseModel):
    product_id: int
    quantity: int
    stockin_date: str
    customer: str = ''
    note: str = ''


class CaseStockInUpdate(BaseModel):
    customer: str | None = None
    stockin_date: str | None = None
    quantity: int | None = None
    note: str | None = None


class CaseStockOutCreate(BaseModel):
    product_id: int
    quantity: int
    stockout_date: str = ''
    customer: str = ''
    note: str = ''


class CaseStockOutUpdate(BaseModel):
    customer: str | None = None
    stockout_date: str | None = None
    quantity: int | None = None
    note: str | None = None


class CaseProductCreate(BaseModel):
    name: str | None = None
    barcode: str | None = None
    image: str | None = None
    product_id: int | None = None

    @field_validator('image')
    @classmethod
    def sanitize_image_url(cls, v: str | None) -> str | None:
        if v:
            sanitized = sanitize_url(v)
            if not sanitized:
                raise ValueError('图片URL包含不安全的协议')
            return sanitized
        return v


class BatchCaseStockInRequest(BaseModel):
    stockins: list[dict]


class BatchCaseStockOutRequest(BaseModel):
    stockouts: list[dict]


class CaseSearchItem(BaseModel):
    id: int
    name: str
    barcode: str = ''
    current_stock: int = 0


class CaseStockInItem(BaseModel):
    id: int
    stockin_no: str = ''
    stockin_date: str = ''
    customer: str = ''
    case_id: int = 0
    case_name: str = ''
    case_barcode: str = ''
    quantity: int = 0
    note: str = ''


class CaseStockInListResponse(BaseModel):
    stockins: list[CaseStockInItem] = []
    total: int = 0
    pages: int = 0
    current_page: int = 1


class CaseStockInDetailResponse(BaseModel):
    id: int
    stockin_no: str = ''
    stockin_date: str = ''
    customer: str = ''
    case_id: int = 0
    case_name: str = ''
    quantity: int = 0
    note: str = ''


class CaseStockInCreateResponse(BaseModel):
    success: bool
    stockin_no: str = ''
    id: int = 0


class CaseActionResponse(BaseModel):
    success: bool
    message: str = ''


class CaseBatchFailedItem(BaseModel):
    index: int
    error: str = ''


class CaseBatchStockInResponse(BaseModel):
    success: bool
    message: str = ''
    failed: list[CaseBatchFailedItem] = []


class CaseStockOutItem(BaseModel):
    id: int
    stockout_no: str = ''
    stockout_date: str = ''
    customer: str = ''
    case_id: int = 0
    case_name: str = ''
    case_barcode: str = ''
    quantity: int = 0
    note: str = ''


class CaseStockOutListResponse(BaseModel):
    stockouts: list[CaseStockOutItem] = []
    total: int = 0
    pages: int = 0
    current_page: int = 1


class CaseStockOutDetailResponse(BaseModel):
    id: int
    stockout_no: str = ''
    stockout_date: str = ''
    customer: str = ''
    case_id: int = 0
    case_name: str = ''
    quantity: int = 0
    note: str = ''


class CaseStockOutCreateResponse(BaseModel):
    success: bool
    stockout_no: str = ''
    id: int = 0


class CaseBatchStockOutResultItem(BaseModel):
    success: bool
    stockout_no: str = ''
    id: int | str | None = None
    error: str | None = None


class CaseBatchStockOutResponse(BaseModel):
    success: bool
    results: list[CaseBatchStockOutResultItem] = []


class CaseInventoryItem(BaseModel):
    id: int
    name: str = ''
    barcode: str = ''
    initial_stock: int = 0
    current_stock: int = 0
    total_in: int = 0
    total_out: int = 0


class CaseInventoryStats(BaseModel):
    total_stock: int = 0
    total_in: int = 0
    total_out: int = 0


class CaseInventorySummaryResponse(BaseModel):
    inventory: list[CaseInventoryItem] = []
    total: int = 0
    page: int = 1
    per_page: int = 50
    pages: int = 0
    stats: CaseInventoryStats | None = None


class CaseInventoryLogItem(BaseModel):
    id: int
    change_type: str = ''
    change_quantity: int = 0
    change_date: str = ''
    customer: str = ''
    related_id: str = ''
    note: str = ''


class CasePaginationInfo(BaseModel):
    page: int = 1
    pages: int = 0
    total: int = 0


class CaseInventoryLogsResponse(BaseModel):
    success: bool
    logs: list[CaseInventoryLogItem] = []
    pagination: CasePaginationInfo | None = None


class CaseProductItem(BaseModel):
    id: int
    name: str = ''
    barcode: str = ''
    image: str = ''
    current_stock: int = 0
    create_time: str = ''


class CaseProductsResponse(BaseModel):
    cases: list[CaseProductItem] = []
    total: int = 0
    page: int = 1
    per_page: int = 50


class CaseProductCreateResponse(BaseModel):
    success: bool
    message: str = ''
    id: int = 0
