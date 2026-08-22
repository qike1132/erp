/**
 * useStagedEdit — 暂存项编辑动作域（批次 2-3 拆分自 useOrderActions）
 *
 * 承载暂存条目编辑弹窗与可用备货量查询。逻辑原样搬移。
 */
import { ref, type Ref } from 'vue'
import { get } from '@/api/request'
import type { StagedItem, AvailableStockinItem } from './types'

/** /aux/available-stockins 响应（兼容数组与 { stockins } / { items } 包裹两种结构） */
type AvailableStockinsResponse = { stockins?: AvailableStockinItem[]; items?: AvailableStockinItem[] } | AvailableStockinItem[]

export function useStagedEdit(stagedItems: Ref<StagedItem[]>) {
  const editStagedVisible = ref(false)
  const editStagedIdx = ref(-1)
  const editStagedData = ref<StagedItem | null>(null)
  const editAvailableStock = ref(0)

  function openEditStaged(uid: string) {
    const idx = stagedItems.value.findIndex((i) => i.uid === uid)
    if (idx < 0) return
    editStagedIdx.value = idx
    const data: StagedItem = { ...stagedItems.value[idx]! }
    editStagedData.value = data
    editStagedVisible.value = true
    if (data.type === 'order' && data.productId && data.customer) {
      get<AvailableStockinsResponse>('/aux/available-stockins', {
        product_id: data.productId,
        customer: data.customer,
      })
        .then((res) => {
          const items: AvailableStockinItem[] = Array.isArray(res) ? res : (res.stockins ?? res.items ?? [])
          editAvailableStock.value = items.reduce(
            (s: number, i: AvailableStockinItem) => s + (i.available ?? i.quantity - (i.deducted || 0)),
            0,
          )
        })
        .catch(() => {
          editAvailableStock.value = 0
        })
    }
  }
  function saveEditStaged() {
    if (editStagedIdx.value >= 0 && editStagedData.value) {
      if (editStagedData.value.deductQuantity > 0) editStagedData.value.deductStock = true
      stagedItems.value[editStagedIdx.value] = { ...editStagedData.value }
    }
    editStagedVisible.value = false
  }

  return {
    editStagedVisible,
    editStagedIdx,
    editStagedData,
    editAvailableStock,
    openEditStaged,
    saveEditStaged,
  }
}
