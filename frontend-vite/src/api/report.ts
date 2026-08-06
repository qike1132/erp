import { get } from './request'
import type { QueryParams } from '@/types'

/** 报表流水响应（与后端 ReportResponse 对齐） */
interface ReportLogResponse {
  success: boolean
  logs: Record<string, unknown>[]
  stats: Record<string, unknown>
  pagination: { pages?: number; total?: number; [key: string]: unknown }
}

export const reportApi = {
  orderLogs: (params?: QueryParams) => get<ReportLogResponse>('/reports/order-logs', params),
  stockinLogs: (params?: QueryParams) => get<ReportLogResponse>('/reports/stockin-logs', params),
  stockoutLogs: (params?: QueryParams) => get<ReportLogResponse>('/reports/stockout-logs', params),
  deductionLogs: (params?: QueryParams) => get<ReportLogResponse>('/reports/deduction-logs', params),
  customerNames: () => get<string[]>('/reports/customer-names'),
}
