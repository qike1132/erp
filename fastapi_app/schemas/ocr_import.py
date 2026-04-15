"""
OCR PDF 导入 Pydantic 数据模型

用于 PDF 出货单 OCR 识别的请求/响应模型。
"""
from pydantic import BaseModel, Field
from typing import Optional, List


class OcrPdfImportResult(BaseModel):
    """PDF 批量 OCR 导入结果"""
    success: bool = Field(..., description="是否成功")
    message: str = Field(..., description="结果消息")
    total_imported: int = Field(default=0, description="总导入数量")
    file_count: int = Field(default=0, description="处理文件数")
    file_results: List[dict] = Field(default_factory=list, description="各文件处理结果")
    errors: List[str] = Field(default_factory=list, description="错误列表")
    task_id: str = Field(default="", description="进度追踪ID")


class OcrPdfPagePreview(BaseModel):
    """PDF 单页预览"""
    page: int = Field(..., description="页码")
    text: str = Field(..., description="识别文本（截取前500字）")


class OcrPdfParsedItem(BaseModel):
    """OCR 解析出的出货项"""
    customer: str = Field(default="", description="客户名称")
    product_name: str = Field(default="", description="产品名称")
    quantity: int = Field(default=0, description="出货数量")
    note: str = Field(default="", description="备注")


class OcrPdfPreviewResult(BaseModel):
    """PDF OCR 预览结果（不写入暂存区）"""
    success: bool = Field(..., description="是否成功")
    message: str = Field(..., description="结果消息")
    filename: str = Field(default="", description="文件名")
    page_count: int = Field(default=0, description="页数")
    pages: List[OcrPdfPagePreview] = Field(default_factory=list, description="各页识别文本")
    parsed_items: List[OcrPdfParsedItem] = Field(default_factory=list, description="解析出的出货项")
