/**
 * useProductionEntry — 生产数据录入弹窗业务逻辑（单行快捷录入）
 *
 * 封装录入表单状态、产品搜索（防抖 + 键盘导航）、最近使用产品、数量调整、
 * 字段校验、连续提交（提交后清空表单并把焦点送回搜索框）、今日重复提示与撤销。
 *
 * 键盘流是本次改版的核心：Alt+1/2/3 切部门、搜索框 ↑↓ 选品 + ⏎ 确认并跳到数量、
 * 数量框 ↑↓ ∓1 / Shift+↑↓ ∓10、⏎ 提交、Ctrl+⏎ 任意位置提交、Esc 关闭。
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

/** 刚创建的记录（用于「刚才录的」条与撤销） */
export interface CreatedRecordSummary {
  id: number
  product_name: string
  department: string
  quantity: number
}

export const PRODUCTION_DEPARTMENTS: readonly DepartmentOption[] = [
  { value: 'filling', label: '充棉部', icon: 'fas fa-cloud' },
  { value: 'handcraft', label: '手工部', icon: 'fas fa-hand-sparkles' },
  { value: 'packaging', label: '包装部', icon: 'fas fa-box' },
]

const RECENT_PRODUCTS_KEY = 'production.recentProducts'
const LAST_DEPT_KEY = 'production.lastDepartment'
const MAX_RECENT = 6
const DEFAULT_DEPT = 'filling'
/** Alt+1/2/3 对应 departments 的下标 */
const ALT_DEPT_KEYS = ['1', '2', '3'] as const

function loadRecent(): Product[] {
  try {
    const raw = localStorage.getItem(RECENT_PRODUCTS_KEY)
    const arr = raw ? JSON.parse(raw) : []
    return Array.isArray(arr) ? arr.slice(0, MAX_RECENT) : []
  } catch {
    return []
  }
}

