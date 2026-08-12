import { get, post, put, del, download, postDownload } from './request'
import type {
  Product, PurchaseOrder, UnprocessedOrder, QueryParams, ExportResponse,
} from '@/types'

// === 物料计算器相关类型（与后端 schemas/purchase_center.py 对齐）===
export interface MaterialCalcProduct {
  id: number
  name: string
  barcode?: string | null
  has_bom: boolean
}

export interface MaterialCalcRow {
  supplier_name: string
  material_name: string
  material_code?: string
  specification?: string
  total_quantity: number
  unit: string
}

export interface MaterialCalcResult {
  success: boolean
  filling: MaterialCalcRow[]
  fabric: MaterialCalcRow[]
  accessory: MaterialCalcRow[]
  packaging: MaterialCalcRow[]
  total_categories?: Record<string, number> | null
  message?: string | null
}

export interface MaterialOrderInput {
  product_id: number
  quantity: number
}

export interface ProductListResponse {
  success: boolean
  products: MaterialCalcProduct[]
  total: number
  pages: number
  current_page: number
}

export interface SearchSuggestionResponse {
  success: boolean
  suggestions: MaterialCalcProduct[]
}

// BOM 相关接口（从 productApi 迁移，属于采购中心域）
export const bomApi = {
  loadBom: (productId: number) => get<Record<string, unknown>>(`/purchase-center/product/${productId}/bom`),
  saveBom: (productId: number, bomData: Record<string, unknown>) => post(`/purchase-center/product/${productId}/bom`, bomData),
  searchProductsForBom: (keyword: string) => get<Product[]>('/purchase-center/products/search', { keyword }),
  bomPreview: (productId: number) => get<Record<string, unknown>>(`/purchase-center/products/${productId}/bom-preview`),
  copyBom: (targetProductId: number, sourceProductId: number, overwrite: boolean) =>
    post(`/purchase-center/products/${targetProductId}/copy-bom`, { source_product_id: sourceProductId, overwrite }),
}

export const purchaseApi = {
  orders: (params?: QueryParams) => get<{ orders: PurchaseOrder[]; total: number; pages: number; current_page: number }>('/purchase-center/orders', params),
  unprocessedOrders: (params?: { page?: number; per_page?: number }) => get<{ orders: UnprocessedOrder[]; total: number; pages: number; current_page: number }>('/purchase-center/unprocessed-orders', params),
  completeOrder: (id: number) => post(`/purchase-center/orders/complete`, { order_id: id }),
  batchComplete: (ids: number[]) => post('/purchase-center/orders/batch-complete', { ids }),
  deleteOrder: (id: number) => del(`/purchase-center/orders/${id}`),
  batchDelete: (ids: number[]) => post('/purchase-center/orders/batch-delete', { ids }),
  updateOrder: (id: number, data: Partial<PurchaseOrder>) => put(`/purchase-center/orders/${id}`, data),
  oneClickGenerate: (data: { composite_ids: string[] }) => post<{ success: boolean; message?: string; created_count?: number; orders?: { id: number; order_no: string }[]; idempotent?: boolean }>('/purchase-center/orders/one-click-generate', data),
  orderDetail: (id: number) => get<{ success: boolean; order?: PurchaseOrder; message?: string }>(`/purchase-center/orders/${id}`),
  completed: (params?: QueryParams) => get<{ orders: PurchaseOrder[]; total: number; pages: number; total_pages?: number }>('/purchase-center/orders/completed', params),
  exportCompleted: (params?: QueryParams) => post<ExportResponse>('/purchase-center/orders/completed/export', params),
  quickFilters: () => get<{ success?: boolean; quick_filters?: { id: string; name?: string; filters?: { start_date?: string; end_date?: string } }[] }>('/purchase-center/orders/completed/quick-filters'),
  suggestions: (field: string, q: string) => get<string[]>('/purchase-center/orders/completed/suggestions', { field, q }),
  factorySummary: (ids: number[]) => post<Record<string, unknown>>('/purchase-center/orders/factory-summary', { ids }),
  supplierSummary: (ids: number[]) => post<Record<string, unknown>[]>('/purchase-center/orders/supplier-summary', { ids }),
  saveFactoryEdits: (edits: Record<string, unknown>[]) => post('/purchase-center/orders/factory-summary/save', { edits }),
  summaryPrint: (ids: number[], format: string) => post<ExportResponse>('/purchase-center/orders/summary-print', { ids, format }),
  supplierSummaryExport: (ids: number[]) => postDownload('/purchase-center/orders/supplier-summary-export', { ids }, '供应商采购订单汇总.xlsx'),
  products: (params?: QueryParams) => get<ProductListResponse>('/purchase-center/products', params),
  searchSuggestions: (q: string) => get<SearchSuggestionResponse>('/purchase-center/products/search-suggestions', { q }),
  calculate: (orders: MaterialOrderInput[]) =>
    post<MaterialCalcResult>('/purchase-center/calculate', { orders }),
}
