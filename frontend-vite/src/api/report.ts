import { download, get } from './request'
import type { QueryParams, PickRequired } from '@/types'
import type { ReportLogItem as GenReportLogItem, ReportResponse as GenReportResponse } from '@/types/api'

/**
 * 报表流水行（与后端 `ReportLogItem` 对齐）。
 *
 * 2026-10-13：五个 tab 统一到「一行一记录」——四类非订单 tab 带 record_id/record_no；
 * 订单 tab 为母行-明细（一行 = 订单×SKU），带 order_id/item_id/item_count/order_total_qty，
 * 前端按 order_id 聚成母行 + 展开的 SKU 子行。
 *
 * 字段清单**只有一份**（生成层 `@/types/api`）：本别名只把前端确实会读的键标成必填，
 * 不重抄字段类型（重抄即第二真相源，check:dto 的 R2 会拦）。
 */
export type ReportLogItem = PickRequired<GenReportLogItem, 'record_id' | 'record_no' | 'reason' | 'gross_quantity' | 'note_display' | 'order_id' | 'order_no' | 'item_id' | 'item_count' | 'order_total_qty' | 'item_note' | 'order_date' | 'stockin_date' | 'stockout_date' | 'deduction_time' | 'return_date' | 'customer' | 'product_name' | 'product_barcode' | 'quantity' | 'note' | 'order_note'> // reason 是退货原因（与 note 分开）；gross_quantity/note_display 供抵扣行编辑

/**
 * 报表流水响应（与后端 ReportResponse 对齐）。
 *
 * 2026-11-16：原实现把 logs/stats 兜底成「任意键值袋」（Record 泛型），于是 `ReportLogItem`
 * 别名写出来却**全仓无人使用**——行字段的错拼/漏取在编译期一律查不出来，后端改名也不会红。
 * 改为复用生成层 `ReportResponse`（单一真相源）后只做两处收窄：logs 换成必填的
 * `ReportLogItem[]`；pagination 收成报表页真正读的形状（ReportView/ReportTable 只读
 * pages/total，生成层给的是无形状字典）。
 */
export type ReportLogResponse = Omit<GenReportResponse, 'logs' | 'pagination'> & {
  success: boolean
  logs: ReportLogItem[]
  pagination: { pages?: number; total?: number }
}

export const reportApi = {
  orderLogs: (params?: QueryParams) => get<ReportLogResponse>('/reports/order-logs', params),
  stockinLogs: (params?: QueryParams) => get<ReportLogResponse>('/reports/stockin-logs', params),
  stockoutLogs: (params?: QueryParams) => get<ReportLogResponse>('/reports/stockout-logs', params),
  deductionLogs: (params?: QueryParams) => get<ReportLogResponse>('/reports/deduction-logs', params),
  returnLogs: (params?: QueryParams) => get<ReportLogResponse>('/reports/return-logs', params),
  /**
   * 导出流水（xlsx）。走 axios 而非直开新标签页：401 刷新、403 提示、
   * 「导出超上限」的 400 文案都依赖请求层统一处理。
   */
  exportReport: (params: Record<string, string>, filename: string) =>
    download('/reports/export', filename, params),
}
