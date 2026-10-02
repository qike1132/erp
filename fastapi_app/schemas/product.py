"""
产品管理 Pydantic 数据模型

用于产品 CRUD 的请求/响应模型。
"""

from datetime import datetime

from pydantic import BaseModel, Field, field_validator

from utils.sanitizer import sanitize_url

# 允许的工厂选项（与前端下拉框保持一致）
VALID_FACTORIES = ('东莞', '湖北')


def _validate_factory(v: str | None) -> str | None:
    """校验工厂值必须属于允许的选项集合，允许为空"""
    if v and v not in VALID_FACTORIES:
        raise ValueError(f'工厂值无效，必须是 {"/".join(VALID_FACTORIES)} 之一')
    return v


class ProductCreate(BaseModel):
    """创建产品请求"""

    name: str = Field(..., min_length=1, max_length=100, description='产品名称')
    barcode: str | None = Field(None, max_length=50, description='69码/商品条码')
    price: float | None = Field(None, ge=0, description='产品价格')
    image: str | None = Field(None, max_length=200, description='产品图片路径')
    factory: str | None = Field(None, max_length=50, description='所属工厂')
    initial_stock: int = Field(0, ge=0, le=100000, description='初始库存')

    @field_validator('image')
    @classmethod
    def sanitize_image_url(cls, v: str | None) -> str | None:
        if v:
            sanitized = sanitize_url(v)
            if not sanitized:
                raise ValueError('图片URL包含不安全的协议')
            return sanitized
        return v

    @field_validator('factory')
    @classmethod
    def validate_factory(cls, v: str | None) -> str | None:
        return _validate_factory(v)


class ProductUpdate(BaseModel):
    """更新产品请求"""

    name: str | None = Field(None, min_length=1, max_length=100, description='产品名称')
    barcode: str | None = Field(None, max_length=50, description='69码/商品条码')
    price: float | None = Field(None, ge=0, description='产品价格')
    image: str | None = Field(None, max_length=200, description='产品图片路径')
    factory: str | None = Field(None, max_length=50, description='所属工厂')
    initial_stock: int | None = Field(None, ge=0, le=100000, description='初始库存')

    @field_validator('image')
    @classmethod
    def sanitize_image_url(cls, v: str | None) -> str | None:
        if v:
            sanitized = sanitize_url(v)
            if not sanitized:
                raise ValueError('图片URL包含不安全的协议')
            return sanitized
        return v

    @field_validator('factory')
    @classmethod
    def validate_factory(cls, v: str | None) -> str | None:
        return _validate_factory(v)


class ProductResponse(BaseModel):
    """产品响应"""

    id: int
    name: str
    barcode: str | None = None
    price: float | None = 0
    image: str | None = None
    factory: str | None = None
    initial_stock: int
    current_stock: int
    create_time: datetime | str | None = None

    @field_validator('image', mode='after')
    @classmethod
    def sign_image_url(cls, v: str | None) -> str | None:
        """出站签发：存量直链转限时签名 URL（OPT-19 前端切换）。

        sign_upload_url 幂等（已带 query 原样返回、密钥未配置返回原 URL），
        故对序列化层的重复调用安全。

        外部直链（http/https 等带 scheme，或 // 协议相对）原样返回：它们不是本地上传
        key，而 sign_upload_url 会把任意非 /static/uploads/ 的值拼成
        /static/uploads/<值>，直接签会把外链拼成 /static/uploads/https://... 而损坏。
        入库侧 sanitize_url 明确放行这类绝对 URL，故出站必须与之一致。
        """
        from urllib.parse import urlparse

        from fastapi_app.services.signed_urls import sign_upload_url

        if not v:
            return v
        parsed = urlparse(v)
        if parsed.scheme or parsed.netloc:
            return v
        return sign_upload_url(v)

    class Config:
        from_attributes = True


class ProductListResponse(BaseModel):
    """产品列表响应"""

    success: bool = True
    # 必须是 ProductResponse 而非 list[dict]：只有走模型校验才会触发 sign_image_url
    # 出站签发。用裸 dict 时列表页的 image 不签发，nginx secure_link 生效后整页图 403
    # （详情页走 ProductResponse 有签发，故此前只有列表漏掉）。
    # 缓存存的是 to_dict() 的裸 dict，签发在每次序列化时发生，不会把限时 URL 写进缓存。
    items: list[ProductResponse]
    total: int = 0


class ProductActionResponse(BaseModel):
    """产品操作响应"""

    success: bool
    message: str


class ProductSearchItem(BaseModel):
    """产品搜索结果项"""

    id: int
    name: str
    barcode: str | None = None
    price: float | None = 0
    current_stock: int = 0


class ProductStockInfo(BaseModel):
    """产品库存信息"""

    product_id: int
    name: str
    current_stock: int
    available_stock: int
