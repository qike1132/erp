import { useApiMutation } from '@/composables/useApiMutation'
import { orderBatchApi } from '@/api'

export function useBatchActions() {
  const assignMutation = useApiMutation(
    (vars: { orderIds: number[]; batchNo: string }) =>
      orderBatchApi.batchAssign({ order_ids: vars.orderIds, batch_no: vars.batchNo }),
    { invalidateKeys: ['order-batch'], successMsg: '批次号设置成功' },
  )

  const completeMutation = useApiMutation(
    (vars: { batchNo: string }) =>
      orderBatchApi.completeBatch({ batch_no: vars.batchNo }),
    { invalidateKeys: ['order-batch'], successMsg: '批次完成操作成功' },
  )

  const updateMutation = useApiMutation(
    (vars: { orderId: number; data: { batch_no: string | null; sync_same_batch?: boolean } }) =>
      orderBatchApi.updateBatchNo(vars.orderId, vars.data),
    { invalidateKeys: ['order-batch'], successMsg: '批次号更新成功' },
  )

  async function batchAssign(orderIds: number[], batchNo: string) {
    return assignMutation.mutate({ orderIds, batchNo })
  }

  async function completeBatch(batchNo: string) {
    return completeMutation.mutate({ batchNo })
  }

  async function updateBatchNo(orderId: number, data: { batch_no: string | null; sync_same_batch?: boolean }) {
    return updateMutation.mutate({ orderId, data })
  }

  return { batchAssign, completeBatch, updateBatchNo }
}
