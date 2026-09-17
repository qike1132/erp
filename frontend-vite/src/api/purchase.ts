import { get, post, put, del, postDownload } from './request'
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
  /** 后端 `MaterialCalcRow.name`（与 material_name 同值，保留以兼容两种口径） */
  name?: string
  supplier_name: string
  material_name: string
  material_code?: string
  specification?: string
  total_quantity: number
  unit: string
}

/**
 * 按「产品 × 作用域(角色)」分块的物料计算结果（对应后端
 * `schemas/purchase_center.py:MaterialCalcScopeGroup`）。
 *
 * `role_id === null` 表示产品级**默认 BOM**，后端保证**恒为首块**；块顺序由后端定死，
 * 前端不得重排（架构 §7#2）。`quantity` 为该产品订单总数量，各作用域共用、**不分摊**。
 * 每个分类的行内 `total_quantity` **已是结果**，前端不要再乘/除。
 */
export interface MaterialCalcScopeGroup {
  product_id: number
  product_name: string
  role_id: number | null
  role_name: string
  quantity: number
  filling: MaterialCalcRow[]
  fabric: MaterialCalcRow[]
  accessory: MaterialCalcRow[]
  packaging: MaterialCalcRow[]
}

export interface MaterialCalcResult {
  success: boolean
  // 扁平字段：全作用域合并口径（旧口径，保留不变）
  filling: MaterialCalcRow[]
  fabric: MaterialCalcRow[]
  accessory: MaterialCalcRow[]
  packaging: MaterialCalcRow[]
  // 追加：按「产品 × 作用域(角色)」分块（旧后端可能缺失 → 前端回退扁平渲染, A-5）
  groups?: MaterialCalcScopeGroup[] | null
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
  /**
   * 复制 BOM。
   * @param targetProductId 目标产品 ID
   * @param sourceProductId 源产品 ID
   * @param overwrite 是否覆盖；角色模式下仅作用于目标角色（后端已收敛作用域）
   * @param roleId 目标角色 ID；传入时物料归属到该角色，为空/省略时按源产品结构复制
   * @param roleName 目标角色名称；仅在 roleId 为空时生效，后端按名称查找或新建角色
   */
  copyBom: (targetProductId: number, sourceProductId: number, overwrite: boolean, roleId?: number | null, roleName?: string | null) =>
    post(`/purchase-center/products/${targetProductId}/copy-bom`, {
      source_product_id: sourceProductId,
      overwrite,
      ...(roleId != null ? { role_id: roleId } : {}),
      ...(roleId == null && roleName ? { role_name: roleName } : {}),
    }),
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
  // 后端返回的是三个时段的计数（dict[str, int]），不是可配置的区间定义数组
  quickFilters: () => get<{ success?: boolean; quick_filters?: Record<string, number> }>('/purchase-center/orders/completed/quick-filters'),
  suggestions: (field: string, q: string) => get<string[]>('/purchase-center/orders/completed/suggestions', { field, q }),
  factorySummary: (ids: number[]) => post<Record<string, unknown>>('/purchase-center/orders/factory-summary', { ids }),
  supplierSummary: (ids: number[]) => post<Record<string, unknown>[]>('/purchase-center/orders/supplier-summary', { ids }),
  saveFactoryEdits: (edits: Record<string, unknown>[]) => post('/purchase-center/orders/factory-summary/save', { edits }),
  summaryPrint: (ids: number[], format: string) => post<ExportResponse>('/purchase-center/orders/summary-print', { ids, format }),
  supplierSummaryExport: (ids: number[]) =>
    postDownload('/purchase-center/orders/supplier-summary-export', { ids }, ids.length > 1 ? '供应商采购订单汇总.zip' : '供应商采购订单汇总.xlsx'),
  products: (params?: QueryParams) => get<ProductListResponse>('/purchase-center/products', params),
  searchSuggestions: (q: string) => get<SearchSuggestionResponse>('/purchase-center/products/search-suggestions', { q }),
  calculate: (orders: MaterialOrderInput[]) =>
    post<MaterialCalcResult>('/purchase-center/calculate', { orders }),
}
