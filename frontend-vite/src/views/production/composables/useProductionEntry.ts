/**
 * useProductionEntry — 生产数据录入抽屉业务逻辑
 *
 * 封装录入表单状态、产品搜索（防抖 + 键盘导航）、最近使用产品、
 * 数量调整、字段校验与提交（含连续录入）、日期快捷工具。
 */
import { ref, reactive, computed, watch, nextTick, onUnmounted, type WritableComputedRef } from 'vue'
import { useQueryClient } from '@tanstack/vue-query'
import { dailyProductionApi, productApi } from '@/api'
import { showToast } from '@/composables/useToast'
import type { Product } from '@/types'

/** 生产部门选项 */
export interface DepartmentOption {
  value: string
  label: string
  icon: string
}

/** 录入表单状态 */
export interface ProductionEntryForm {
  product_id: number | null
  product_name: string
  barcode: string
  unit_price: number
  quantity: number
  remark: string
}

export const PRODUCTION_DEPARTMENTS: readonly DepartmentOption[] = [
  { value: 'filling', label: '充棉部', icon: 'fas fa-cloud' },
  { value: 'handcraft', label: '手工部', icon: 'fas fa-hand-sparkles' },
  { value: 'packaging', label: '包装部', icon: 'fas fa-box' },
]

const RECENT_PRODUCTS_KEY = 'production.recentProducts'
const MAX_RECENT = 6

function loadRecent(): Product[] {
  try {
    const raw = localStorage.getItem(RECENT_PRODUCTS_KEY)
    const arr = raw ? JSON.parse(raw) : []
    return Array.isArray(arr) ? arr.slice(0, MAX_RECENT) : []
  } catch {
    return []
  }
}

function toLocalDate(d: Date): string {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}

function todayLocal(): string {
  return toLocalDate(new Date())
}

function prevDay(d: string): string {
  const dt = new Date(d + 'T00:00:00')
  dt.setDate(dt.getDate() - 1)
  return toLocalDate(dt)
}

