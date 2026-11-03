/**
 * useProductionEntry — 生产数据录入弹窗业务逻辑（方向 A：一张单 = 多行 SKU）
 *
 * 与旧版（单对象 form）的根本差别：录入主体是 `rows`，一行一个 SKU，
 * 底部一次性提交。提交是**顺序**的——同一部门同一天的记录有先后语义，
 * 且部分失败时能精确说出是哪几行没进去，成功的行不会重来一遍。
 *
 * 保留的键盘流：Alt+1/2/3 切部门、搜索框 ↑↓ 选品 + ⏎ 加入一行并跳到该行数量、
 * 数量框 ↑↓ ∓1 / Shift+↑↓ ∓10、数量框 ⏎ 回搜索框继续加下一条、
 * Ctrl+⏎ 任意位置批量提交、Esc 分层（产品下拉 → 粘贴层 → 弹窗）。
 */
import { ref, computed, watch, nextTick, onUnmounted, type WritableComputedRef } from 'vue'
import { useQuery, useQueryClient } from '@tanstack/vue-query'
import { customerApi, dailyProductionApi, productApi } from '@/api'
import { showToast } from '@/composables/useToast'
import type { Product, ProductionDepartment } from '@/types'

/** 生产部门选项 */
export interface DepartmentOption {
  value: ProductionDepartment
  label: string
  icon: string
}

/** 一行 = 一个 SKU。key 是本地行号，与后端记录 id 无关。 */
export interface EntryRow {
  key: number
  product_id: number
  product_name: string
  barcode: string
  unit_price: number
  quantity: number
  remark: string
  /** 批次号：包装部成品库存沿用订单批次体系；其它部门按客户要求也可带 */
  batch_no: string
  is_custom: boolean
  custom_country: string
  /** 行级错误（校验失败 / 提交失败），展示在行下方，不清空用户输入 */
  error: string
  saving: boolean
}

/** 刚创建的记录（用于完成态清单与「撤销本批」） */
export interface CreatedRecordSummary {
  id: number
  product_name: string
  department: string
  quantity: number
  customer_name?: string
  batch_no?: string
  unit_price?: number
}

/** 右侧「最近客户添加」栏的一行 */
export interface RecentSku {
  product_id: number
  product_name: string
  barcode: string
  /** 最近一次给该客户录入的数量，仅作参考展示 */
  quantity: number
}

/** 包装部部门码：成品库存相关字段/校验只对它生效（避免字面量在多处漂移） */
export const PACKAGING_DEPT = 'packaging'

export const PRODUCTION_DEPARTMENTS: readonly DepartmentOption[] = [
  { value: 'filling', label: '充棉部', icon: 'fas fa-cloud' },
  { value: 'handcraft', label: '手工部', icon: 'fas fa-hand-sparkles' },
  { value: 'packaging', label: '包装部', icon: 'fas fa-box' },
]

const LAST_DEPT_KEY = 'production.lastDepartment'
const DRAFT_KEY = 'production.entryDraft'
const DEFAULT_DEPT = 'filling'
/** 一张单的上限：再多的行既滚不动，也让部分失败的排查变长 */
export const MAX_ROWS = 50
/** Alt+1/2/3 对应 departments 的下标 */
const ALT_DEPT_KEYS = ['1', '2', '3'] as const

function readStorage(key: string): string | null {
  try {
    return localStorage.getItem(key)
  } catch {
    return null
  }
}
function writeStorage(key: string, value: string) {
  try {
    localStorage.setItem(key, value)
  } catch {
    /* localStorage 不可用时静默忽略（隐私模式等） */
  }
}

/** 上次使用的部门；非法/不可读时回落到默认部门 */
function loadLastDept(): string {
  const v = readStorage(LAST_DEPT_KEY)
  return v && PRODUCTION_DEPARTMENTS.some((d) => d.value === v) ? v : DEFAULT_DEPT
}

/** 'YYYY-MM-DD' → { year, month }（records 接口要求年/月或区间二选一） */
function monthParts(dateStr: string): { year: number; month: number } {
  const d = new Date(dateStr + 'T00:00:00')
  return { year: d.getFullYear(), month: d.getMonth() + 1 }
}

