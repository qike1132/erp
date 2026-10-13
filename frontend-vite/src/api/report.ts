import { get } from './request'
import type { QueryParams } from '@/types'

/**
 * 报表流水行（与后端 `ReportLogItem` 对齐）。
 *
 * 2026-10-13：五个 tab 统一到「一行一记录」——四类非订单 tab 带 record_id/record_no；
 * 订单 tab 为母行-明细（一行 = 订单×SKU），带 order_id/item_id/item_count/order_total_qty，
 * 前端按 order_id 聚成母行 + 展开的 SKU 子行。
 */
export interface ReportLogItem {
  record_id: number
  record_no: string
  /** 退货原因（与 note 分开） */
  reason: string
  /** 抵扣行编辑所需：毛量 / 合并展示备注 */
  gross_quantity: number
  note_display: string
  order_id: number
  order_no: string
  item_id: number
  item_count: number
  order_total_qty: number
  item_note: string
  order_date: string
  stockin_date: string
  stockout_date: string
  deduction_time: string
  return_date: string
  customer: string
  product_name: string
  product_barcode: string
  quantity: number
  note: string
  order_note: string
}

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
  returnLogs: (params?: QueryParams) => get<ReportLogResponse>('/reports/return-logs', params),
}
