import { ref, computed } from 'vue'
import { purchaseApi, type MaterialCalcProduct, type MaterialCalcRow } from '@/api'
import { showToast } from '@/composables/useToast'

export interface OrderItem {
  product_id: number
  name: string
  quantity: number
}

// 物料分类列表（与后端 result 字典一致，包装类不展示）
export const CALC_CATEGORY_LIST = [
  { key: 'filling', label: '填充类', icon: 'fas fa-cloud' },
  { key: 'fabric', label: '面料类', icon: 'fas fa-scroll' },
  { key: 'accessory', label: '辅料类', icon: 'fas fa-puzzle-piece' },
] as const

export const CALC_CATEGORY_LABELS: Record<string, string> = Object.fromEntries(
  CALC_CATEGORY_LIST.map((c) => [c.key, c.label]),
)

/** 将任意输入规整为非负整数；非法/负值返回 0。 */
export function clampQuantity(v: unknown): number {
  const n = Number(v)
  if (!Number.isFinite(n) || n < 0) return 0
  return Math.floor(n)
}

/**
 * 物料计算器共享状态与逻辑。
 * 桌面端 / 移动端共用，确保行为一致（BOM 校验、聚合、竞态保护）。
 * 搜索 UI 由各端自行实现，仅共享订单与计算逻辑。
 */
export function useMaterialCalculator() {
  const orderItems = ref<OrderItem[]>([])
  const calcResults = ref<Record<string, MaterialCalcRow[]>>({})
  const calculating = ref(false)

  // selectedProductIds 由 orderItems 派生，避免双份状态失同步
  const selectedProductIds = computed(() => orderItems.value.map((i) => i.product_id))
  const totalOrders = computed(() =>
    orderItems.value.reduce((s, i) => s + (i.quantity > 0 ? i.quantity : 0), 0),
  )
  const hasResults = computed(() => Object.values(calcResults.value).some((arr) => arr.length > 0))
  const calcStatus = computed(() => {
    if (calculating.value) return '计算中...'
    const total = Object.values(calcResults.value).reduce((s, arr) => s + arr.length, 0)
    return total > 0 ? `${total} 种物料` : ''
  })

  let calcTimer: ReturnType<typeof setTimeout> | null = null
  let calcRequestId = 0 // 竞态保护：仅最新一次请求的结果会生效

  function addProduct(p: MaterialCalcProduct, defaultQuantity: number = 0): boolean {
    if (!p.has_bom) {
      showToast(`"${p.name}" 没有BOM，无法计算物料`, 'warning')
      return false
    }
    if (selectedProductIds.value.includes(p.id)) return false
    orderItems.value.push({ product_id: p.id, name: p.name, quantity: clampQuantity(defaultQuantity) })
    return true
  }

  function removeProduct(id: number) {
    const idx = orderItems.value.findIndex((i) => i.product_id === id)
    if (idx >= 0) orderItems.value.splice(idx, 1)
  }

  function clearAll() {
    // 递增 requestId 使任何在途请求过期，避免清空后旧结果回流
    calcRequestId++
    orderItems.value = []
    calcResults.value = {}
    calculating.value = false
  }

  function applyBatch(quantity: number) {
    const q = clampQuantity(quantity)
    orderItems.value.forEach((i) => {
      i.quantity = q
    })
  }

  function debounceCalc() {
    if (calcTimer) clearTimeout(calcTimer)
    calcTimer = setTimeout(() => triggerCalculation(), 350)
  }

  async function triggerCalculation() {
    const validOrders = orderItems.value.filter((i) => i.quantity > 0)
    const reqId = ++calcRequestId
    if (validOrders.length === 0) {
      calcResults.value = {}
      calculating.value = false
      return
    }
    calculating.value = true
    try {
      const res = await purchaseApi.calculate(
        validOrders.map((i) => ({ product_id: i.product_id, quantity: i.quantity })),
      )
      // 过期响应丢弃，避免旧请求覆盖新结果
      if (reqId !== calcRequestId) return
      calcResults.value = {
        filling: res.filling ?? [],
        fabric: res.fabric ?? [],
        accessory: res.accessory ?? [],
      }
    } catch (err: any) {
      if (reqId !== calcRequestId) return
      showToast(err?.response?.data?.detail || '计算失败', 'error')
    } finally {
      if (reqId === calcRequestId) calculating.value = false
    }
  }

  function dispose() {
    if (calcTimer) clearTimeout(calcTimer)
  }

  return {
    orderItems,
    calcResults,
    calculating,
    selectedProductIds,
    totalOrders,
    hasResults,
    calcStatus,
    addProduct,
    removeProduct,
    clearAll,
    applyBatch,
    debounceCalc,
    triggerCalculation,
    dispose,
  }
}
