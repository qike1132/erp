import { get, post, put, del } from './request'
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

/** 看板订单条目 */
export interface KanbanOrder {
  id: number
  order_no: string
  customer: string
  order_date: string
  record_type: 'order' | 'stockin'
  products: { product_id: number; product_name: string | null; quantity: number }[]
  processes: OrderOutsourceProcess[]
  total_processes: number
  completed_processes: number
  progress: number
  current_process: string | null
  status_label: string
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

export interface KanbanResponse {
  success: boolean
  data: KanbanOrder[]
  total: number
  page: number
  per_page: number
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
  /** 进度看板 */
  kanban: (params?: QueryParams) => get<KanbanResponse>('/outsource/kanban', params),
  /** SKU 工序预设 */
  processTypes: (params?: QueryParams) => get<ProcessTypeListResponse>('/outsource/process-types', params),
  createProcessType: (data: Partial<OutsourceProcessType>) => post<OutsourceProcessType>('/outsource/process-types', data),
  /** 为一个 SKU 批量添加多个工序预设（自由输入工序名称） */
  batchCreateProcessTypes: (productId: number, processTypes: string[]) =>
    post<GenerateProcessResponse>('/outsource/process-types/batch', { product_id: productId, process_types: processTypes }),
  updateProcessType: (id: number, data: Partial<OutsourceProcessType>) => put<OutsourceProcessType>(`/outsource/process-types/${id}`, data),
  deleteProcessType: (id: number) => del(`/outsource/process-types/${id}`),
  /** 订单外发工序 */
  orderProcesses: (orderId: number) => get<OrderProcessListResponse>(`/outsource/orders/${orderId}/processes`),
  /** 订单外发工序流水（台账） */
  orderFlows: (orderId: number) => get<ProcessFlowListResponse>(`/outsource/orders/${orderId}/flows`),
  generateProcesses: (orderId: number) => post<GenerateProcessResponse>(`/outsource/orders/${orderId}/processes/generate`),
  updateProcess: (id: number, data: Partial<OrderOutsourceProcess>) => put<OrderProcessListResponse>(`/outsource/processes/${id}`, data),
  shipProcess: (id: number, shippedQuantity: number) =>
    post<OrderProcessListResponse>(`/outsource/processes/${id}/ship`, { shipped_quantity: shippedQuantity }),
  receiveProcess: (id: number, receivedQuantity?: number) =>
    post<OrderProcessListResponse>(`/outsource/processes/${id}/receive`, receivedQuantity != null ? { received_quantity: receivedQuantity } : {}),
  deleteProcess: (id: number) => del(`/outsource/processes/${id}`),
}
