import { get } from './request'
import type { QueryParams, PickRequired } from '@/types'
import type { ReportLogItem as GenReportLogItem } from '@/types/api'

/**
 * 报表流水行（与后端 `ReportLogItem` 对齐）。
 *
 * 2026-10-13：五个 tab 统一到「一行一记录」——四类非订单 tab 带 record_id/record_no；
 * 订单 tab 为母行-明细（一行 = 订单×SKU），带 order_id/item_id/item_count/order_total_qty，
 * 前端按 order_id 聚成母行 + 展开的 SKU 子行。
 */
export type ReportLogItem = PickRequired<GenReportLogItem, 'record_id' | 'record_no' | 'reason' | 'gross_quantity' | 'note_display' | 'order_id' | 'order_no' | 'item_id' | 'item_count' | 'order_total_qty' | 'item_note' | 'order_date' | 'stockin_date' | 'stockout_date' | 'deduction_time' | 'return_date' | 'customer' | 'product_name' | 'product_barcode' | 'quantity' | 'note' | 'order_note'> // reason 是退货原因（与 note 分开）；gross_quantity/note_display 供抵扣行编辑

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
