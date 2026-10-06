/**
 * OCR 粘贴识别的共享类型（components/ocr 域）。
 *
 * 与后端 schemas/ocr_import.py::OcrOrderPreviewItem / OcrOrderPreviewResult 一一对应。
 * 该链路「识别只预览不写库」：确认后的落点（订单暂存 / 出货暂存）由各消费域的
 * buildStaged 回调决定，这里不约定暂存条目的形状。
 */

/** 产品搜索建议的最小结构（customer-order 的 ProductSuggestion、stock 的 Product 均结构兼容） */
export interface OcrProductOption {
  id: number
  name: string
}

/** 确认导入时交给各域映射函数的上下文 */
export interface OcrStagingContext {
  /** 表单当前选中的时间：图上本来就没有日期 */
  date: string
  /** 表单当前选中的客户：图上没有客户信息时兜底 */
  fallbackCustomer: string
}

/** 图片识别的单条结果（对应后端 schemas/ocr_import.py::OcrOrderPreviewItem） */
export interface OcrOrderItem {
  /** 图上识别到的原始产品名 */
  raw_product_name: string
  /** 匹配到的产品 ID；未匹配为 null，需用户手选 */
  product_id: number | null
  /** 匹配后的产品名；未匹配时回落为原始名 */
  product_name: string
  match_confidence: number
  quantity: number
  unit: string
  customer: string
  customer_id: number | null
  customer_confidence: number
  note: string
}

/** 图片识别预览响应（后端 OcrOrderPreviewResult）。该端点不写库。 */
export interface OcrOrderPreviewResult {
  success: boolean
  message: string
  filename: string
  item_count: number
  items: OcrOrderItem[]
  /** OCR 识别原文，用于区分「认字错了」与「解析错了」 */
  raw_text: string
  warnings: string[]
}

/** 弹窗内可编辑的一行：识别结果 + 前端编辑态 */
export interface OcrDraftItem extends OcrOrderItem {
  uid: string
}
