import { get, post, put, del } from './request'
import type { OrderItem, StagingOrder, QueryParams } from '@/types'

/** 订单列表响应（对应后端 OrderListResponse schema） */
export interface OrderListApiResponse {
  success: boolean
  data: OrderItem[]
  total: number
  page: number
  per_page: number
  /** 未确认湖北订单总数（beile-list 专用，顶部横幅） */
  unconfirmed_count?: number
}

export interface ConfirmOrderResponse {
  success: boolean
  message: string
  already_confirmed?: boolean
}

export const orderApi = {
  list: (params?: QueryParams) => get<OrderListApiResponse>('/orders/list', params),
  beileList: (params?: QueryParams) => get<OrderListApiResponse>('/orders/beile-list', params),
  detail: (id: number) => get<OrderItem>(`/orders/${id}`),
  create: (data: Partial<OrderItem>) => post<OrderItem>('/orders/create', data),
  update: (id: number, data: Partial<OrderItem>) => put<OrderItem>(`/orders/edit/${id}`, data),
  delete: (id: number) => del(`/orders/delete/${id}`),
  lock: (id: number) => post(`/orders/lock/${id}`),
  unlock: (id: number) => post(`/orders/unlock/${id}`),
  deductStock: (id: number) => post(`/orders/deduct-stock/${id}`),
  updateDeduct: (id: number, deductQuantity: number) => put(`/orders/deduct/${id}?deduct_quantity=${deductQuantity}`),
  confirmBeileOrder: (id: number) => post<ConfirmOrderResponse>(`/orders/${id}/confirm`),
  confirmBeileStockin: (id: number) => post<ConfirmOrderResponse>(`/orders/stockin/${id}/confirm`),
  staging: {
    add: (data: Partial<StagingOrder>) => post<StagingOrder>('/staging-orders/add', data),
    list: () => get<StagingOrder[]>('/staging-orders/list'),
    delete: (id: number) => del(`/staging-orders/${id}`),
    confirm: () => post('/staging-orders/confirm'),
  },
}
