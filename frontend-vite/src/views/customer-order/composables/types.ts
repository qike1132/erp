/**
 * customer-order 模块局部类型定义
 *
 * OrderItem / StockInRecord 等通用类型从 @/types 复用，
 * 此处仅定义模块内部使用的类型。
 */

/** 暂存列表项（录入页右栏） */
export interface StagedItem {
  /** 唯一标识，用于异步操作后安全定位（避免索引失效） */
  uid: string
  type: 'order' | 'stockin'
  orderType: 'normal' | 'custom'
  customer: string
  productId: number
  productName: string
  quantity: number
  date: string
  note: string
  country: string
  deductStock: boolean
  deductQuantity: number
}

/** 录入表单状态 */
export interface FormState {
  type: 'order' | 'stockin'
  orderType: 'normal' | 'custom'
  date: string
  customer: string
  productSearch: string
  productId: number
  quantity: number
  deductStock: boolean
  deductQuantity: number
  note: string
  country: string
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
  order_type?: string
  country?: string
  is_locked?: boolean
  locked_by_name?: string
  /** 订单关联的工厂名列表（从 items 聚合，去重排序） */
  factories?: string[]
  items?: Array<{
    id: number
    product_name: string
    product_barcode?: string
    quantity: number
    order_type?: string
    country?: string
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