/** 上次使用的部门；非法/不可读时回落到默认部门（localStorage 不可用时静默） */
function loadLastDept(): string {
  try {
    const v = localStorage.getItem(LAST_DEPT_KEY)
    return v && PRODUCTION_DEPARTMENTS.some((d) => d.value === v) ? v : DEFAULT_DEPT
  } catch {
    return DEFAULT_DEPT
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

/** 'YYYY-MM-DD' → { year, month }（records 接口要求年/月或区间二选一） */
function monthParts(dateStr: string): { year: number; month: number } {
  const d = new Date(dateStr + 'T00:00:00')
  return { year: d.getFullYear(), month: d.getMonth() + 1 }
}

export function useProductionEntry(
  openModel: WritableComputedRef<boolean>,
  selectedDateModel: WritableComputedRef<string>,
) {
  const queryClient = useQueryClient()
  const _timers: ReturnType<typeof setTimeout>[] = []

  const formDept = ref(loadLastDept())
  const isSubmitting = ref(false)
  const detailOpen = ref(false)
  const deptMenuOpen = ref(false)

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

  // ===== 少录错护栏 =====
  /** 未选产品或数量 ≤ 0 时不允许提交（按钮禁用 + handleSubmit 兜底） */
  const canSubmit = computed(() => form.product_id != null && Number(form.quantity) > 0)

  const todayCount = ref(0)
  const duplicateTotal = ref(0)
  /** 今日同部门同产品已有数量 —— 只提示，绝不阻断（一天两批同产品是合法的） */
  const duplicateHint = computed(() =>
    duplicateTotal.value > 0 ? `今天已录 ${duplicateTotal.value} 件 · 仍要录入` : '',
  )

  const lastCreated = ref<CreatedRecordSummary | null>(null)
  const undoConfirmOpen = ref(false)
  const undoText = computed(() => {
    const c = lastCreated.value
    return c ? `撤销刚才录入的「${c.product_name}」${c.quantity} 件？` : '撤销刚才录入的记录？'
  })

  const currentDept = computed(
    () => PRODUCTION_DEPARTMENTS.find((d) => d.value === formDept.value) ?? PRODUCTION_DEPARTMENTS[0]!,
  )

  function deptLabel(value: string): string {
    return PRODUCTION_DEPARTMENTS.find((d) => d.value === value)?.label ?? value
  }

  function adjustQty(delta: number) {
    const cur = Number(form.quantity) || 0
    form.quantity = Math.max(0, cur + delta)
  }

  /** 数量框 ↑↓（Shift 时为 ±10） */
  function onQtyArrow(direction: number, event: KeyboardEvent) {
    adjustQty(direction * (event.shiftKey ? 10 : 1))
  }

  // ===== 产品搜索 =====
  const searchQuery = ref('')
  const searchResults = ref<Product[]>([])
  const showDropdown = ref(false)
  const searchLoading = ref(false)
  const searchError = ref('')
  const searchActiveIndex = ref(-1)
  const productSearchRef = ref<HTMLInputElement>()
  const quantityRef = ref<HTMLInputElement>()
  let searchTimer: ReturnType<typeof setTimeout> | null = null

  function onSearchInput() {
    if (searchTimer) clearTimeout(searchTimer)
    searchError.value = ''
    if (form.product_name && searchQuery.value !== form.product_name) {
      form.product_id = null
      form.product_name = ''
      form.barcode = ''
      form.unit_price = 0
      duplicateTotal.value = 0
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
    if (product) void selectProduct(product)
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
    // 选品即完成 → 焦点直奔数量框，键盘流不断线（鼠标点 chip 时同样受益）
    nextTick(() => quantityRef.value?.focus())
    void checkDuplicate()
  }
  function clearProduct() {
    form.product_id = null
    form.product_name = ''
    form.barcode = ''
    searchQuery.value = ''
    form.unit_price = 0
    duplicateTotal.value = 0
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

  // ===== 今日计数与重复提示 =====
  async function refreshTodayCount() {
    const { year, month } = monthParts(selectedDateModel.value)
    try {
      const res = await dailyProductionApi.records({
        year, month, production_date: selectedDateModel.value,
      })
      todayCount.value = res?.total ?? 0
    } catch {
      todayCount.value = 0
    }
  }

  /**
   * 今日 + 当前部门 + 该产品是否已有记录。
   * 用列表接口的 stats.total_quantity（跨页口径，与当前分页无关），不自己加总页面行。
   */
  async function checkDuplicate() {
    duplicateTotal.value = 0
    if (form.product_id == null || !form.product_name) return
    const { year, month } = monthParts(selectedDateModel.value)
    try {
      const res = await dailyProductionApi.records({
        year,
        month,
        production_date: selectedDateModel.value,
        department: formDept.value,
        keyword: form.product_name,
      })
      duplicateTotal.value = res?.stats?.total_quantity ?? 0
    } catch {
      duplicateTotal.value = 0
    }
  }

  function pickDept(value: string) {
    formDept.value = value
    deptMenuOpen.value = false
  }
  function pickDeptByIndex(index: number) {
    const dept = PRODUCTION_DEPARTMENTS[index]
    if (dept) pickDept(dept.value)
  }

  function clearEntryFields() {
    form.product_id = null
    form.product_name = ''
    form.barcode = ''
    form.unit_price = 0
    form.quantity = 0
    form.remark = ''
    searchQuery.value = ''
    Object.keys(formErrors).forEach((k) => (formErrors[k] = ''))
  }

  /** 提交成功后的清空：保留部门（连续录入同一部门是常态） */
  function resetQuickForm() {
    clearEntryFields()
    duplicateTotal.value = 0
    searchResults.value = []
    showDropdown.value = false
    searchActiveIndex.value = -1
  }

  function resetForm() {
    clearEntryFields()
    duplicateTotal.value = 0
    detailOpen.value = false
    deptMenuOpen.value = false
    lastCreated.value = null
    undoConfirmOpen.value = false
    searchResults.value = []
    showDropdown.value = false
    searchActiveIndex.value = -1
  }

  function closeEntryDrawer() {
    openModel.value = false
    resetForm()
  }

  function invalidateSummaries() {
    queryClient.invalidateQueries({ queryKey: ['daily-production-records'] })
    queryClient.invalidateQueries({ queryKey: ['daily-production-daily-summary'] })
    queryClient.invalidateQueries({ queryKey: ['daily-production-monthly-summary'] })
  }

  async function confirmSubmit() {
    isSubmitting.value = true
    try {
      const res = (await dailyProductionApi.createRecord({
        department: formDept.value,
        product_id: form.product_id,
        product_name: form.product_name,
        barcode: form.barcode,
        unit_price: form.unit_price || 0,
        quantity: form.quantity,
        production_value: Number(computedValue.value),
        production_date: selectedDateModel.value,
        remark: form.remark,
      } as Record<string, unknown>)) as { id?: number | null } | null

      const createdId = res?.id ?? null
      if (createdId != null) {
        lastCreated.value = {
          id: createdId,
          product_name: form.product_name,
          department: formDept.value,
          quantity: form.quantity,
        }
      }
      showToast('录入成功', 'success')
      // 提交即连续：清空表单、焦点回到搜索框，下一条可以立刻录
      resetQuickForm()
      nextTick(() => productSearchRef.value?.focus())
      invalidateSummaries()
      void refreshTodayCount()
    } catch (error: unknown) {
      const detail = (error as { response?: { data?: { detail?: string } } } | null)?.response?.data?.detail
      showToast(detail ?? '录入失败', 'error')
    } finally {
      isSubmitting.value = false
    }
  }

  async function handleSubmit() {
    // 防重复提交：连按 Ctrl+⏎ / 双击按钮都不能建出两条
    if (isSubmitting.value) return
    if (!validateForm()) return
    await confirmSubmit()
  }

  // ===== 撤销（物理删除，必须二次确认） =====
  function requestUndo() {
    if (lastCreated.value) undoConfirmOpen.value = true
  }

  async function confirmUndo() {
    const created = lastCreated.value
    undoConfirmOpen.value = false
    if (!created) return
    try {
      await dailyProductionApi.deleteRecord(created.id)
      lastCreated.value = null
      showToast('已撤销', 'success')
      invalidateSummaries()
      void refreshTodayCount()
      void checkDuplicate()
    } catch {
      showToast('撤销失败', 'error')
    }
  }

  /** 弹窗内的键盘流（挂在模态根节点，靠冒泡覆盖所有子输入框） */
  function onModalKeydown(event: KeyboardEvent) {
    if (event.altKey && !event.ctrlKey && !event.metaKey) {
      const idx = ALT_DEPT_KEYS.indexOf(event.key as (typeof ALT_DEPT_KEYS)[number])
      if (idx >= 0) {
        event.preventDefault()
        pickDeptByIndex(idx)
        return
      }
    }
    if (event.ctrlKey && event.key === 'Enter') {
      event.preventDefault()
      void handleSubmit()
      return
    }
    if (event.key === 'Escape') {
      closeEntryDrawer()
    }
  }

  watch(formDept, (value) => {
    try {
      localStorage.setItem(LAST_DEPT_KEY, value)
    } catch {
      /* localStorage 不可用时静默忽略 */
    }
    if (form.product_id != null) void checkDuplicate()
  })

  watch(
    openModel,
    (v) => {
      if (v) {
        void refreshTodayCount()
        nextTick(() => productSearchRef.value?.focus())
      }
    },
    { immediate: true },
  )

  onUnmounted(() => {
    if (searchTimer) clearTimeout(searchTimer)
    _timers.forEach(clearTimeout)
  })

  return {
    departments: PRODUCTION_DEPARTMENTS,
    formDept,
    currentDept,
    deptLabel,
    isSubmitting,
    detailOpen,
    deptMenuOpen,
    recentProducts,
    clearRecent,
    form,
    formErrors,
    computedValue,
    canSubmit,
    adjustQty,
    onQtyArrow,
    searchQuery,
    searchResults,
    showDropdown,
    searchLoading,
    searchError,
    searchActiveIndex,
    productSearchRef,
    quantityRef,
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
    todayCount,
    duplicateHint,
    lastCreated,
    undoConfirmOpen,
    undoText,
    requestUndo,
    confirmUndo,
    pickDept,
    pickDeptByIndex,
    onModalKeydown,
    todayLocal,
    prevDay,
  }
}
