/**
 * useOrderActions — 订单动作编排 Hook（聚合器）
 *
 * 2026-10-06 记录查询 tab 收敛至报表页：useOrderDetailEdit / useOrderDelete /
 * useStockinEdit 三个动作域随记录查询功能迁至 views/report/composables，
 * 本聚合器只保留录入侧（暂存项/暂存编辑/Excel 导入）。签名相应去掉 fetchOrders
 * 参数（原供三个迁出动作域刷新记录列表用）。
 */
import type { Reactive, ComputedRef } from 'vue'
import type { FormState } from './types'
import { useStagedItems, genUid } from './useStagedItems'
import { useStagedEdit } from './useStagedEdit'
import { useOrderImport } from './useOrderImport'

export function useOrderActions(
  _form: Reactive<FormState>,
  isOrder: ComputedRef<boolean>,
) {
  const staged = useStagedItems()
  const stagedEdit = useStagedEdit(staged.stagedItems)
  const orderImport = useOrderImport(staged.stagedItems, isOrder)

  return {
    ...staged,
    ...stagedEdit,
    ...orderImport,
    genUid,
  }
}
