import { ref, computed, onUnmounted } from 'vue'
import { purchaseApi, type MaterialCalcProduct, type MaterialCalcRow, type MaterialCalcScopeGroup } from '@/api'
import { showToast } from '@/composables/useToast'
import { getErrorMessage } from '@/types/errors'
import { deriveRoleMatrix } from '@/utils/roleMatrix'

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
 *
 * 响应口径：后端 `/calculate` **只追加** `groups`，扁平字段原样保留。
 * - `calcResults`：扁平字段（旧口径，保留用于回退渲染）；
 * - `calcGroups`：按「产品 × 作用域(角色)」分块（默认 BOM 恒首）；
 * - `matrix`：由 `calcGroups` 派生的跨角色对比矩阵（纯函数，A-5 缺失时为空矩阵）。
 */
// 订单物料条目上限（与后端 CalculateMaterialRequest.orders max_length=200 对齐）
const MAX_ORDER_ITEMS = 200

export function useMaterialCalculator() {
  const orderItems = ref<OrderItem[]>([])
  const calcResults = ref<Record<string, MaterialCalcRow[]>>({})
  const calcGroups = ref<MaterialCalcScopeGroup[]>([])
  const calculating = ref(false)

  // selectedProductIds 由 orderItems 派生，避免双份状态失同步
  const selectedProductIds = computed(() => orderItems.value.map((i) => i.product_id))
  const totalOrders = computed(() =>
    orderItems.value.reduce((s, i) => s + (i.quantity > 0 ? i.quantity : 0), 0),
  )
  const hasResults = computed(() => Object.values(calcResults.value).some((arr) => arr.length > 0))
  const hasGroups = computed(() => calcGroups.value.length > 0)
  // 跨角色对比矩阵：groups 缺失/空 → 空矩阵（不抛错，A-5）
  const matrix = computed(() => deriveRoleMatrix(calcGroups.value))
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
    if (orderItems.value.length >= MAX_ORDER_ITEMS) {
      showToast(`最多添加 ${MAX_ORDER_ITEMS} 个产品进行计算，请先移除部分产品`, 'warning')
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
    calcGroups.value = []
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
      calcGroups.value = []
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
      // groups 为「只追加」字段：旧后端可能缺失 → 置空并回退扁平渲染（A-5）
      calcGroups.value = Array.isArray(res.groups) ? res.groups : []
    } catch (err: unknown) {
      if (reqId !== calcRequestId) return
      showToast(getErrorMessage(err, '计算失败'), 'error')
    } finally {
      if (reqId === calcRequestId) calculating.value = false
    }
  }

  function dispose() {
    if (calcTimer) clearTimeout(calcTimer)
  }

  // 组件卸载时清理防抖定时器，避免内存泄漏与卸载后回调执行
  onUnmounted(() => {
    dispose()
  })

  return {
    orderItems,
    calcResults,
    calcGroups,
    calculating,
    selectedProductIds,
    totalOrders,
    hasResults,
    hasGroups,
    matrix,
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
