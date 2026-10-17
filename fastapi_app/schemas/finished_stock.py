"""成品库存（批次级）Pydantic 模型"""
from pydantic import BaseModel, Field, field_validator, model_validator


class FinishedStockItem(BaseModel):
    """成品库存聚合行（客户 + 产品 + 批次）"""
    customer_name: str = ''
    product_id: int
    product_name: str = ''
    barcode: str = ''
    batch_no: str = ''
    image: str = ''
    image_thumb: str | None = None
    batch_in_qty: int = 0
    batch_available: int = 0
    is_custom: bool = False
    custom_country: str = ''
    remark: str = ''

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

    @model_validator(mode='after')
    def derive_image_thumb(self) -> 'FinishedStockItem':
        """出站派生缩略图 URL（列表用），与 ProductResponse.derive_image_thumb 同口径。

        缩略图 key 是确定性后缀（get_thumbnail_key 追加 .thumb.webp），无需加列/迁移；
        文件不存在时前端 404 回退原图（列表用 image_thumb，预览用 image=原图）。
        """
        img = self.image
        if img and img.startswith('/static/uploads/'):
            from fastapi_app.services.signed_urls import sign_upload_url
            from fastapi_app.services.storage_service import get_thumbnail_key

            bare = img.split('?', 1)[0]
            self.image_thumb = sign_upload_url(get_thumbnail_key(bare))
        return self


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


class FinishedStockRemarkUpdate(BaseModel):
    """成品库存页备注更新（UPSERT；remark 清空即删除该行）"""
    customer_name: str = Field('', max_length=100, description='客户名称（与聚合行展示值一致；空=未指定客户）')
    product_id: int = Field(..., gt=0, description='产品ID')
    batch_no: str = Field('', max_length=100, description='批次号（空=未分批次）')
    remark: str = Field('', max_length=2000, description='备注内容（清空即删除）')


class FinishedStockRemarkResponse(BaseModel):
    success: bool = True
    remark: str = ''
