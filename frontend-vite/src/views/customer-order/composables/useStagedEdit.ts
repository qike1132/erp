/**
 * useStagedEdit — 暂存项编辑动作域（批次 2-3 拆分自 useOrderActions）
 *
 * 承载暂存条目编辑弹窗与可用备货量查询。逻辑原样搬移。
 */
import { ref, type Ref } from 'vue'
import { auxApi } from '@/api'
import { showToast } from '@/composables/useToast'
import { QUANTITY_RANGE_MESSAGE, isQuantityOutOfRange } from './quantityRange'
import { planSplitsMessage } from './shipmentPlanRules'
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
    const source = stagedItems.value[idx]!
    // 深拷贝分批计划（2026-10-06 v2 评审 BLOCK）：数组若与暂存条目共享引用，
    // 弹窗内的增删改会原地污染暂存数据，用户点「取消」也无法回退
    const data: StagedItem = { ...source, shipmentPlans: source.shipmentPlans.map((s) => ({ ...s })) }
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
    // 分批出货计划校验（2026-10-06 v2）：行完整性 + 排满口径，
    // 与录入表单同规则同文案，否则提交时会被后端整组拒绝
    if (editStagedData.value && editStagedData.value.type === 'order') {
      const msg = planSplitsMessage(editStagedData.value.shipmentPlans, editStagedData.value.quantity)
      if (msg) {
        showToast(msg, 'warning')
        return
      }
    }
    if (editStagedIdx.value >= 0 && editStagedData.value) {
      if (editStagedData.value.deductQuantity > 0) editStagedData.value.deductStock = true
      // 落回同样深拷贝（2026-10-06 排查 INV-2）：落回若共享数组，暂存条目会与
      // 仍存活的 editStagedData 保持引用关联，任何后续原地修改都会双向外溢
      const saved = editStagedData.value
      stagedItems.value[editStagedIdx.value] = {
        ...saved,
        shipmentPlans: saved.shipmentPlans.map((s) => ({ ...s })),
      }
    }
    editStagedVisible.value = false
    // 释放编辑副本：关闭弹窗后不留持数组引用的存活对象
    editStagedData.value = null
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
