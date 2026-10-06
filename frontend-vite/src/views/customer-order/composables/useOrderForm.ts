import { ref, reactive, computed } from 'vue'
import { auxApi } from '@/api'
import { useCatalogStore } from '@/stores/catalog'
import { isQuantityOutOfRange } from './quantityRange'
import { planSplitsMessage } from './shipmentPlanRules'
import type { FormState, ProductSuggestion, AvailableStockinItem } from './types'

/** 产品搜索防抖由 UiAutocomplete 内部处理 */

/** 按**本地时区**格式化为 YYYY-MM-DD（toISOString 会按 UTC 截断，导致跨时区偏移一天） */
export function formatLocalDate(d: Date): string {
  const y = d.getFullYear()
  const m = String(d.getMonth() + 1).padStart(2, '0')
  const day = String(d.getDate()).padStart(2, '0')
  return `${y}-${m}-${day}`
}

export function useOrderForm() {
  // ===== Data queries =====
  // 客户下拉选项：目录 store 统一缓存（TTL 内跨视图复用，组件卸载不清空）
  const catalogStore = useCatalogStore()
  catalogStore.ensureActiveCustomerNames().catch(() => {
    // 加载失败保持空列表，下次进入视图时重试
  })
  const customerList = computed(() => catalogStore.activeCustomerNames.map((c) => ({ name: c.name })))
  const customerOptions = computed(() => customerList.value.map((c: { name: string }) => ({ value: c.name, label: c.name })))

  // ===== Product search (delegated to UiAutocomplete) =====
  /** 产品搜索是否失败过。失败不能与「无匹配结果」混为一谈，否则用户会误判为产品不存在。 */
  const productSearchFailed = ref(false)

  async function searchProducts(q: string): Promise<ProductSuggestion[]> {
    if (!q.trim()) return []
    try {
      const d = await auxApi.productSearch(q)
      productSearchFailed.value = false
      return (Array.isArray(d) ? d : []).map((p) => ({ value: p.name, id: p.id, name: p.name, barcode: p.barcode ?? '' }))
    } catch {
      productSearchFailed.value = true
      return []
    }
  }

  function selectProduct(p: ProductSuggestion) {
    form.productId = p.id
    form.productSearch = p.value
    if (isOrder.value && form.deductStock) fetchAvailableStock()
  }

  // ===== Unified form =====
  // 按本地时区取当天日期。不能用 toISOString()（恒为 UTC）：在 UTC+8 下
  // 本地 08:00 之前它返回的是前一天，会让新录入的单据默认落到昨天。
  const today = formatLocalDate(new Date())
  const form = reactive<FormState>({
    type: 'order',
    date: today,
    customer: '',
    productSearch: '',
    productId: 0,
    quantity: 0,
    deductStock: false,
    deductQuantity: 0,
    note: '',
    shipmentPlans: [],
  })
  const isOrder = computed(() => form.type === 'order')
  /**
   * 当前还缺哪些必填项（只列**字段名**，用于「请先填写：…」）。
   * 越界属于「已填但值不合法」，由 quantityOutOfRange 单独表达并给出区间文案，
   * 不混进缺项清单，否则长句会读成「还需填写：客户名称、数量必须介于…」。
   */
  const missingFields = computed<string[]>(() => {
    const missing: string[] = []
    if (!form.date) missing.push(isOrder.value ? '订单时间' : '备货时间')
    if (!form.customer) missing.push('客户名称')
    if (!form.productId) missing.push('产品名称')
    if (!(form.quantity > 0)) missing.push(isOrder.value ? '订单数量' : '备货数量')
    return missing
  })

  /** 数量已填但超出 [1, 9,999,999]（0、负数、超上限都算） */
  const quantityOutOfRange = computed(() => isQuantityOutOfRange(form.quantity))

  /**
   * 分批出货计划值错误（2026-10-06 v2）：''=合法。
   * 与 quantityOutOfRange 同通道——缺项走 missingFields，值错误单独表达。
   */
  const planSplitsInvalid = computed(() =>
    isOrder.value ? planSplitsMessage(form.shipmentPlans, form.quantity) : '')

  const canAdd = computed(() => missingFields.value.length === 0 && !quantityOutOfRange.value)

  // ===== Deduct stock =====
  const availableStock = ref(0)
  const deductInfoVisible = ref(false)
  /** 可用备货查询的失败/前置条件原因。非空时界面展示该原因，
   * 而不是把「查询失败」或「还没选客户」呈现成「暂无可用备货」这一业务结论。 */
  const stockError = ref('')

  async function fetchAvailableStock() {
    if (!form.productId || !form.customer) {
      availableStock.value = 0
      stockError.value = '请先选择产品与客户，才能查询可用备货'
      return
    }
    try {
      const res = await auxApi.availableStockins({ product_id: form.productId, customer: form.customer })
      const items: AvailableStockinItem[] = Array.isArray(res) ? res : []
      availableStock.value = items.reduce((s: number, i: AvailableStockinItem) => s + (i.available ?? i.quantity - (i.deducted || 0)), 0)
      stockError.value = ''
    } catch {
      availableStock.value = 0
      stockError.value = '可用备货查询失败，请重试'
    }
  }

  async function enableDeduct() {
    form.deductStock = true
    deductInfoVisible.value = true
    // 先用当前已知值占位，await 完成后用最新值修正
    form.deductQuantity = Math.min(form.quantity, availableStock.value)
    await fetchAvailableStock()
    form.deductQuantity = Math.min(form.quantity, availableStock.value)
  }

  function disableDeduct() {
    form.deductStock = false
    form.deductQuantity = 0
    deductInfoVisible.value = false
    stockError.value = ''
  }

  /** UI 按钮切换：开关抵扣预览 */
  async function handleDeductPreview() {
    if (form.deductStock) {
      disableDeduct()
    } else {
      await enableDeduct()
    }
  }

  async function openDeductEdit() {
    if (!form.deductStock) await enableDeduct()
    deductInfoVisible.value = true
  }

  function resetFormAfterAdd() {
    form.productSearch = ''
    form.productId = 0
    form.quantity = 0
    form.note = ''
    form.deductStock = false
    form.deductQuantity = 0
    deductInfoVisible.value = false
    form.shipmentPlans = []
  }

  return {
    form,
    isOrder,
    canAdd,
    missingFields,
    quantityOutOfRange,
    planSplitsInvalid,
    customerOptions,
    searchProducts,
    productSearchFailed,
    selectProduct,
    availableStock,
    deductInfoVisible,
    stockError,
    handleDeductPreview,
    openDeductEdit,
    resetFormAfterAdd,
  }
}
