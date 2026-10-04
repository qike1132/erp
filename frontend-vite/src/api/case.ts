/**
 * 皮套管理 API — 与 fastapi_app/api/v1/endpoints/case_endpoint.py 契约一一对应。
 * 主件与配件同为 SKU；出入库统一为一张流水（direction 区分方向）。
 */
import { get, post, put, del, upload, download } from './request'

// ===== 共享类型 =====

/** 皮套 SKU 搜索项（GET /cases/search） */
export interface CaseSearchItem {
  id: number
  name: string
  barcode: string
  current_stock: number
  parent_id: number | null
}

/** 产品列表项（GET /cases/products）：附配件数，供「有配件/无配件」筛选 */
export interface CaseProduct {
  id: number
  name: string
  barcode: string
  part_count: number
  has_parts: boolean
}

export interface CaseProductListResponse {
  products: CaseProduct[]
  total: number
  page: number
  per_page: number
  pages: number
}

/** 客户下拉选项 */
export interface CustomerOption {
  value: string
  label: string
}

/** 皮套 SKU（主件或配件） */
export interface CaseItem {
  id: number
  name: string
  barcode: string
  image: string
  unit: string
  product_id: number | null
  parent_id: number | null
  qty_per_set: number
  initial_stock: number
  current_stock: number
  total_in: number
  total_out: number
}

export interface CaseItemListResponse {
  items: CaseItem[]
  total: number
  page: number
  per_page: number
  pages: number
}

/** 出入库流水 */
export interface CaseMovement {
  id: number
  case_id: number
  case_name: string
  case_barcode: string
  direction: 'in' | 'out'
  movement_no: string
  quantity: number
  customer: string
  movement_date: string
  note: string
  create_time: string
}

export interface CaseMovementListResponse {
  movements: CaseMovement[]
  total: number
  pages: number
  current_page: number
}

/** 新增/批量出入库请求体 */
export interface CaseMovementPayload {
  case_id: number
  direction: 'in' | 'out'
  quantity: number
  movement_date?: string
  customer?: string
  note?: string
}

export interface CaseMovementCreateResponse {
  success: boolean
  movement_no: string
  id: number
}

export interface CaseBatchFailedItem {
  index: number
  error: string
}

export interface CaseBatchMovementResponse {
  success: boolean
  results: Record<string, unknown>[]
  failed: CaseBatchFailedItem[]
}

/** 库存分组节点（主件 + 其配件） */
export interface CaseInventoryNode extends CaseItem {
  children: CaseItem[]
}

export interface CaseInventoryStats {
  total_items: number
  total_stock: number
  total_in: number
  total_out: number
}

export interface CaseInventoryResponse {
  inventory: CaseInventoryNode[]
  total: number
  page: number
  per_page: number
  pages: number
  stats: CaseInventoryStats | null
}

export interface CaseActionResponse {
  success: boolean
  message: string
}

/** 某产品的皮套树：主件 + 配件 */
export interface CaseTree {
  main: CaseItem
  parts: CaseItem[]
}

// ===== 请求参数（用 type 而非 interface：get() 的 params 形参是 Record<string, unknown>）=====
export type CaseItemListParams = {
  page?: number
  per_page?: number
  search?: string
  parent_id?: number
  roots_only?: boolean
}

export type CaseMovementListParams = {
  page?: number
  per_page?: number
  case_id?: number
  direction?: 'in' | 'out'
  customer?: string
  start_date?: string
  end_date?: string
  quantity_min?: number
  quantity_max?: number
}

export type CaseInventoryParams = {
  page?: number
  per_page?: number
  search?: string
}

export type CaseProductListParams = {
  page?: number
  per_page?: number
  search?: string
  has_parts?: 'all' | 'yes' | 'no'
}

export type CaseExportParams = {
  scope: 'movements' | 'inventory'
  case_id?: number
  direction?: 'in' | 'out'
  customer?: string
  start_date?: string
  end_date?: string
  search?: string
}

// ===== API =====
export const caseApi = {
  /** SKU 搜索（名称/69码），附当前库存 */
  search: (q: string) => get<CaseSearchItem[]>('/cases/search', { q }),

  // --- SKU 主档 ---
  items: (params?: CaseItemListParams) => get<CaseItemListResponse>('/cases/items', params),
  createItem: (data: Record<string, unknown>) => post<{ id: number }>('/cases/items', data),
  updateItem: (id: number, data: Record<string, unknown>) => put<CaseActionResponse>(`/cases/items/${id}`, data),
  deleteItem: (id: number) => del<CaseActionResponse>(`/cases/items/${id}`),

  // --- 库存汇总（主件分组） ---
  inventory: (params: CaseInventoryParams) => get<CaseInventoryResponse>('/cases/inventory', params),

  /** 产品列表（皮套设置）：全部产品 + 配件数，按有无配件筛选 */
  products: (params?: CaseProductListParams) => get<CaseProductListResponse>('/cases/products', params),

  /** 取某产品的皮套主件（不存在则自动创建）+ 其配件 */
  forProduct: (productId: number) => post<CaseTree>('/cases/for-product', { product_id: productId }),

  // --- 出入库流水 ---
  movements: (params?: CaseMovementListParams) => get<CaseMovementListResponse>('/cases/movements', params),
  getMovement: (id: number) => get<CaseMovement>(`/cases/movements/${id}`),
  createMovement: (data: CaseMovementPayload) => post<CaseMovementCreateResponse>('/cases/movements', data),
  batchMovements: (movements: CaseMovementPayload[]) =>
    post<CaseBatchMovementResponse>('/cases/movements/batch', { movements }),
  updateMovement: (id: number, data: Record<string, unknown>) => put<CaseActionResponse>(`/cases/movements/${id}`, data),
  deleteMovement: (id: number) => del<CaseActionResponse>(`/cases/movements/${id}`),

  // --- Excel 批量导入（batch 域） ---
  // timeout 120s：Excel 解析 + 写库常远超全局 15s，否则前端先超时、后端可能已写入
  // → 用户重试造成重复出入库（与 OCR 导入同口径，见 request.ts:upload 注释）。
  importStockins: (formData: FormData) => upload<{ success: boolean; imported?: number; message?: string }>('/batch/import-case-stockins', formData, undefined, 120000),
  importStockouts: (formData: FormData) => upload<{ success: boolean; imported?: number; message?: string }>('/batch/import-case-stockouts', formData, undefined, 120000),
  downloadTemplate: (filename: string) => download('/batch/download-template', filename),

  // --- 导出 ---
  exportXlsx: (params: CaseExportParams) =>
    download('/cases/export', params.scope === 'inventory' ? '皮套库存汇总.xlsx' : '皮套出入库流水.xlsx', params),
}
