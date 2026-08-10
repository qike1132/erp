import { ref, reactive, computed, watch } from 'vue'
import { get } from '@/api/request'
import { customerApi } from '@/api'
import { useQuery } from '@tanstack/vue-query'
import { useCountryStore } from '@/stores/country'
import { showToast } from '@/composables/useToast'
import type { FormState, ProductSuggestion, AvailableStockinItem } from './types'

/** 产品搜索防抖由 UiAutocomplete 内部处理 */
/** 数量上限 */
const MAX_QUANTITY = 9999999

export function useOrderForm() {
  // ===== Data queries =====
  const { data: customerData } = useQuery({
    queryKey: ['customers-active-names'],
    queryFn: () => customerApi.activeNames() as Promise<any>,
    staleTime: 30_000,
    gcTime: 60_000,
  })
  const customerList = computed(() => {
    const raw = customerData.value?.names ?? customerData.value ?? []
    return raw.map((c: any) => ({ name: c.name ?? c }))
  })
  const customerOptions = computed(() => customerList.value.map((c: { name: string }) => ({ value: c.name, label: c.name })))

  // ===== Product search (delegated to UiAutocomplete) =====
  async function searchProducts(q: string): Promise<ProductSuggestion[]> {
    if (!q.trim()) return []
    try {
      const d = await get<any[]>('/aux/product-search', { q })
      return (Array.isArray(d) ? d : []).map((p: any) => ({ value: p.name, id: p.id, name: p.name, barcode: p.barcode ?? '' }))
    } catch {
      return []
    }
  }

  function selectProduct(p: ProductSuggestion) {
    form.productId = p.id
    form.productSearch = p.value
    if (isOrder.value && form.deductStock) fetchAvailableStock()
  }

  // ===== Unified form =====
  const today = new Date().toISOString().split('T')[0] ?? ''
  const form = reactive<FormState>({
    type: 'order',
    orderType: 'normal',
    date: today,
    customer: '',
    productSearch: '',
    productId: 0,
    quantity: 0,
    deductStock: false,
    deductQuantity: 0,
    note: '',
    country: '',
  })
  const isOrder = computed(() => form.type === 'order')
  const isCustomOrder = computed(() => form.orderType === 'custom')
  const orderTypeOptions = [
    { value: 'normal', label: '常规订单' },
    { value: 'custom', label: '定制订单' },
  ]

  const lastCountry = ref('')
  watch(() => form.orderType, (newType, oldType) => {
    if (oldType === 'custom' && newType === 'normal') {
      lastCountry.value = form.country
      form.country = ''
    } else if (oldType === 'normal' && newType === 'custom' && lastCountry.value) {
      form.country = lastCountry.value
    }
  })
  const canAdd = computed(() => {
    const base = !!form.customer && !!form.productId && form.quantity > 0 && form.quantity <= MAX_QUANTITY && !!form.date
    if (isCustomOrder.value) return base && !!form.country
    return base
  })

  // ===== Country dialog =====
  const countryDialogVisible = ref(false)
  const newCountryName = ref('')
  const countryStore = useCountryStore()

  if (!countryStore.loaded) {
    countryStore.fetchCountries()
  }

  function openCountryDialog() {
    newCountryName.value = ''
    countryDialogVisible.value = true
  }

  async function saveCountry() {
    const trimmed = newCountryName.value.trim()
    if (!trimmed) {
      showToast('请输入国家名称', 'warning')
      return
    }
    const ok = await countryStore.addCountry(trimmed)
    if (ok) {
      form.country = trimmed
      countryDialogVisible.value = false
      showToast('国家保存成功', 'success')
    } else {
      showToast('该国家已存在', 'warning')
    }
  }

  // ===== Deduct stock =====
  const availableStock = ref(0)
  const deductInfoVisible = ref(false)

  async function fetchAvailableStock() {
    if (!form.productId || !form.customer) {
      availableStock.value = 0
      return
    }
    try {
      const res = (await get('/aux/available-stockins', { product_id: form.productId, customer: form.customer })) as any
      const items: AvailableStockinItem[] = res.stockins ?? res.items ?? res ?? []
      availableStock.value = items.reduce((s: number, i: AvailableStockinItem) => s + (i.available ?? i.quantity - (i.deducted || 0)), 0)
    } catch {
      availableStock.value = 0
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
    form.orderType = 'normal'
    form.country = ''
    form.deductStock = false
    form.deductQuantity = 0
    deductInfoVisible.value = false
  }

  return {
    form,
    isOrder,
    isCustomOrder,
    orderTypeOptions,
    canAdd,
    customerOptions,
    countryStore,
    searchProducts,
    selectProduct,
    countryDialogVisible,
    newCountryName,
    openCountryDialog,
    saveCountry,
    availableStock,
    deductInfoVisible,
    handleDeductPreview,
    openDeductEdit,
    resetFormAfterAdd,
  }
}
