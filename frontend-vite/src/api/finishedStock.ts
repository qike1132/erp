import { download, get, put } from './request'
import type { ApiResponse, BatchAvailable, FinishedStockSummary } from '@/types'

/**
 * 成品库存（批次级）API — 只读聚合。
 *
 * 真相源与 /stock 同源（daily_production_record 包装部入库 + stock_out 批次扣减）。
 */
export const finishedStockApi = {
  /** 按 客户/产品/批次 聚合成品库存（分页 + 客户列表） */
  summary: (params?: {
    customer?: string
    product?: string
    batch_no?: string
    page?: number
    per_page?: number
  }) => get<FinishedStockSummary>('/finished-stock/summary', params),

  /** 某产品的批次可用量列表（供 /stock-out 录入 SKU 后带出批次选择） */
  batches: (productId: number, customer?: string) =>
    get<ApiResponse<BatchAvailable[]>>('/finished-stock/batches', {
      product_id: productId,
      customer,
    }),

  /** 导出当前筛选（客户 + 搜索词）的成品库存 */
  export: (params?: { customer?: string; product?: string }) =>
    download('/finished-stock/export', '成品库存.xlsx', params),

  /** 页面级备注 UPSERT：键 (客户,产品,批次) 一行一条；清空即删除 */
  saveRemark: (data: {
    customer_name: string
    product_id: number
    batch_no: string
    remark: string
  }) => put<{ success?: boolean; remark?: string }>('/finished-stock/remark', data),
}
