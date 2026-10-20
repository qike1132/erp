/**
 * 报表页记录操作的模块局部类型（2026-10-06 记录查询 tab 收敛至报表页时迁入）。
 *
 * OrderRecord / OrderDetailData 原在 customer-order/composables/types.ts，
 * 因报表记录操作迁至 /report 而随迁至此。旧 EditOrderModal / useOrderDetailEdit /
 * useOrderDelete 已按 Z11-R1 删除；OrderRecord 现由 useReportRowActions /
 * useStockinEdit 使用。录入侧类型（StagedItem / FormState 等）留在 customer-order。
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

/**
 * 统一记录类型（订单或备货归一化后，GET /orders/records 契约）。
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
  /** 备货行为 null（后端 /orders/records 统一记录契约） */
  status: string | null
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
