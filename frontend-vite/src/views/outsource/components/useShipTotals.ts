/**
 * useShipTotals — 批量发货底栏汇总口径（只算，不改状态）
 *
 * 从清单视图模型派生底栏与确认态所需的全部汇总：已勾选工序行、合计件数、
 * 涉及订单数（经 splitQty 拆分去重）、非法行计数与首条非法提示。
 * 口径与提交 payload 一致：rowQty 只计已勾选且合法的行。
 */
import { computed, type Ref } from 'vue'
import { splitQty, rowQty, isRowInvalid, type CartProduct } from './shipCartModel'

export function useShipTotals(cartGroups: Ref<CartProduct[]>) {
  const checkedRows = computed(() =>
    cartGroups.value.flatMap((p) => p.processes).filter((r) => r.input.on),
  )
  const checkedCount = computed(() => checkedRows.value.length)
  const shipSum = computed(() => checkedRows.value.reduce((s, r) => s + rowQty(r), 0))
  /** 涉及订单数：按各工序拆分后的实际发货订单去重 */
  const selectedOrderCount = computed(() => {
    const ids = new Set<number>()
    for (const r of checkedRows.value) {
      for (const it of splitQty(r)) ids.add(it.row.order_id)
    }
    return ids.size
  })
  const invalidCount = computed(() => checkedRows.value.filter(isRowInvalid).length)

  /** 首条非法行的提示：明确指出工序名与上限，便于直接定位与修正 */
  const firstInvalidHint = computed(() => {
    const r = checkedRows.value.find(isRowInvalid)
    if (!r) return ''
    const n = Number(r.input.qty)
    if (!Number.isFinite(n) || n < 1) return `「${r.processType}」需为大于 0 的整数`
    if (!Number.isInteger(n)) return `「${r.processType}」需为整数`
    return `「${r.processType}」不能超过剩余未发 ${r.remaining.toLocaleString()}`
  })

  return { checkedRows, checkedCount, shipSum, selectedOrderCount, invalidCount, firstInvalidHint }
}
