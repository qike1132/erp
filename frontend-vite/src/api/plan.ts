import { get, post, put, del, upload, download } from './request'
import type { StagingOrder, ShipmentRecord, QueryParams } from '@/types'

/** 暂存校验失败明细（与后端 schemas.StagingErrorItem 对齐） */
export interface StagingErrorItem {
  /** 导入批次内行序号（1 起），非 Excel 物理行号 */
  seq: number
  customer_name: string
  product_name: string
  barcode: string
  quantity: number
  plan_date: string
  message: string
}

/** POST /plans/upload：解析 Excel 并写入暂存区（尚未进入正式表） */
export interface PlanUploadResult {
  success: boolean
  batch_id: string
  total: number
  success_count: number
  error_count: number
  errors: string[]
  is_async: boolean
  detected_month: string | null
}

/** POST /plans/staging/validate：校验暂存区数据 */
export interface PlanStagingValidateResult {
  success: boolean
  total: number
  valid_count: number
  error_count: number
  errors: StagingErrorItem[]
}

/** POST /plans/staging/confirm：确认暂存数据写入正式表 */
export interface PlanStagingConfirmResult {
  success: boolean
  created_plans: { plan_id: number; plan_no: string }[]
  created_count: number
  skipped_count: number
}

/** 导入链路超时：解析 + 校验 + 落库可能远超全局 15s */
export const PLAN_IMPORT_TIMEOUT = 120_000

export const planApi = {
  list: (params?: QueryParams) => get<Record<string, unknown>[]>('/plans/list', params),
  detail: (id: number) => get<Record<string, unknown>>(`/plans/detail/${id}`),
  create: (data: Record<string, unknown>) => post<Record<string, unknown>>('/plans/create', data),
  update: (id: number, data: Record<string, unknown>) => put<Record<string, unknown>>(`/plans/edit/${id}`, data),
  delete: (id: number) => del(`/plans/delete/${id}`),
  updateDetail: (detailId: number, data: Record<string, unknown>) => put(`/plans/details/${detailId}`, data),
  deleteDetail: (detailId: number) => del(`/plans/details/${detailId}`),
  addDetails: (planId: number, details: Record<string, unknown>[]) => post(`/plans/details/add?plan_id=${planId}`, { details }),
  monthly: (params?: QueryParams) => get<Record<string, unknown>>('/plans/monthly', params),
  monthlyAggregated: (params?: QueryParams) => get<Record<string, unknown>>('/plans/monthly-aggregated', params),
  customerSummary: (params?: QueryParams) => get<Record<string, unknown>>('/plans/customer-summary', params),
  inventoryCompare: (params?: QueryParams) => get<Record<string, unknown>>('/plans/inventory-compare', params),
  shipmentProgress: (planId: number) => get<ShipmentRecord[]>(`/plans/shipment/progress?plan_id=${planId}`),
  upload: (formData: FormData) => upload<PlanUploadResult>('/plans/upload', formData, undefined, PLAN_IMPORT_TIMEOUT),
  stagingList: () => get<StagingOrder[]>('/plans/staging/list'),
  stagingValidate: () => post<PlanStagingValidateResult>('/plans/staging/validate'),
  stagingConfirm: (data: { batch_id?: string; selected_ids?: number[] | null }) => post<PlanStagingConfirmResult>('/plans/staging/confirm', data),
  stagingClear: () => del('/plans/staging/clear'),
  validateBarcode: (q: string) => get<{ valid: boolean }>('/plans/validate-barcode', { q }),
  downloadTemplate: () => download('/plans/template/download', '出货计划导入模板.xlsx'),
}
