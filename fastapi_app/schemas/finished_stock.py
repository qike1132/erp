"""成品库存（批次级）Pydantic 模型"""
from pydantic import BaseModel, field_validator


class FinishedStockItem(BaseModel):
    """成品库存聚合行（客户 + 产品 + 批次）"""
    customer_name: str = ''
    product_id: int
    product_name: str = ''
    barcode: str = ''
    batch_no: str = ''
    image: str = ''
    batch_in_qty: int = 0
    batch_available: int = 0
    is_custom: bool = False
    custom_country: str = ''

    @field_validator('image', mode='after')
    @classmethod
    def sign_image_url(cls, v: str) -> str:
        """出站签发图片直链（与 ProductResponse.sign_image_url 同口径）。

        /static/uploads 受 nginx 签名保护，未签名的裸路径会 404；外链原样返回不重签。
        """
        from urllib.parse import urlparse

        from fastapi_app.services.signed_urls import sign_upload_url

        if not v:
            return v
        parsed = urlparse(v)
        if parsed.scheme or parsed.netloc:
            return v
        return sign_upload_url(v)


class FinishedStockSummaryResponse(BaseModel):
    """成品库存聚合响应"""
    success: bool = True
    data: list[FinishedStockItem] = []
    total: int = 0
    total_available: int = 0
    page: int = 1
    per_page: int = 20
    all_customers: list[str] = []


class BatchAvailableItem(BaseModel):
    """某产品的批次可用量"""
    batch_no: str = ''
    available_quantity: int = 0


class BatchListResponse(BaseModel):
    """批次列表响应（供 /stock-out 带出批次选择）"""
    success: bool = True
    data: list[BatchAvailableItem] = []