function errorDetail(error: unknown, fallback: string): string {
  return (error as { response?: { data?: { detail?: string } } } | null)?.response?.data?.detail ?? fallback
}

export function useProductionEntry(
  openModel: WritableComputedRef<boolean>,
  selectedDateModel: WritableComputedRef<string>,
) {
  const queryClient = useQueryClient()
  const _timers: ReturnType<typeof setTimeout>[] = []

  const formDept = ref(loadLastDept())
  const isSubmitting = ref(false)
  const submitState = ref<'editing' | 'done'>('editing')
  const createdBatch = ref<CreatedRecordSummary[]>([])
  const undoConfirmOpen = ref(false)
  const pasteOpen = ref(false)

  /** 右侧「最近客户添加」：该客户最近录入过生产记录的 SKU（按最近一次录入倒序） */
  const customerRecent = ref<RecentSku[]>([])
  const recentLoading = ref(false)
  let _recentSeq = 0

  // ===== 行（录入主体） =====
  const rows = ref<EntryRow[]>([])
  let _rowKey = 0

  const customerId = ref<number | null>(null)
  const customerName = ref('')

  const { data: customerData } = useQuery({
    queryKey: ['customer-active-names'],
    queryFn: () => customerApi.activeNames(),
    staleTime: 5 * 60 * 1000,
  })
  const customerOptions = computed(() => customerData.value ?? [])

  // ===== 批次号列：只跟部门走——包装部显示（选填），充棉/手工不需要 =====
  const isPackaging = computed(() => formDept.value === PACKAGING_DEPT)
  /** 2026-11-01 owner 裁决：批次号跟部门走，不跟客户走。
   *  未填批次的包装部记录进成品库存时按「未分批次」兜底。 */
  const batchColumnOn = computed(() => isPackaging.value)
  const batchFilledCount = computed(() => rows.value.filter((r) => r.batch_no.trim()).length)

  // ===== 合计与提交门槛 =====
  const totals = computed(() => {
    const qty = rows.value.reduce((s, r) => s + (Number(r.quantity) || 0), 0)
    const value = rows.value.reduce((s, r) => s + (Number(r.quantity) || 0) * (Number(r.unit_price) || 0), 0)
    return { sku: rows.value.length, qty, value }
  })
  const canSubmit = computed(
    () =>
      customerId.value != null // 客户必填：没选客户就不给提交
      && rows.value.length > 0
      && rows.value.every((r) => Number(r.quantity) > 0)
      && !isSubmitting.value,
  )

  const todayCount = ref(0)
  const currentDept = computed(
    () => PRODUCTION_DEPARTMENTS.find((d) => d.value === formDept.value) ?? PRODUCTION_DEPARTMENTS[0]!,
  )
  function deptLabel(value: string): string {
    return PRODUCTION_DEPARTMENTS.find((d) => d.value === value)?.label ?? value
  }

  function adjustRowQty(row: EntryRow, delta: number) {
    const cur = Number(row.quantity) || 0
    row.quantity = Math.max(0, Math.min(999999, cur + delta))
    if (row.error) row.error = ''
  }
  /** 数量框 ↑↓（Shift 时为 ±10） */
  function onRowQtyArrow(row: EntryRow, direction: number, event: KeyboardEvent) {
    adjustRowQty(row, direction * (event.shiftKey ? 10 : 1))
  }
  /** 数量框 ⏎ = 这一条录完，回搜索框加下一条（键盘流不断线） */
  function onRowQtyEnter() {
    productSearchRef.value?.focus()
  }

  function focusRowQty(key: number) {
    nextTick(() => {
      const el = document.querySelector<HTMLInputElement>(`[data-qty-key="${key}"]`)
      el?.focus()
    })
  }

  // ===== 产品搜索（保留 H7 竞态护栏） =====
  const searchQuery = ref('')
  const searchResults = ref<Product[]>([])
  const showDropdown = ref(false)
  const searchLoading = ref(false)
  const searchError = ref('')
  const searchActiveIndex = ref(-1)
  const productSearchRef = ref<HTMLInputElement>()
  let searchTimer: ReturnType<typeof setTimeout> | null = null
  let _searchSeq = 0

  function resetSearch() {
    searchQuery.value = ''
    searchResults.value = []
    showDropdown.value = false
    searchActiveIndex.value = -1
    searchLoading.value = false
    searchError.value = ''
    _searchSeq += 1
  }

  /** 搜索框提示语：选了客户又没输关键字时，下拉里铺的是该客户可见的 SKU */
  const searchHint = computed(() => {
    if (searchQuery.value.trim()) return ''
    if (customerId.value == null) return ''
    return `${customerName.value || '该客户'} 可见的产品`
  })

  /**
   * 取产品。选了客户走 /products/list + customer_id：后端 visible_to_customer 的语义是
   * 「属于该客户，或未挂客户」——未分配归属的通用 SKU 不会被挡掉，和生产现场一致。
   * 没选客户时沿用 /products/search 的全库搜索。
   */
  async function fetchProducts(keyword: string): Promise<Product[]> {
    if (customerId.value != null) {
      const res = await productApi.list({
        customer_id: customerId.value,
        search: keyword || undefined,
        page: 1,
        per_page: 20,
      })
      return res?.items ?? []
    }
    const res = (await productApi.search(keyword)) as unknown as Product[] & { products?: Product[] }
    return res.products ?? res ?? []
  }

  /** 聚焦且没输关键字：直接把该客户可见的产品铺出来，省掉「先想关键词」这一步 */
  async function browseCustomerProducts() {
    if (customerId.value == null) return
    const seq = ++_searchSeq
    searchLoading.value = true
    searchActiveIndex.value = -1
    showDropdown.value = true
    try {
      const list = await fetchProducts('')
      if (seq !== _searchSeq) return
      searchResults.value = list
      searchError.value = ''
    } catch {
      if (seq !== _searchSeq) return
      searchError.value = '产品加载失败，请重试'
      searchResults.value = []
    } finally {
      if (seq === _searchSeq) searchLoading.value = false
    }
  }

  function onSearchInput() {
    if (searchTimer) clearTimeout(searchTimer)
    searchError.value = ''
    const kw = searchQuery.value.trim()
    const seq = ++_searchSeq
    if (!kw) {
      searchResults.value = []
      searchActiveIndex.value = -1
      if (customerId.value != null) {
        // 清空关键字 = 回到「这个客户有哪些 SKU」，而不是把下拉收掉
        void browseCustomerProducts()
      } else {
        showDropdown.value = false
        searchLoading.value = false
      }
      return
    }
    searchLoading.value = true
    showDropdown.value = true
    searchActiveIndex.value = -1
    searchTimer = setTimeout(async () => {
      try {
        const list = await fetchProducts(kw)
        if (seq !== _searchSeq || searchQuery.value.trim() !== kw) return
        searchResults.value = list
        searchError.value = ''
      } catch {
        if (seq !== _searchSeq || searchQuery.value.trim() !== kw) return
        searchError.value = '产品搜索失败，请重试'
        searchResults.value = []
      } finally {
        if (seq === _searchSeq) searchLoading.value = false
      }
    }, 300)
  }
  function onSearchFocus() {
    // 聚焦只负责「收着的下拉重新展开」，不主动拉数据——
    // 否则打开录入页时的自动聚焦会把产品列表整个弹出来（已定位过的 BUG）。
    const kw = searchQuery.value.trim()
    if (kw) {
      if (searchResults.value.length || searchError.value) showDropdown.value = true
      return
    }
    if (customerId.value != null && searchResults.value.length) showDropdown.value = true
  }
  /** 用户点击搜索框才展开该客户的产品列表（键盘 Tab 聚焦不触发） */
  function onSearchClick() {
    if (searchQuery.value.trim()) return
    if (customerId.value != null && !searchResults.value.length) void browseCustomerProducts()
  }
  let _blurTimer: ReturnType<typeof setTimeout> | null = null
  function onSearchBlur() {
    if (_blurTimer) clearTimeout(_blurTimer)
    _blurTimer = setTimeout(() => {
      _blurTimer = null
      showDropdown.value = false
      searchActiveIndex.value = -1
    }, 150)
  }
  function cancelBlurClose() {
    if (_blurTimer) {
      clearTimeout(_blurTimer)
      _blurTimer = null
    }
  }
  function moveSearchIndex(delta: number) {
    if (!searchResults.value.length) return
    searchActiveIndex.value += delta
    if (searchActiveIndex.value < 0) searchActiveIndex.value = searchResults.value.length - 1
    if (searchActiveIndex.value >= searchResults.value.length) searchActiveIndex.value = 0
  }
  function confirmSearchSelection() {
    if (!searchResults.value.length) return
    // 没按过 ↑↓ 时回落到第一条：否则「输入产品名 → ⏎」是静默无反应
    const idx = searchActiveIndex.value >= 0 ? searchActiveIndex.value : 0
    const product = searchResults.value[idx]
    if (product) void selectProduct(product)
  }

  /** 选中产品 = 追加一行（不再覆盖某个表单），随后焦点落到该行数量 */
  /**
   * 加一行。
   * @param keepOpen 点下拉条目时为 true：保留搜索结果、下拉不收起、焦点留在搜索框，
   *   让用户能连着点好几个 SKU；回车加行走 false（清空搜索并把焦点移到数量）。
   */
  async function selectProduct(product: Product, keepOpen = false) {
    if (rows.value.length >= MAX_ROWS) {
      showToast(`一张单最多 ${MAX_ROWS} 个 SKU，请先提交这一批`, 'warning')
      return
    }
    const row: EntryRow = {
      key: ++_rowKey,
      product_id: product.id,
      product_name: product.name,
      barcode: product.barcode || '',
      unit_price: 0,
      quantity: 0,
      remark: '',
      batch_no: '',
      is_custom: false,
      custom_country: '',
      error: '',
      saving: false,
    }
    rows.value.push(row)
    // push 进去的是原始对象，后续必须改**响应式代理**（rows.value 里那一个），
    // 直接写 row 只会改到 raw target：值变了但视图不重渲染（单价/重复提示会一直显示 0）。
    const liveRow = rows.value[rows.value.length - 1]!
    if (keepOpen) {
      // 连续点击模式：下拉与结果原样留着，焦点还给搜索框（否则会触发失焦收起）
      cancelBlurClose()
      showDropdown.value = true
      void nextTick(() => productSearchRef.value?.focus())
    } else {
      resetSearch()
      // 焦点必须立刻落到新行数量：单价要等接口回来，等到那时候再聚焦，
      // 用户前几百毫秒敲的数字会全部丢失（键盘流的致命回退）
      focusRowQty(liveRow.key)
    }
    // 单价按行取：只写回这一行，行被删或用户已手填就不再覆盖
    try {
      const infoRes = await dailyProductionApi.productInfo(product.id)
      if (infoRes?.data?.price && rows.value.includes(liveRow) && !liveRow.unit_price) {
        liveRow.unit_price = infoRes.data.price
      }
    } catch {
      // 获取单价失败不阻断（保持 0，行内可手填）
    }
  }

  function removeRow(row: EntryRow) {
    rows.value = rows.value.filter((r) => r !== row)
  }
  function clearRows() {
    rows.value = []
    clearDraft()
  }

  function selectCustomer(id: number | null) {
    customerId.value = id
    customerName.value = id == null ? '' : customerOptions.value.find((c) => c.id === id)?.name ?? ''
    // 客户变了，上一批结果属于别的客户，必须作废；搜索框正开着就立刻换成本客户的
    _searchSeq += 1
    searchResults.value = []
    searchActiveIndex.value = -1
    if (id != null && document.activeElement === productSearchRef.value) {
      void browseCustomerProducts()
    } else if (id == null) {
      showDropdown.value = false
    }
    void loadCustomerRecent()
  }

  /** 'YYYY-MM-DD' 往前推 n 天（本地时区，避免 toISOString 的 UTC 偏移） */
  function daysBefore(dateStr: string, n: number): string {
    const d = new Date(dateStr + 'T00:00:00')
    d.setDate(d.getDate() - n)
    const m = String(d.getMonth() + 1).padStart(2, '0')
    const day = String(d.getDate()).padStart(2, '0')
    return `${d.getFullYear()}-${m}-${day}`
  }

  /**
   * 右侧「最近客户添加」：该客户近 90 天录入过的 SKU，按最近一次录入去重。
   *
   * 记录接口没有 customer_id 过滤参数，但每行都带 customer_id / customer_name，
   * 一次 200 行足够覆盖活跃客户的近期 SKU；优先按 id 匹配，历史数据 id 为空时用名字兜底。
   */
  async function loadCustomerRecent() {
    const cid = customerId.value
    if (cid == null) {
      customerRecent.value = []
      recentLoading.value = false
      return
    }
    const seq = ++_recentSeq
    recentLoading.value = true
    try {
      const end = selectedDateModel.value
      const res = await dailyProductionApi.records({
        start_date: daysBefore(end, 90),
        end_date: end,
        sort: 'desc',
        page: 1,
        per_page: 200,
      })
      if (seq !== _recentSeq) return
      const name = customerName.value
      const seen = new Set<number>()
      const list: RecentSku[] = []
      for (const rec of res?.data ?? []) {
        const sameCustomer = rec.customer_id != null
          ? rec.customer_id === cid
          : !!name && rec.customer_name === name
        if (!sameCustomer || rec.product_id == null || seen.has(rec.product_id)) continue
        seen.add(rec.product_id)
        list.push({
          product_id: rec.product_id,
          product_name: rec.product_name,
          barcode: rec.barcode ?? '',
          quantity: rec.quantity,
        })
        if (list.length >= 10) break
      }
      customerRecent.value = list
    } catch {
      if (seq === _recentSeq) customerRecent.value = []
    } finally {
      if (seq === _recentSeq) recentLoading.value = false
    }
  }

  /** 点右侧条目 = 直接加一行，和搜索选中走同一条路径 */
  function addRecentSku(item: RecentSku) {
    void selectProduct({ id: item.product_id, name: item.product_name, barcode: item.barcode } as Product)
  }

  /** 右侧栏空态里的「浏览该客户的产品」：聚焦搜索框即会拉该客户的产品 */
  function browseProducts() {
    productSearchRef.value?.focus()
    if (customerId.value != null) void browseCustomerProducts()
  }

  // ===== 今日计数与重复提示 =====
  async function refreshTodayCount() {
    const { year, month } = monthParts(selectedDateModel.value)
    try {
      const res = await dailyProductionApi.records({ year, month, production_date: selectedDateModel.value })
      todayCount.value = res?.total ?? 0
    } catch {
      todayCount.value = 0
    }
  }

  // ===== 校验 =====
  function validateRows(): boolean {
    if (customerId.value == null) {
      showToast('请先选择客户（客户为必填项）', 'warning')
      return false
    }
    if (!rows.value.length) {
      showToast('请先加入至少一个 SKU', 'warning')
      return false
    }
    let ok = true
    rows.value.forEach((r) => {
      r.error = ''
      const qty = Number(r.quantity)
      if (!qty || qty <= 0) {
        r.error = '生产数量必须大于 0'
        ok = false
      } else if (qty > 999999) {
        r.error = '生产数量不能超过 999999'
        ok = false
      }
    })
    if (!ok) showToast('有 SKU 未通过校验，按行内红字修正后再提交', 'error')
    return ok
  }

  function payloadOf(row: EntryRow): Record<string, unknown> {
    return {
      department: formDept.value,
      product_id: row.product_id,
      customer_id: customerId.value,
      product_name: row.product_name,
      barcode: row.barcode,
      unit_price: row.unit_price || 0,
      quantity: row.quantity,
      production_value: Number((row.quantity || 0) * (row.unit_price || 0)),
      production_date: selectedDateModel.value,
      remark: row.remark,
      // batch_no 后端不限部门存储，客户要求时其它部门也要带上；
      // 定制字段仅包装部有意义，不传避免脏数据
      batch_no: row.batch_no.trim() || null,
      ...(isPackaging.value
        ? { is_custom: row.is_custom, custom_country: row.is_custom ? row.custom_country.trim() || null : null }
        : {}),
    }
  }

  function invalidateSummaries() {
    queryClient.invalidateQueries({ queryKey: ['daily-production-records'] })
    queryClient.invalidateQueries({ queryKey: ['daily-production-daily-summary'] })
    queryClient.invalidateQueries({ queryKey: ['daily-production-monthly-summary'] })
    queryClient.invalidateQueries({ queryKey: ['finished-stock'] })
  }

  /**
   * 批量提交：顺序逐条创建。
   * 全部成功 → 进完成态（可整批撤销）；有失败 → 只把失败的行留在表里，
   * 成功的行从表中移除，不会重复建单，用户只需重试剩下的。
   */
  async function submitBatch() {
    if (isSubmitting.value) return
    if (submitState.value === 'done') return
    if (!validateRows()) return
    isSubmitting.value = true
    const created: CreatedRecordSummary[] = []
    const failed: EntryRow[] = []
    for (const row of [...rows.value]) {
      row.saving = true
      row.error = ''
      try {
        const res = (await dailyProductionApi.createRecord(payloadOf(row))) as { id?: number | null } | null
        const createdId = res?.id ?? null
        if (createdId == null) throw new Error('创建未返回记录 id')
        created.push({
          id: createdId,
          product_name: row.product_name,
          department: formDept.value,
          quantity: row.quantity,
          customer_name: customerName.value,
          batch_no: row.batch_no,
          unit_price: row.unit_price,
        })
      } catch (error: unknown) {
        row.error = errorDetail(error, '提交失败，请重试')
        failed.push(row)
      } finally {
        row.saving = false
      }
    }
    isSubmitting.value = false
    invalidateSummaries()
    void refreshTodayCount()

    if (!failed.length) {
      createdBatch.value = created
      rows.value = []
      clearDraft()
      submitState.value = 'done'
      // 刚录的 SKU 应该立刻出现在右侧「最近客户添加」的顶部
      void loadCustomerRecent()
      showToast(`已录入 ${created.length} 条生产记录`, 'success')
      return
    }
    rows.value = failed
    if (created.length) {
      showToast(`已录入 ${created.length} 条，${failed.length} 条失败——只剩失败的行，可直接重试`, 'warning')
    } else {
      showToast('提交失败，请检查行内提示', 'error')
    }
  }

  // ===== 撤销整批（物理删除，必须二次确认） =====
  const undoText = computed(() => {
    const n = createdBatch.value.length
    const first = createdBatch.value[0]
    return first ? `撤销刚才录入的 ${n} 条记录（含「${first.product_name}」等）？` : '撤销刚才录入的记录？'
  })
  function requestUndo() {
    if (createdBatch.value.length) undoConfirmOpen.value = true
  }
  async function confirmUndo() {
    const targets = [...createdBatch.value]
    undoConfirmOpen.value = false
    if (!targets.length) return
    const remaining: CreatedRecordSummary[] = []
    for (const item of targets) {
      try {
        await dailyProductionApi.deleteRecord(item.id)
      } catch (error: unknown) {
        remaining.push(item, ...targets.slice(targets.indexOf(item) + 1))
        createdBatch.value = remaining
        showToast(errorDetail(error, '撤销失败'), 'error')
        invalidateSummaries()
        void refreshTodayCount()
        return
      }
    }
    createdBatch.value = []
    showToast('已撤销本批录入', 'success')
    invalidateSummaries()
    void refreshTodayCount()
    // 整批都删掉了就回到录入态，否则完成态会停在「已录入 0 条」的空回执上
    submitState.value = 'editing'
    nextTick(() => productSearchRef.value?.focus())
  }

  // ===== 草稿（关弹窗自动留底，避免多行录入被一次误关清掉） =====
  function saveDraft(silent = false) {
    if (!rows.value.length) return
    writeStorage(DRAFT_KEY, JSON.stringify({
      date: selectedDateModel.value,
      department: formDept.value,
      customer_id: customerId.value,
      customer_name: customerName.value,
      rows: rows.value.map((r) => ({
        product_id: r.product_id,
        product_name: r.product_name,
        barcode: r.barcode,
        unit_price: r.unit_price,
        quantity: r.quantity,
        remark: r.remark,
        batch_no: r.batch_no,
        is_custom: r.is_custom,
        custom_country: r.custom_country,
      })),
    }))
    if (!silent) showToast(`草稿已保存到本机（${rows.value.length} 个 SKU）`, 'success')
  }
  function clearDraft() {
    try {
      localStorage.removeItem(DRAFT_KEY)
    } catch {
      /* 忽略 */
    }
  }
  function restoreDraft() {
    const raw = readStorage(DRAFT_KEY)
    if (!raw) return
    try {
      const draft = JSON.parse(raw) as {
        date?: string
        department?: string
        customer_id?: number | null
        customer_name?: string
        rows?: Array<Partial<EntryRow>>
      }
      if (!Array.isArray(draft.rows) || !draft.rows.length) return
      // 草稿是「某一天的单据」，跨日期恢复会把昨天的数量记到今天头上
      if (draft.date && draft.date !== selectedDateModel.value) {
        showToast(`上次草稿属于 ${draft.date}，未恢复`, 'info')
        return
      }
      if (draft.department && PRODUCTION_DEPARTMENTS.some((d) => d.value === draft.department)) {
        formDept.value = draft.department
      }
      customerId.value = draft.customer_id ?? null
      customerName.value = draft.customer_name ?? ''
      rows.value = draft.rows.slice(0, MAX_ROWS).map((r) => ({
        key: ++_rowKey,
        product_id: Number(r.product_id),
        product_name: String(r.product_name ?? ''),
        barcode: String(r.barcode ?? ''),
        unit_price: Number(r.unit_price) || 0,
        quantity: Number(r.quantity) || 0,
        remark: String(r.remark ?? ''),
        batch_no: String(r.batch_no ?? ''),
        is_custom: Boolean(r.is_custom),
        custom_country: String(r.custom_country ?? ''),
        error: '',
        saving: false,
      }))
      showToast(`已恢复上次未提交的 ${rows.value.length} 个 SKU`, 'info')
      } catch {
      clearDraft()
    }
  }

  // ===== 粘贴导入（Excel：产品名或 69 码 / 数量 / 批次号） =====
  async function importPaste(text: string): Promise<void> {
    const lines = text.split(/\r?\n/).map((l) => l.trim()).filter(Boolean)
    if (!lines.length) return
    const matched: Array<{ product: Product; qty: number; batch: string }> = []
    const unmatched: string[] = []
    for (const line of lines) {
      const cols = line.split(/\t|,|\s{2,}/).map((s) => s.trim()).filter(Boolean)
      const nameOrCode = cols[0] ?? ''
      if (!nameOrCode) continue
      try {
        const res = (await productApi.search(nameOrCode)) as unknown as Product[] & { products?: Product[] }
        const list = res.products ?? res ?? []
        // 只接受精确命中（产品名或 69 码）：退而求其次取第一条会录错产品
        const product = list.find((p) => p.name === nameOrCode || p.barcode === nameOrCode)
        if (!product) {
          unmatched.push(nameOrCode)
          continue
        }
        matched.push({ product, qty: Math.max(0, parseInt(cols[1] ?? '0', 10) || 0), batch: cols[2] ?? '' })
      } catch {
        unmatched.push(nameOrCode)
      }
    }
    if (!matched.length) {
      showToast('没有识别到可导入的行（需精确匹配产品名或 69 码）', 'error')
      return
    }
    const room = MAX_ROWS - rows.value.length
    matched.slice(0, Math.max(0, room)).forEach(({ product, qty, batch }) => {
      rows.value.push({
        key: ++_rowKey,
        product_id: product.id,
        product_name: product.name,
        barcode: product.barcode || '',
        unit_price: 0,
        quantity: qty,
        remark: '',
        batch_no: batch,
        is_custom: false,
        custom_country: '',
        error: '',
        saving: false,
      })
    })
    // 单价并行补齐；重复提示走缓存
    await Promise.all(rows.value.filter((r) => !r.unit_price).map(async (r) => {
      try {
        const infoRes = await dailyProductionApi.productInfo(r.product_id)
        if (infoRes?.data?.price && rows.value.includes(r) && !r.unit_price) r.unit_price = infoRes.data.price
      } catch {
        /* 单价失败可手填 */
      }
    }))
    const dropped = matched.length - Math.min(matched.length, Math.max(0, room))
    const parts = [`已导入 ${Math.min(matched.length, Math.max(0, room))} 行`]
    if (unmatched.length) parts.push(`${unmatched.length} 行未精确匹配到产品`)
    if (dropped > 0) parts.push(`${dropped} 行超出单张上限被跳过`)
    showToast(parts.join('，'), unmatched.length || dropped > 0 ? 'warning' : 'success')
  }

  // ===== 开关与部门 =====
  function pickDept(value: string) {
    formDept.value = value
  }
  function pickDeptByIndex(index: number) {
    const dept = PRODUCTION_DEPARTMENTS[index]
    if (dept) pickDept(dept.value)
  }

  function startNewBatch() {
    submitState.value = 'editing'
    createdBatch.value = []
    rows.value = []
    resetSearch()
    nextTick(() => productSearchRef.value?.focus())
  }

  function closeEntryDrawer() {
    // 有未提交的行就留草稿：多行录入被一次 Esc/误关清掉是这版最不能接受的回退
    if (rows.value.length) saveDraft(true)
    openModel.value = false
    submitState.value = 'editing'
    createdBatch.value = []
    undoConfirmOpen.value = false
    pasteOpen.value = false
    resetSearch()
  }

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
      // 粘贴层里的 Ctrl+⏎ 是「导入」，不是提交整单
      if (pasteOpen.value) return
      event.preventDefault()
      void submitBatch()
      return
    }
    if (event.key === 'Escape') {
      if (showDropdown.value) {
        showDropdown.value = false
        searchActiveIndex.value = -1
        event.stopPropagation()
        return
      }
      if (pasteOpen.value) {
        pasteOpen.value = false
        event.stopPropagation()
        return
      }
      closeEntryDrawer()
    }
  }

  watch(formDept, (value) => {
    writeStorage(LAST_DEPT_KEY, value)
  })
  watch(selectedDateModel, () => {
    void refreshTodayCount()
    // 最近 90 天的窗口以选中日期为终点，日期变了要重算
    void loadCustomerRecent()
  })

  watch(
    openModel,
    (v) => {
      if (v) {
        void refreshTodayCount()
        if (!rows.value.length) restoreDraft()
        void loadCustomerRecent()
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
    isPackaging,
    isSubmitting,
    submitState,
    createdBatch,
    undoConfirmOpen,
    undoText,
    pasteOpen,
    customerRecent,
    recentLoading,
    addRecentSku,
    browseProducts,
    rows,
    totals,
    canSubmit,
    customerId,
    customerName,
    customerOptions,
    selectCustomer,
    batchColumnOn,
    batchFilledCount,
    onRowQtyArrow,
    onRowQtyEnter,
    selectProduct,
    removeRow,
    clearRows,
    searchQuery,
    searchResults,
    showDropdown,
    searchLoading,
    searchError,
    searchActiveIndex,
    productSearchRef,
    searchHint,
    onSearchInput,
    onSearchFocus,
    onSearchClick,
    onSearchBlur,
    moveSearchIndex,
    confirmSearchSelection,
    resetSearch,
    submitBatch,
    requestUndo,
    confirmUndo,
    saveDraft,
    clearDraft,
    importPaste,
    startNewBatch,
    todayCount,
    closeEntryDrawer,
    pickDept,
    onModalKeydown,
  }
}
