"""
批量导入 Pydantic 数据模型
"""
from pydantic import BaseModel, Field
from typing import Optional, List


class BatchImportResult(BaseModel):
    """批量导入结果"""
    success: bool = Field(..., description="是否成功")
    message: str = Field(..., description="结果消息")
    imported: int = Field(default=0, description="成功导入数量")
    skipped: int = Field(default=0, description="跳过数量")


class ComprehensiveImportResult(BaseModel):
    """综合批量导入结果"""
    success: bool = Field(..., description="是否成功")
    message: str = Field(default="", description="结果消息")
    imported: dict = Field(
        default_factory=lambda: {"products": 0, "orders": 0, "stockins": 0, "stockouts": 0},
        description="各类型导入数量"
    )
    errors: List[str] = Field(default_factory=list, description="错误列表")


class DeductionDetail(BaseModel):
    """抵扣详情"""
    stockin_id: int
    stockin_no: str
    deduct_amount: int
    stockout_no: str
    remaining_in_stockin: int
