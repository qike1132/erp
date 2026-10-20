import { computed, ref, watch } from 'vue'
import { purchaseApi } from '@/api'
import { showToast } from '@/composables/useToast'
import type { PurchaseOrder, PurchaseOrderItem } from '@/types'

/**
 * 采购明细单价补录状态机（订单详情弹窗用）。
 *
 * 一键生成路径没有价格来源（BOM 行无价字段），采购单价生成后恒为 0，
 * 而系统里原本没有任何录入入口 → 采购单金额与供应商金额汇总恒为 0。
 * 这里提供唯一的补录入口：逐行填草稿 → 只提交改动行 → 后端重算金额。
 *
 * 草稿只存在本地，点保存才提交；换单/重新拉详情后按新订单对象重置草稿。
 */
export function useOrderItemPrices(
  order: () => PurchaseOrder | null,
  onSaved: (orderId: number) => void,
) {
  const priceDrafts = ref<Record<number, string>>({})
  const saving = ref(false)

  watch(order, () => { priceDrafts.value = {} })

  /** 当前行单价草稿；未编辑时回退到库里已存值 */
  function priceDraft(item: PurchaseOrderItem): string {
    const draft = priceDrafts.value[item.id]
    if (draft !== undefined) return draft
    return String(item.unit_price ?? 0)
  }

  function onPriceInput(item: PurchaseOrderItem, event: Event) {
    const value = (event.target as HTMLInputElement).value
    priceDrafts.value = { ...priceDrafts.value, [item.id]: value }
  }

  /** 草稿单价解析成数字；空串按 0（未定价），非法值返回 null */
  function parsePrice(item: PurchaseOrderItem): number | null {
    const raw = priceDraft(item).trim()
    if (raw === '') return 0
    const parsed = Number(raw)
    if (!Number.isFinite(parsed) || parsed < 0) return null
    return parsed
  }

  /** 行金额 = 单价 × 数量（单价取草稿值，与保存后一致） */
  function lineAmount(item: PurchaseOrderItem): number {
    const price = parsePrice(item)
    if (price === null) return 0
    return price * (parseFloat(String(item.quantity)) || 0)
  }

  /** 与库里已存值不同的行 = 待保存项（未改动的行不进请求体） */
  const changedEntries = computed(() => {
    const result: { id: number; unit_price: number }[] = []
    for (const item of order()?.items || []) {
      const price = parsePrice(item)
      if (price === null) continue
      if (Math.abs(price - (item.unit_price ?? 0)) > 0.000001) {
        result.push({ id: item.id, unit_price: price })
      }
    }
    return result
  })

  const hasPriceChanges = computed(() => changedEntries.value.length > 0)

  /** 任一行单价非法（负数/非数字）：保存按钮保持可点，点下去给出明确报错 */
  const hasInvalidPrice = computed(() =>
    (order()?.items || []).some((item) => parsePrice(item) === null),
  )

  const canSavePrices = computed(() => hasPriceChanges.value || hasInvalidPrice.value)

  async function handleSavePrices() {
    const current = order()
    if (!current) return
    if (hasInvalidPrice.value) {
      showToast('单价必须是大于等于 0 的数字', 'error')
      return
    }
    if (!hasPriceChanges.value) return
    saving.value = true
    try {
      await purchaseApi.updateItemPrices(current.id, changedEntries.value)
      showToast('单价已保存', 'success')
      onSaved(current.id)
    } catch (err: unknown) {
      showToast((err as Error).message || '保存单价失败', 'error')
    } finally {
      saving.value = false
    }
  }

  return {
    priceDraft,
    onPriceInput,
    lineAmount,
    canSavePrices,
    saving,
    handleSavePrices,
  }
}
