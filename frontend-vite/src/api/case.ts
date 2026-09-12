/**
 * 皮套管理 API — 与 fastapi_app/api/v1/endpoints/case_endpoint.py 契约一一对应。
 * 所有响应类型以 schemas/case.py 为准。
 */
import { get, post, put, del, upload, download } from './request'

// ===== 共享类型 =====

/** 产品搜索候选项（GET /cases/search） */
export interface CaseSearchItem {
  id: number
  name: string
  barcode: string
  current_stock: number
}

/** 客户下拉选项 */
export interface CustomerOption {
  value: string
  label: string
}

/** 入库/出库记录行（列表响应项） */
export interface CaseStockRecord {
  id: number
  stockin_no?: string
  stockout_no?: string
  stockin_date?: string
  stockout_date?: string
  customer?: string
  case_id?: number
  case_name?: string
  case_barcode?: string
  quantity: number
  note?: string
}

export interface CaseStockListResponse {
  stockins?: CaseStockRecord[]
  stockouts?: CaseStockRecord[]
  total?: number
  pages: number
  current_page: number
}

export interface CaseStockDetailResponse {
  id: number
  stockin_no?: string
  stockout_no?: string
  stockin_date?: string
  stockout_date?: string
  customer?: string
  case_id?: number
  case_name?: string
  quantity: number
  note?: string
}

export interface CaseActionResponse {
  success: boolean
  message: string
}

export interface CaseBatchFailedItem {
  index: number
  error: string
}

export interface CaseBatchStockInResponse {
  success: boolean
  message: string
  failed: CaseBatchFailedItem[]
}

export interface CaseBatchStockOutResultItem {
  success: boolean
  stockout_no?: string
  id?: number | string | null
  error?: string
}

export interface CaseBatchStockOutResponse {
  success: boolean
  results: CaseBatchStockOutResultItem[]
}

/** 暂存提交项（批量入库/出库请求体） */
export interface CaseBatchStockItemPayload {
  productId: string | number
  customer: string
  quantity: number
  stockinDate?: string
  stockoutDate?: string
  note: string
}

// ===== 库存汇总 / 流水 =====

export interface CaseInventoryItem {
  id: number
  name: string
  barcode: string
  initial_stock: number
  total_in: number
  total_out: number
  current_stock: number
}

export interface CaseInventoryStats {
  total_stock: number
  total_in: number
  total_out: number
}

export interface CaseInventorySummaryResponse {
  inventory: CaseInventoryItem[]
  total: number
  page: number
  per_page: number
  pages: number
  stats: CaseInventoryStats | null
}

export interface CaseInventoryLogItem {
  id: number
  change_type: string
  change_quantity: number
  change_date: string
  customer: string
  related_id: string
  note: string
}

export interface CaseInventoryLogsResponse {
  success: boolean
  logs: CaseInventoryLogItem[]
  pagination: { page: number; pages: number; total: number } | null
}

// ===== 入库/出库请求参数 =====

// 用 type 而非 interface：get() 的 params 形参是 Record<string, unknown>，
// 接口缺少隐式索引签名会导致赋值失败。
export type CaseStockListParams = {
  page?: number
  per_page?: number
  customer?: string
  start_date?: string
  end_date?: string
}

export interface CaseStockUpdatePayload {
  customer?: string
  quantity?: number
  note?: string
  stockin_date?: string
  stockout_date?: string
}

// ===== API =====

export const caseApi = {
  /** 产品搜索（名称/69码），返回附当前库存 */
  search: (q: string) => get<CaseSearchItem[]>('/cases/search', { q }),

  // --- 入库 ---
  stockins: (params?: CaseStockListParams) => get<CaseStockListResponse>('/cases/in/list', params),
  getStockin: (id: number) => get<CaseStockDetailResponse>(`/cases/in/${id}`),
  updateStockin: (id: number, data: CaseStockUpdatePayload) => put<CaseActionResponse>(`/cases/in/${id}`, data),
  deleteStockin: (id: number) => del<CaseActionResponse>(`/cases/in/${id}`),
  batchStockin: (stockins: CaseBatchStockItemPayload[]) =>
    post<CaseBatchStockInResponse>('/cases/in/batch', { stockins }),

  // --- 出库 ---
  stockouts: (params?: CaseStockListParams) => get<CaseStockListResponse>('/cases/out/list', params),
  getStockout: (id: number) => get<CaseStockDetailResponse>(`/cases/out/${id}`),
  updateStockout: (id: number, data: CaseStockUpdatePayload) => put<CaseActionResponse>(`/cases/out/${id}`, data),
  deleteStockout: (id: number) => del<CaseActionResponse>(`/cases/out/${id}`),
  batchStockout: (stockouts: CaseBatchStockItemPayload[]) =>
    post<CaseBatchStockOutResponse>('/cases/out/batch', { stockouts }),

  // --- Excel 批量导入（batch 域） ---
  importStockins: (formData: FormData) => upload<{ success: boolean; imported?: number; message?: string }>('/batch/import-case-stockins', formData),
  importStockouts: (formData: FormData) => upload<{ success: boolean; imported?: number; message?: string }>('/batch/import-case-stockouts', formData),
  downloadTemplate: (filename: string) => download('/batch/download-template', filename),

  // --- 库存汇总 / 流水 ---
  inventorySummary: (params: { page: number; per_page: number; search?: string }) =>
    get<CaseInventorySummaryResponse>('/cases/inventory-summary', params),
  inventoryLogs: (caseId: number, params: { page: number; per_page: number; type?: string; start_date?: string; end_date?: string }) =>
    get<CaseInventoryLogsResponse>(`/cases/inventory-logs/${caseId}`, params),
}
