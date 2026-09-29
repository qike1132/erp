/**
 * customer-order 模块局部类型定义
 *
 * OrderItem / StockInRecord 等通用类型从 @/types 复用，
 * 此处仅定义模块内部使用的类型。
 */
import type { OrderItem } from '@/types'

/**
 * 订单详情数据（orderApi.detail 返回）
 *
 * API 实际包含 order_no / batch_no / customer / product 等扩展字段，
 * 且兼容裸返回与 { data } 包裹两种结构；与 OrderItem 取交集描述。
 */
export type OrderDetailData = OrderItem & {
  order_no?: string
  batch_no?: string
  customer?: string
  product?: { id?: number; name?: string; barcode?: string; image?: string }
  data?: OrderItem
}

/** 暂存列表项（录入页右栏） */
export interface StagedItem {
  /** 唯一标识，用于异步操作后安全定位（避免索引失效） */
  uid: string
  /**
   * 条目来源：manual = 本页手工新增（仅存在于前端）；
   * import = Excel 批量导入（服务端 staging_* 表是权威副本）；
   * ocr = 粘贴图片识别后人工确认（仅存在于前端）。
   *
   * 服务端导入前会清空当前会话的暂存区，因此重复导入必须用它替换上一次
   * 导入的条目，否则同一批数据会在列表里翻倍（提交时产生重复订单）。
   * ocr 与 manual 都是纯前端条目，不受该替换逻辑影响。
   */
  origin?: 'manual' | 'import' | 'ocr'
  type: 'order' | 'stockin'
  customer: string
  productId: number
  productName: string
  quantity: number
  date: string
  note: string
  deductStock: boolean
  deductQuantity: number
}

/** 录入表单状态 */
export interface FormState {
  type: 'order' | 'stockin'
  date: string
  customer: string
  productSearch: string
  productId: number
  quantity: number
  deductStock: boolean
  deductQuantity: number
  note: string
}

/**
 * 记录查询 tab 中的统一记录类型（订单或备货归一化后）。
 * 使用扁平接口而非联合类型，因为模板需要统一访问 customer / items / product 等字段，
 * 这些字段在不同记录类型中可能存在或不存在。
 */
export interface OrderRecord {
  id: number
  record_type: 'order' | 'stockin'
  order_no?: string
  stockin_no?: string
  customer?: string
  order_date?: string
  stockin_date?: string
  product_id?: number
  product_name?: string
  product?: { id?: number; name?: string; barcode?: string; image?: string }
  barcode?: string
  quantity: number
  deduct_quantity?: number
  deduct_stock?: boolean
  deducted?: boolean
  status: string
  note?: string
  is_locked?: boolean
  locked_by_name?: string
  /** 订单关联的工厂名列表（从 items 聚合，去重排序） */
  factories?: string[]
  items?: Array<{
    id: number
    product_name: string
    product_barcode?: string
    quantity: number
    deduct_quantity?: number
    note?: string
  }>
}

/** 订单列表 API 响应（对应后端 OrderListResponse schema） */
export interface OrderListResponse {
  success: boolean
  data: OrderRecord[]
  total: number
  page: number
  per_page: number
  /** 未确认湖北订单总数（beile-list 专用，列表顶部横幅使用） */
  unconfirmed_count?: number
}

/** 备货列表 API 响应 */
export interface StockinListResponse {
  data?: OrderRecord[]
  items?: OrderRecord[]
  total?: number
}

/** 产品搜索建议项 */
export interface ProductSuggestion {
  id: number
  value: string
  name: string
  barcode?: string
}

/** 可用备货查询响应中的单项 */
export interface AvailableStockinItem {
  id: number
  quantity: number
  deducted?: number
  available?: number
}

/** 订单图片识别的单条结果（对应后端 schemas/ocr_import.py::OcrOrderPreviewItem） */
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

/** 订单图片识别预览响应（后端 OcrOrderPreviewResult）。该端点不写库。 */
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
