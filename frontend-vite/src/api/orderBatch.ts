import { get, post, put } from './request'
import type { OrderBatchItem, BatchNoUpdatePayload, BatchAssignPayload, BatchCompletePayload, QueryParams } from '@/types'

export const orderBatchApi = {
  orders: (params?: QueryParams) => get<{ success: boolean; data: OrderBatchItem[]; total: number }>('/order-batch/orders', params),
  updateBatchNo: (orderId: number, data: BatchNoUpdatePayload) => put<{ success: boolean; message: string; updated_count: number }>(`/order-batch/orders/${orderId}/batch-no`, data),
  batchAssign: (data: BatchAssignPayload) => post<{ success: boolean; message: string; updated_count: number }>('/order-batch/orders/batch-assign', data),
  completeBatch: (data: BatchCompletePayload) => post<{ success: boolean; message: string; completed_count: number; failed_orders: unknown[] }>('/order-batch/batch/complete', data),
  history: (params?: QueryParams) => get<{ success: boolean; data: OrderBatchItem[]; total: number }>('/order-batch/history', params),
  whitelist: () => get<{ customers: string[] }>('/order-batch/whitelist'),
  setWhitelist: (customers: string[]) => put<{ customers: string[] }>('/order-batch/whitelist', { customers }),
}