export function useProductionEntry(
  openModel: WritableComputedRef<boolean>,
  selectedDateModel: WritableComputedRef<string>,
) {
  const queryClient = useQueryClient()
  const _timers: ReturnType<typeof setTimeout>[] = []

  const formDept = ref('filling')
  const isSubmitting = ref(false)
  const keepAdding = ref(false)

  const recentProducts = ref<Product[]>(loadRecent())

  function saveRecent() {
    try {
      localStorage.setItem(RECENT_PRODUCTS_KEY, JSON.stringify(recentProducts.value.slice(0, MAX_RECENT)))
    } catch {
      /* localStorage 不可用时静默忽略 */
    }
  }
  function pushRecent(product: Product) {
    if (!product || product.id == null) return
    const filtered = recentProducts.value.filter((x) => x.id !== product.id)
    filtered.unshift(product)
    recentProducts.value = filtered.slice(0, MAX_RECENT)
    saveRecent()
  }
  function clearRecent() {
    recentProducts.value = []
    saveRecent()
  }

  const form = reactive<ProductionEntryForm>({
    product_id: null,
    product_name: '',
    barcode: '',
    unit_price: 0,
    quantity: 0,
    remark: '',
  })
  const formErrors = reactive<Record<string, string>>({})
  const computedValue = computed(() => (form.quantity || 0) * (form.unit_price || 0))

  function adjustQty(delta: number) {
    const cur = Number(form.quantity) || 0
    form.quantity = Math.max(0, cur + delta)
  }

  const searchQuery = ref('')
  const searchResults = ref<Product[]>([])
  const showDropdown = ref(false)
  const searchLoading = ref(false)
  const searchError = ref('')
  const searchActiveIndex = ref(-1)
  const productSearchRef = ref<HTMLInputElement>()
  let searchTimer: ReturnType<typeof setTimeout> | null = null

  function onSearchInput() {
    if (searchTimer) clearTimeout(searchTimer)
    searchError.value = ''
    if (form.product_name && searchQuery.value !== form.product_name) {
      form.product_id = null
      form.product_name = ''
      form.barcode = ''
      form.unit_price = 0
    }
    if (!searchQuery.value.trim()) {
      searchResults.value = []
      showDropdown.value = false
      return
    }
    searchLoading.value = true
    showDropdown.value = true
    searchActiveIndex.value = -1
    searchTimer = setTimeout(async () => {
      try {
        const res = (await productApi.search(searchQuery.value.trim())) as unknown as Product[] & { products?: Product[] }
        searchResults.value = res.products ?? res ?? []
        searchError.value = ''
      } catch {
        searchError.value = '产品搜索失败，请重试'
        searchResults.value = []
      } finally {
        searchLoading.value = false
      }
    }, 300)
  }
  function onSearchFocus() {
    if (searchQuery.value.trim() && (searchResults.value.length || searchError.value)) {
      showDropdown.value = true
    }
  }
  function onSearchBlur() {
    const _t = setTimeout(() => {
      showDropdown.value = false
      searchActiveIndex.value = -1
    }, 150)
    _timers.push(_t)
  }
  function moveSearchIndex(delta: number) {
    if (!searchResults.value.length) return
    searchActiveIndex.value += delta
    if (searchActiveIndex.value < 0) searchActiveIndex.value = searchResults.value.length - 1
    if (searchActiveIndex.value >= searchResults.value.length) searchActiveIndex.value = 0
  }
  function confirmSearchSelection() {
    const product = searchActiveIndex.value >= 0 ? searchResults.value[searchActiveIndex.value] : undefined
    if (product) selectProduct(product)
  }
  async function selectProduct(product: Product) {
    form.product_id = product.id
    form.product_name = product.name
    form.barcode = product.barcode || ''
    searchQuery.value = product.name
    searchResults.value = []
    showDropdown.value = false
    searchActiveIndex.value = -1
    pushRecent(product)
    try {
      const infoRes = await dailyProductionApi.productInfo(product.id)
      if (infoRes?.data?.price) {
        form.unit_price = infoRes.data.price
      }
    } catch {
      // 获取单价失败不影响主流程
    }
  }
  function clearProduct() {
    form.product_id = null
    form.product_name = ''
    form.barcode = ''
    searchQuery.value = ''
    form.unit_price = 0
  }

  function validateField(field: string): boolean {
    formErrors[field] = ''
    if (field === 'quantity') {
      if (!form.quantity || form.quantity <= 0) {
        formErrors.quantity = '生产数量必须大于0'
        return false
      }
      if (form.quantity > 999999) {
        formErrors.quantity = '生产数量不能超过999999'
        return false
      }
    }
    if (field === 'product_name' && !form.product_name) {
      formErrors.product_name = '请选择产品'
      return false
    }
    return true
  }

  function validateForm(): boolean {
    let valid = true
    if (!validateField('product_name')) valid = false
    if (!validateField('quantity')) valid = false
    if (!formDept.value) {
      showToast('请选择生产部门', 'warning')
      valid = false
    }
    return valid
  }

  function resetForm() {
    form.product_id = null
    form.product_name = ''
    form.barcode = ''
    form.unit_price = 0
    form.quantity = 0
    form.remark = ''
    searchQuery.value = ''
    formDept.value = 'filling'
    keepAdding.value = false
    Object.keys(formErrors).forEach((k) => (formErrors[k] = ''))
  }

  function resetFormForContinue() {
    form.product_id = null
    form.product_name = ''
    form.barcode = ''
    form.quantity = 0
    searchQuery.value = ''
    Object.keys(formErrors).forEach((k) => (formErrors[k] = ''))
  }

  function closeEntryDrawer() {
    openModel.value = false
    resetForm()
  }

  async function confirmSubmit(opts: { keepOpen: boolean } = { keepOpen: false }) {
    isSubmitting.value = true
    try {
      await dailyProductionApi.createRecord({
        department: formDept.value,
        product_id: form.product_id,
        product_name: form.product_name,
        barcode: form.barcode,
        unit_price: form.unit_price || 0,
        quantity: form.quantity,
        production_value: Number(computedValue.value),
        production_date: selectedDateModel.value,
        remark: form.remark,
      } as Record<string, unknown>)
      showToast('录入成功', 'success')
      if (opts.keepOpen) {
        resetFormForContinue()
        nextTick(() => productSearchRef.value?.focus())
      } else {
        resetForm()
        openModel.value = false
      }
      queryClient.invalidateQueries({ queryKey: ['daily-production-records'] })
      queryClient.invalidateQueries({ queryKey: ['daily-production-daily-summary'] })
      queryClient.invalidateQueries({ queryKey: ['daily-production-monthly-summary'] })
    } catch (error: unknown) {
      const detail = (error as { response?: { data?: { detail?: string } } } | null)?.response?.data?.detail
      showToast(detail ?? '录入失败', 'error')
    } finally {
      isSubmitting.value = false
    }
  }

  async function handleSubmit() {
    if (!validateForm()) return
    if (keepAdding.value) {
      await confirmSubmit({ keepOpen: true })
    } else {
      await confirmSubmit({ keepOpen: false })
    }
  }

  watch(openModel, (v) => {
    if (v) {
      nextTick(() => productSearchRef.value?.focus())
    }
  })

  onUnmounted(() => {
    if (searchTimer) clearTimeout(searchTimer)
    _timers.forEach(clearTimeout)
  })

  return {
    departments: PRODUCTION_DEPARTMENTS,
    formDept,
    isSubmitting,
    keepAdding,
    recentProducts,
    clearRecent,
    form,
    formErrors,
    computedValue,
    adjustQty,
    searchQuery,
    searchResults,
    showDropdown,
    searchLoading,
    searchError,
    searchActiveIndex,
    productSearchRef,
    onSearchInput,
    onSearchFocus,
    onSearchBlur,
    moveSearchIndex,
    confirmSearchSelection,
    selectProduct,
    clearProduct,
    validateField,
    closeEntryDrawer,
    handleSubmit,
    todayLocal,
    prevDay,
  }
}