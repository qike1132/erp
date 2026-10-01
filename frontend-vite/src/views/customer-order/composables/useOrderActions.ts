/**
 * useOrderActions — 订单动作编排 Hook（聚合器）
 *
 * 批次 2-3 拆分：实现按动作域迁移至
 *   useStagedItems（暂存项状态/删除/批量提交）
 *   useStagedEdit（暂存项编辑弹窗/可用备货量）
 *   useOrderImport（Excel 模板/选择/拖拽/导入）
 *   useOrderDetailEdit（详情弹窗/保存/抵扣重试）
 *   useStockinEdit（记录查询里备货行的编辑/删除，2026-10-01）
 * 本文件保持原签名与返回形状不变，消费方零改动。
 */
import type { Reactive, ComputedRef } from 'vue'
import type { FormState } from './types'
import { useStagedItems, genUid } from './useStagedItems'
import { useStagedEdit } from './useStagedEdit'
import { useOrderImport } from './useOrderImport'
import { useOrderDetailEdit } from './useOrderDetailEdit'
import { useOrderDelete } from './useOrderDelete'
import { useStockinEdit } from './useStockinEdit'

export function useOrderActions(
  _form: Reactive<FormState>,
  isOrder: ComputedRef<boolean>,
  fetchOrders: () => Promise<void>,
) {
  const staged = useStagedItems()
  const stagedEdit = useStagedEdit(staged.stagedItems)
  const orderImport = useOrderImport(staged.stagedItems, isOrder)
  const detailEdit = useOrderDetailEdit(fetchOrders)
  const orderDelete = useOrderDelete(fetchOrders, staged.confirmDialog)
  const stockinEdit = useStockinEdit(fetchOrders, staged.confirmDialog)

  return {
    ...staged,
    ...stagedEdit,
    ...orderImport,
    ...detailEdit,
    ...orderDelete,
    ...stockinEdit,
    genUid,
  }
}
