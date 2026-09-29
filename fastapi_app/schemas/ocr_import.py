"""
OCR PDF 导入 Pydantic 数据模型

用于 PDF 出货单 OCR 识别的请求/响应模型。
"""

from pydantic import BaseModel, Field


class OcrPdfImportResult(BaseModel):
    """PDF 批量 OCR 导入结果"""
    success: bool = Field(..., description="是否成功")
    message: str = Field(..., description="结果消息")
    total_imported: int = Field(default=0, description="总导入数量")
    file_count: int = Field(default=0, description="处理文件数")
    file_results: list[dict] = Field(default_factory=list, description="各文件处理结果")
    errors: list[str] = Field(default_factory=list, description="错误列表")
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
    pages: list[OcrPdfPagePreview] = Field(default_factory=list, description="各页识别文本")
    parsed_items: list[OcrPdfParsedItem] = Field(default_factory=list, description="解析出的出货项")


class OcrOrderPreviewItem(BaseModel):
    """订单 OCR 预览的单个条目（含产品/客户匹配结果）"""
    raw_product_name: str = Field(..., description="图上识别到的原始产品名")
    product_id: int | None = Field(default=None, description="匹配到的产品ID，未匹配为 None")
    product_name: str = Field(..., description="匹配后的产品名；未匹配时回落为原始名")
    match_confidence: float = Field(default=0.0, description="产品匹配置信度 0~1")
    quantity: int = Field(..., description="数量")
    unit: str = Field(default="", description="量词（箱/件/个…），未识别到为空")
    customer: str = Field(default="", description="客户名，可为空")
    customer_id: int | None = Field(default=None, description="匹配到的客户ID，未匹配为 None")
    customer_confidence: float = Field(default=0.0, description="客户匹配置信度 0~1")
    note: str = Field(default="", description="备注（本轮不自动提取，留空由用户填写）")


class OcrOrderPreviewResult(BaseModel):
    """订单 OCR 预览结果（**不写库**，由前端人工确认后再入暂存区）"""
    success: bool = Field(..., description="是否识别到条目")
    message: str = Field(..., description="结果消息")
    filename: str = Field(default="", description="文件名")
    item_count: int = Field(default=0, description="识别到的条目数")
    items: list[OcrOrderPreviewItem] = Field(default_factory=list, description="待确认条目")
    raw_text: str = Field(default="", description="OCR 识别原文（用于区分认字错误与解析错误）")
    warnings: list[str] = Field(default_factory=list, description="需要用户注意的提示")
