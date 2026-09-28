/**
 * useOrderDelete — 订单删除动作域
 *
 * 从 CustomerOrderView 内联实现搬移，逻辑原样保留：
 * 删除确认 → 调接口 → 失效库存派生查询缓存 → 刷新列表。
 */
import { useQueryClient } from '@tanstack/vue-query'
import { orderApi } from '@/api'
import { showToast } from '@/composables/useToast'
import { getErrorMessage } from '@/types/errors'
import { invalidateStockDataQueries } from '@/utils/queryKeys'
import type { OrderRecord } from './types'

type ConfirmDialogApi = {
  confirm: (msg: string, subMsg?: string, dialogType?: 'danger' | 'warning') => Promise<boolean>
}

export function useOrderDelete(
  fetchOrders: () => Promise<void>,
  confirmDialog: ConfirmDialogApi,
) {
  const queryClient = useQueryClient()

  async function handleDeleteOrder(record: OrderRecord) {
    const orderNo = record.order_no || record.stockin_no || ''
    const ok = await confirmDialog.confirm(
      `确定删除订单「${orderNo}」吗？`,
      '删除将级联清理订单流程节点、状态变更、审批参与者及关联记录；系统会先备份订单数据，误删后可联系管理员恢复。此操作不可撤销。',
      'danger',
    )
    if (!ok) return
    try {
      const res = await orderApi.delete(record.id) as { message?: string }
      showToast(res?.message || '订单删除成功', 'success')
      // 删除订单会同时改变库存视图（order_agg/country_agg 过滤 is_deleted）：
      // 必须失效派生查询缓存，否则 /stock 在 staleTime 内仍展示删除前的库存数据。
      invalidateStockDataQueries(queryClient)
      fetchOrders()
    } catch (e: unknown) {
      showToast(getErrorMessage(e, '删除订单失败'), 'error')
    }
  }

  return { handleDeleteOrder }
}
