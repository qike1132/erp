import { get, post, del } from './request'
import type { QueryParams } from '@/types'
import type { OrderListApiResponse } from './order'

/** SKU 外发工序预设 */
export interface OutsourceProcessType {
  id: number
  product_id: number
  product_name?: string | null
  product_barcode?: string | null
  factory?: string | null
  process_type: string
  sort_order: number
  is_active: boolean
  remark?: string | null
  created_by?: string | null
  create_time?: string | null
  update_time?: string | null
}

/** 订单外发工序实例 */
export interface OrderOutsourceProcess {
  id: number
  order_id: number
  order_item_id?: number | null
  product_id: number
  product_name?: string | null
  process_type: string
  sort_order: number
  status: 'pending' | 'shipped' | 'received'
  shipped_quantity?: number | null
  received_quantity?: number | null
  planned_start_time?: string | null
  planned_end_time?: string | null
  actual_start_time?: string | null
  actual_end_time?: string | null
  remark?: string | null
  created_by?: string | null
  create_time?: string | null
  update_time?: string | null
}

export interface ProcessTypeListResponse {
  success: boolean
  data: OutsourceProcessType[]
  total: number
}

export interface OrderProcessListResponse {
  success: boolean
  data: OrderOutsourceProcess[]
  total: number
}

export interface GenerateProcessResponse {
  success: boolean
  message: string
  created: number
  skipped: number
}

/** 外发工序发货/收货流水记录（台账） */
export interface OutsourceProcessFlow {
  id: number
  process_id: number
  process_type?: string | null
  action: 'ship' | 'receive'
  quantity: number
  operator?: string | null
  create_time?: string | null
}

export interface ProcessFlowListResponse {
  success: boolean
  data: OutsourceProcessFlow[]
  total: number
}

export const outsourceApi = {
  /** 湖北工厂订单列表（强制 factory=湖北，含备货） */
  orders: (params?: QueryParams) => get<OrderListApiResponse>('/outsource/orders', params),
  /** SKU 工序预设 */
  processTypes: (params?: QueryParams) => get<ProcessTypeListResponse>('/outsource/process-types', params),
  /** 为一个 SKU 批量添加多个工序预设（自由输入工序名称） */
  batchCreateProcessTypes: (productId: number, processTypes: string[]) =>
    post<GenerateProcessResponse>('/outsource/process-types/batch', { product_id: productId, process_types: processTypes }),
  deleteProcessType: (id: number) => del(`/outsource/process-types/${id}`),
  /** 订单外发工序 */
  orderProcesses: (orderId: number) => get<OrderProcessListResponse>(`/outsource/orders/${orderId}/processes`),
  /** 订单外发工序流水（台账） */
  orderFlows: (orderId: number) => get<ProcessFlowListResponse>(`/outsource/orders/${orderId}/flows`),
  /** 批量发货（单事务原子）：一次请求完成多道工序发货，任一条失败整批回滚 */
  shipProcessesBatch: (orderId: number, items: { process_id: number; quantity: number }[]) =>
    post<OrderProcessListResponse>(`/outsource/orders/${orderId}/processes/ship-batch`, { items }),
  /** 批量收货（单事务原子）：quantity 缺省时后端按剩余待收数量收货 */
  receiveProcessesBatch: (orderId: number, items: { process_id: number; quantity?: number }[]) =>
    post<OrderProcessListResponse>(`/outsource/orders/${orderId}/processes/receive-batch`, { items })
}
