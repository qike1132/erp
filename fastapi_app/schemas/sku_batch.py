"""SKU批次管理 Pydantic 数据模型"""
from pydantic import BaseModel, Field
from typing import Optional, List


class SkuBatchQuery(BaseModel):
    """批次查询参数"""
    batch_no: Optional[str] = Field(None, max_length=50, description='批次号')
    sku_code: Optional[str] = Field(None, max_length=50, description='SKU编号')
    status: Optional[str] = Field(None, max_length=20, description='批次状态')


class SkuBatchItem(BaseModel):
    """批次列表项"""
    id: int
    sku_code: str
    batch_no: str
    status: str
    quantity: float = 0
    remark: str = ''
    create_time: str = ''
    update_time: str = ''

    class Config:
        from_attributes = True


class SkuBatchListResponse(BaseModel):
    """批次列表响应"""
    success: bool = True
    items: List[SkuBatchItem]
    total: int = 0
    pages: int = 0
    current_page: int = 1


class SkuBatchActionResponse(BaseModel):
    """操作响应"""
    success: bool
    message: str
