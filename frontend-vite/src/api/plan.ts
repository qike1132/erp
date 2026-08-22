import { get, post, put, del, upload, download } from './request'
import type { StagingOrder, ShipmentRecord, QueryParams } from '@/types'

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
  dayDetails: (params?: QueryParams) => get<Record<string, unknown>>('/plans/day-details', params),
  customerSummary: (params?: QueryParams) => get<Record<string, unknown>>('/plans/customer-summary', params),
  inventoryCompare: (params?: QueryParams) => get<Record<string, unknown>>('/plans/inventory-compare', params),
  shipmentProgress: (planId: number) => get<ShipmentRecord[]>(`/plans/shipment/progress?plan_id=${planId}`),
  shipmentRecords: (planId: number) => get<ShipmentRecord[]>(`/plans/shipment/records?plan_id=${planId}`),
  upload: (formData: FormData) => upload('/plans/upload', formData),
  stagingList: () => get<StagingOrder[]>('/plans/staging/list'),
  stagingValidate: () => post<{ valid: boolean; errors?: string[] }>('/plans/staging/validate'),
  stagingConfirm: (data: Record<string, unknown>) => post('/plans/staging/confirm', data),
  stagingClear: () => del('/plans/staging/clear'),
  validateBarcode: (q: string) => get<{ valid: boolean }>('/plans/validate-barcode', { q }),
  downloadTemplate: () => download('/plans/template/download', '出货计划导入模板.xlsx'),
}
