import { get, post, put } from './request'
import type { OrderBatchItem, BatchNoUpdatePayload, BatchAssignPayload, BatchCompletePayload, QueryParams } from '@/types'

export const orderBatchApi = {
  orders: (params?: QueryParams) => get<{ success: boolean; data: OrderBatchItem[]; total: number }>('/order-batch/orders', params),
  updateBatchNo: (orderId: number, data: BatchNoUpdatePayload) => put<{ success: boolean; message: string; updated_count: number }>(`/order-batch/orders/${orderId}/batch-no`, data),
  batchAssign: (data: BatchAssignPayload) => post<{ success: boolean; message: string; updated_count: number }>('/order-batch/orders/batch-assign', data),
  // 字段与 types/api.d.ts::BatchCompleteResponse 一致（completed_stockins = 归档的备货条数）
  completeBatch: (data: BatchCompletePayload) => post<{ success: boolean; message: string; completed_count: number; completed_stockins: number; failed_orders: unknown[] }>('/order-batch/batch/complete', data),
  history: (params?: QueryParams) => get<{ success: boolean; data: OrderBatchItem[]; total: number }>('/order-batch/history', params),
  whitelist: () => get<{ customers: string[] }>('/order-batch/whitelist'),
  setWhitelist: (customers: string[]) => put<{ customers: string[] }>('/order-batch/whitelist', { customers }),
}
