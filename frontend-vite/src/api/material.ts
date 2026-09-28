import { get, post, postDownload } from './request'
import type { ApiResponse, QueryParams } from '@/types'

/** 来料登记物料项（对齐后端 MaterialRegistrationItem） */
export interface RegItem {
  id: number
  material_name: string
  specification: string
  material_category: string
  ordered_quantity: number | string
  received_quantity: number | string
  remaining_quantity: number | string
  progress: number
  unit: string
  supplier_name?: string
}

/** SKU 明细（多 SKU 订单时按 SKU 分行显示） */
export interface RegSkuItem {
  product_name: string
  barcode: string
  quantity: number
}

/** 来料登记记录（对齐后端 RegistrationListResponse.registrations） */
export interface Registration {
  id: number
  purchase_order_no: string
  supplier_name: string
  supplier_names?: string[]
  po_create_time?: string
  customer_name: string
  product_name: string
  product_quantity: number
  items: RegItem[]
  sku_items?: RegSkuItem[]
  status: string
  progress: number
  total_ordered: number | string
  total_received: number | string
  update_time?: string
}

/** 后端供应商聚合接口响应（snake_case，对齐 SupplierDetailResponse schema） */
export interface SupplierDetailApiResponse {
  supplier_groups: Array<{
    supplier_name: string
    items: Array<{
      name: string
      ordered: number
      received: number
      remaining: number
      pct: number
      sub_items: Array<{ id: number; ordered: number; received: number }>
      unit: string
      spec: string
    }>
    total_ordered: number
    total_received: number
    pct: number
  }>
  total_ordered: number
  total_received: number
  total_pct: number
}

export const materialApi = {
  overview: () => get<Record<string, unknown>>('/material-registrations/stats/overview'),
  trend: (days: number) => get<Record<string, unknown>>('/material-registrations/stats/trend', { days }),
  distribution: () => get<Record<string, unknown>>('/material-registrations/stats/distribution'),
  registrations: (params?: QueryParams) => get<{ registrations: Registration[]; pages?: number; total_pages?: number; total?: number }>('/material-registrations/registrations', params),
  registrationDetail: (id: number) => get<{ registration?: Registration }>(`/material-registrations/registrations/${id}`),
  supplierDetail: (orderNo: string) => get<SupplierDetailApiResponse>('/material-registrations/supplier-detail', { order_no: orderNo }),
  history: (params?: QueryParams) => get<{ registrations: Registration[]; pages?: number; total_pages?: number; total?: number }>('/material-registrations/history', params),
  receive: (id: number, data: { received_quantity: number; remark?: string }) => post<ApiResponse & { auto_completed?: boolean }>(`/material-registrations/items/${id}/receive`, data),
  export: (params?: QueryParams, filename = '来料登记汇总.xlsx') =>
    postDownload('/material-registrations/export', params ?? {}, filename),
}
