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
  /**
   * 可用备货查询状态（2026-10-30 审计 A-M36）。
   *
   * `editAvailableStock` 同时承担「数量输入框上限」与「保存前校验基准」两个职责，
   * 因此必须能区分「查询中 / 查询成功且为 0 / 查询失败」：
   * 失败时把 0 当成真值，会让用户以为「这个产品没有可用备货」，也让保存校验
   * 无从判断；查询中也一样，0 只是个占位值。
   */
  const editStockState = ref<'idle' | 'loading' | 'ready' | 'error'>('idle')
  /**
   * 查询序号：连续打开不同暂存条目时，先发的请求可能后到，把 A 产品的可用量
   * 写到 B 产品上（用户按 A 的数字填抵扣量，后端按 B 的备货扣 → 少扣且无提示）。
   */
  let stockSeq = 0

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
    // 新的一次编辑：清空上一条目的可用量，别让「上一条的 N 件」在新弹窗里
    // 停留到响应回来为止
    editAvailableStock.value = 0
    editStockState.value = 'idle'
    const seq = ++stockSeq
    if (data.type === 'order' && data.productId && data.customer) {
      const productId = data.productId
      const customer = data.customer
      editStockState.value = 'loading'
      auxApi.availableStockins({ product_id: productId, customer: customer })
        .then((res) => {
          // 已被更新的编辑请求取代（或弹窗已切到别的条目）：丢弃，不写回
          if (seq !== stockSeq) return
          if (editStagedData.value?.productId !== productId || editStagedData.value?.customer !== customer) return
          const items: AvailableStockinItem[] = Array.isArray(res) ? res : []
          editAvailableStock.value = items.reduce(
            (s: number, i: AvailableStockinItem) => s + (i.available ?? i.quantity - (i.deducted || 0)),
            0,
          )
          editStockState.value = 'ready'
        })
        .catch(() => {
          if (seq !== stockSeq) return
          editAvailableStock.value = 0
          editStockState.value = 'error'
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
    // 抵扣数量不得超过（已确认的）可用备货（A-M36）。后端 `min(请求, 可用)`
    // 是静默截断：填 10 实际只扣 6 也不报错，用户只能事后发现少扣。
    // 查询失败时无法确认上限 —— 宁可拦住并要求重试，也不放行一个无法校验的数。
    if (editStagedData.value?.type === 'order' && (editStagedData.value.deductStock || editStagedData.value.deductQuantity > 0)) {
      const requested = editStagedData.value.deductQuantity || 0
      if (requested > 0 && editStockState.value === 'error') {
        showToast('可用备货查询失败，无法确认抵扣数量，请重试后再保存', 'warning')
        return
      }
      if (requested > 0 && editStockState.value === 'ready' && requested > editAvailableStock.value) {
        showToast(`抵扣数量 ${requested} 超过当前可用备货 ${editAvailableStock.value}，请调整后再保存`, 'warning')
        return
      }
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
    editStockState,
    openEditStaged,
    saveEditStaged,
  }
}
