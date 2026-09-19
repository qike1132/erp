/**
 * useStagedEdit — 暂存项编辑动作域（批次 2-3 拆分自 useOrderActions）
 *
 * 承载暂存条目编辑弹窗与可用备货量查询。逻辑原样搬移。
 */
import { ref, type Ref } from 'vue'
import { auxApi } from '@/api'
import { showToast } from '@/composables/useToast'
import { QUANTITY_RANGE_MESSAGE, isQuantityOutOfRange } from './quantityRange'
import type { StagedItem, AvailableStockinItem } from './types'

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
      auxApi.availableStockins({ product_id: data.productId, customer: data.customer })
        .then((res) => {
          const items: AvailableStockinItem[] = Array.isArray(res) ? res : []
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
    // 提交前最终校验：输入框的实时标红可能被用户绕过（回车/直接点保存），
    // 这里再挡一次，避免越界数量进入暂存区。
    if (editStagedData.value && isQuantityOutOfRange(editStagedData.value.quantity)) {
      showToast(QUANTITY_RANGE_MESSAGE, 'warning')
      return
    }
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
