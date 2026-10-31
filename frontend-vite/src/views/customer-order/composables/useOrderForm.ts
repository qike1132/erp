import { ref, reactive, computed, watch } from 'vue'
import { auxApi } from '@/api'
import type { ProductSearchItem } from '@/api/auxiliary'
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

  // ===== Product search / browse =====
  /** 产品搜索是否失败过。失败不能与「无匹配结果」混为一谈，否则用户会误判为产品不存在。 */
  const productSearchFailed = ref(false)
  /** 浏览列表（弹窗点开时）是否加载失败。与「该客户没有产品」是两回事。 */
  const skuListFailed = ref(false)

  /** 浏览模式一次列多少条。弹窗不做分页，超过上限由弹窗给提示引导去搜索。 */
  const SKU_BROWSE_LIMIT = 200

  /**
   * 后端搜索项 → 前端建议项。搜索与浏览共用同一个映射：OCR 粘贴导入的「手选产品」
   * 也吃这个结构，两处各写一份迟早漂移，而漂移的表现是那条链路静默失效。
   */
  function toProductSuggestions(items: ProductSearchItem[] | null | undefined): ProductSuggestion[] {
    return (Array.isArray(items) ? items : []).map((p) => ({
      value: p.name, id: p.id, name: p.name, barcode: p.barcode ?? '',
    }))
  }

  async function searchProducts(q: string): Promise<ProductSuggestion[]> {
    if (!q.trim()) return []
    try {
      // 带上当前客户：后端只返回属于该客户（或未挂客户）的 SKU。
      // 未选客户时 customer 为 undefined，后端不过滤 —— 与改造前一致。
      const d = await auxApi.productSearch(q, { customer: form.customer || undefined })
      productSearchFailed.value = false
      return toProductSuggestions(d)
    } catch {
      productSearchFailed.value = true
      return []
    }
  }

  /**
   * 浏览模式：列出当前客户可见的全部 SKU（弹窗点开时调，此时还没有关键字）。
   * 未选客户不发请求 —— 后端在没有客户时本就返回空，前端提前短路省一次往返。
   */
  async function fetchSkuList(): Promise<ProductSuggestion[]> {
    if (!form.customer) {
      skuListFailed.value = false
      return []
    }
    try {
      const d = await auxApi.productSearch('', { customer: form.customer, limit: SKU_BROWSE_LIMIT })
      skuListFailed.value = false
      return toProductSuggestions(d)
    } catch {
      skuListFailed.value = true
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

  // 切换客户 → 清掉已选产品。产品可见范围随客户变化，留着旧选择等于让用户提交一个
  // 可能不属于新客户的 SKU（下拉里显示的结果也还是上一个客户的）。
  watch(() => form.customer, () => {
    form.productSearch = ''
    form.productId = 0
    if (form.deductStock) disableDeduct()
  })

  /**
   * 弹窗里「没有数据」的原因（空串 = 正常）。
   * 三种空对用户的下一步完全不同：没选客户要去选客户、加载失败要重试、
   * 客户真没挂产品要去产品页挂客户。一律显示「暂无数据」等于把用户扔在原地。
   */
  const skuListError = computed(() => {
    if (!form.customer) return '请先选择客户'
    return skuListFailed.value ? '加载失败，请重试' : ''
  })
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
  /** 可用备货请求序号（A-M36）：只接受最后一次请求的结果，防跨产品串数 */
  let stockFetchSeq = 0
  /** 可用备货查询的失败/前置条件原因。非空时界面展示该原因，
   * 而不是把「查询失败」或「还没选客户」呈现成「暂无可用备货」这一业务结论。 */
  const stockError = ref('')

  async function fetchAvailableStock() {
    if (!form.productId || !form.customer) {
      availableStock.value = 0
      stockError.value = '请先选择产品与客户，才能查询可用备货'
      return
    }
    // 请求序号（A-M36）：连续换产品/客户时先发的请求可能后到，把 A 产品的
    // 可用量写到 B 产品上——用户照着这个数字填抵扣量，后端按 B 的备货扣，
    // 结果就是「少扣且无提示」。只接受最后一次请求、且产品/客户未变的结果。
    const seq = ++stockFetchSeq
    const productId = form.productId
    const customer = form.customer
    try {
      const res = await auxApi.availableStockins({ product_id: productId, customer: customer })
      if (seq !== stockFetchSeq) return
      if (form.productId !== productId || form.customer !== customer) return
      const items: AvailableStockinItem[] = Array.isArray(res) ? res : []
      availableStock.value = items.reduce((s: number, i: AvailableStockinItem) => s + (i.available ?? i.quantity - (i.deducted || 0)), 0)
      stockError.value = ''
    } catch {
      if (seq !== stockFetchSeq) return
      if (form.productId !== productId || form.customer !== customer) return
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
    // 类型必须归位「订单」：备货条目会直接增加库存，type 残留会让后续添加的条目
    // 在用户不注意时全部变成备货入库（2026-10-06 出库"凭空库存"事故的入口之一）
    form.type = 'order'
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
    fetchSkuList,
    skuListError,
    selectProduct,
    availableStock,
    deductInfoVisible,
    stockError,
    fetchAvailableStock,
    handleDeductPreview,
    openDeductEdit,
    resetFormAfterAdd,
  }
}
