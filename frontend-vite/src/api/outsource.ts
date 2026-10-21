import { get, post, del } from './request'
import type { QueryParams, WithRequired, WithItems } from '@/types'
import type { OrderListApiResponse } from './order'
import type { GenerateProcessResponse as GenGenerateProcessResponse, ShipmentReceiveResponse as GenShipmentReceiveResponse, HubeiProductSearchItem as GenHubeiProductSearchItem, ShippableProcessItem as GenShippableProcessItem, UnshippedProcessItem as GenUnshippedProcessItem, OrderProcessListResponse as GenOrderProcessListResponse, ProcessTypeListResponse as GenProcessTypeListResponse, ShipmentBatchOrder as GenShipmentBatchOrder, ShipmentBatchResponse as GenShipmentBatchResponse, ShipmentListResponse as GenShipmentListResponse } from '@/types/api'

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

export type ProcessTypeListResponse = WithItems<Required<GenProcessTypeListResponse>, 'data', OutsourceProcessType>

export type OrderProcessListResponse = WithItems<Required<GenOrderProcessListResponse>, 'data', OrderOutsourceProcess>

export type GenerateProcessResponse = Required<GenGenerateProcessResponse>

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

/** 湖北工厂 SKU 搜索建议项（工序预设页搜索框数据源） */
export type HubeiProductSearchItem = GenHubeiProductSearchItem

/** 未到货（未发完）工序明细：未到数量 = 订单数量 - 已发数量 */
export type UnshippedProcessItem = WithRequired<GenUnshippedProcessItem, 'target_qty' | 'shipped_qty' | 'remaining'>

/** 待发货工序（批量发货面板数据源） */
export type ShippableProcessItem = WithRequired<GenShippableProcessItem, 'target_qty' | 'shipped_qty' | 'remaining'>

/** 发货单明细行（SKU + 工序 + 发货/收货数量） */
export interface ShipmentItem {
  id: number
  process_id?: number | null
  product_id?: number | null
  product_name?: string | null
  process_type: string
  /** 订单要求的该工序总数量（工序已删除时为空） */
  order_qty?: number | null
  shipped_quantity: number
  received_quantity: number
}

/** 发货单（一键发货生成，贝乐用户端「待收货」订单） */
export interface Shipment {
  id: number
  shipment_no: string
  order_id?: number | null
  customer?: string | null
  status: 'shipped' | 'received'
  shipped_at?: string | null
  received_at?: string | null
  shipped_by?: string | null
  received_by?: string | null
  remark?: string | null
  create_time?: string | null
  item_count: number
  total_shipped: number
  items?: ShipmentItem[]
}

export type ShipmentListResponse = WithItems<Required<GenShipmentListResponse>, 'data', Shipment>

export type ShipmentReceiveResponse = Required<GenShipmentReceiveResponse>

/** 批量发货：单个订单的发货明细 */
export type ShipmentBatchOrder = GenShipmentBatchOrder

export type ShipmentBatchResponse = WithItems<Required<GenShipmentBatchResponse>, 'data', Shipment>

export const outsourceApi = {
  /** 湖北工厂订单列表（强制 factory=湖北，含备货） */
  orders: (params?: QueryParams) => get<OrderListApiResponse>('/outsource/orders', params),
  /** 搜索工厂=湖北 的 SKU（工序预设页搜索框数据源） */
  productSearch: (q: string) => get<HubeiProductSearchItem[]>('/outsource/products/search', { q }),
  /** 跨全部湖北订单聚合未发完工序明细（导出/打印未到货清单） */
  unshipped: () => get<UnshippedProcessItem[]>('/outsource/unshipped'),
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
  /** 跨全部湖北订单聚合待发货工序（批量发货面板数据源） */
  shippable: () => get<ShippableProcessItem[]>('/outsource/processes/shippable'),
  /** 跨订单批量发货（单事务原子） */
  shipMulti: (items: { process_id: number; quantity: number }[]) =>
    post<OrderProcessListResponse>('/outsource/processes/ship-multi', { items }),
  /** 批量收货（单事务原子）：quantity 缺省时后端按剩余待收数量收货 */
  receiveProcessesBatch: (orderId: number, items: { process_id: number; quantity?: number }[]) =>
    post<OrderProcessListResponse>(`/outsource/orders/${orderId}/processes/receive-batch`, { items }),
  /** 发货单列表（待收货/已完成筛选 + 计数横幅） */
  shipments: (params?: { status?: string; page?: number; per_page?: number }) =>
    get<ShipmentListResponse>('/outsource/shipments', params),
  /** 一键发货：按订单生成发货单并逐工序发货 */
  createShipment: (orderId: number, items: { process_id: number; quantity: number }[]) =>
    post<Shipment>('/outsource/shipments', { order_id: orderId, items }),
  /** 批量发货（多订单一次性）：每订单生成一张发货单，单事务原子 */
  createShipmentsBatch: (orders: ShipmentBatchOrder[]) =>
    post<ShipmentBatchResponse>('/outsource/shipments/batch', { orders }),
  /** 合并发货（跨订单/跨客户生成一张发货单） */
  createMergedShipment: (items: { process_id: number; quantity: number }[]) =>
    post<Shipment>('/outsource/shipments/merged', { items }),
  /** 发货单明细 */
  shipmentDetail: (id: number) => get<Shipment>(`/outsource/shipments/${id}`),
  /** 确认收货（贝乐账号） */
  receiveShipment: (id: number) => post<ShipmentReceiveResponse>(`/outsource/shipments/${id}/receive`)
}
