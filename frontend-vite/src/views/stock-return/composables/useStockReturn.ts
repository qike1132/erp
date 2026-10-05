/**
 * useStockReturn — 退货管理页面业务逻辑
 *
 * P1 录入变更：退货 = 选产品 + 数量（不关联出货单/订单），库存 +N、流水留痕。
 * 封装退货列表查询（服务端分页 + 客户/日期筛选）、
 * 新增退货（页内选产品）、取消（P1-① 软取消，带确认对话框）。
 */
import { ref, reactive, computed } from 'vue'
import { useQuery, keepPreviousData } from '@tanstack/vue-query'
import { stockReturnApi } from '@/api'
import type { Customer, Product } from '@/types'
import { showToast } from '@/composables/useToast'
import { useApiMutation } from '@/composables/useApiMutation'
import { useDebouncedSearch } from '@/composables/useDebouncedSearch'
import { useConfirmDialog } from '@/composables/useConfirmDialog'
import { useAuthStore } from '@/stores/auth'
import { useCatalogStore } from '@/stores/catalog'
import type { StockReturnCreatePayload } from '@/api/stockReturn'

/** 退货原因受控选项（P1 起落字典表；当前与后端 reason String(200) 自由文本兼容） */
export const RETURN_REASON_OPTIONS = ['质量问题', '错发', '多送', '客户不要', '换货', '其他'] as const

/** 新增退货表单（按产品制） */
export interface StockReturnFormData {
  product_id: number | null
  product_name: string
  customer: string
  quantity: number | null
  reason: string
  note: string
}

function emptyForm(): StockReturnFormData {
  return {
    product_id: null,
    product_name: '',
    customer: '',
    quantity: null,
    reason: '',
    note: '',
  }
}

function validateReturnForm(form: StockReturnFormData): string | null {
  if (!form.customer) return '请先选择客户'
  if (!form.product_id) return '请先选择产品'
  const qty = form.quantity
  if (qty == null || !Number.isInteger(qty) || qty <= 0) return '退货数量必须为正整数'
  if (!form.reason) return '请选择退货原因'
  return null
}

/** 幂等令牌：每次打开弹窗重新生成；同一次弹窗内的网络重试视为同一请求 */
function newRequestId(): string {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
    return crypto.randomUUID()
  }
  return `req-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`
}

export function useStockReturn() {
  const auth = useAuthStore()
  const catalog = useCatalogStore()
  const confirmDialog = useConfirmDialog()
  const actionId = ref<number | ''>(0)

  // ---------- 列表查询（服务端分页 + 筛选） ----------
  const searchTerm = ref('')
  const startDate = ref('')
  const endDate = ref('')
  const currentPage = ref(1)
  const perPage = 20

  const { debounceSearch } = useDebouncedSearch()
  const debouncedSearch = ref('')

  function onSearchInput() {
    debounceSearch(() => {
      debouncedSearch.value = searchTerm.value
      currentPage.value = 1
    })
  }

  function clearSearch() {
    searchTerm.value = ''
    debouncedSearch.value = ''
    startDate.value = ''
    endDate.value = ''
    currentPage.value = 1
  }

  function applyFilter() {
    debouncedSearch.value = searchTerm.value
    currentPage.value = 1
  }

  const { data: result, isLoading } = useQuery({
    queryKey: [
      'stock-returns-list',
      () => debouncedSearch.value,
      () => startDate.value,
      () => endDate.value,
      () => currentPage.value,
    ],
    queryFn: () =>
      stockReturnApi.list({
        per_page: perPage,
        page: currentPage.value,
        customer: debouncedSearch.value || undefined,
        start_date: startDate.value || undefined,
        end_date: endDate.value || undefined,
      }),
    // 本 composable 也会在出货行（StockOutRecords）实例化——无退货查看权限的
    // 访客不应发出 /stock-returns/list 请求，否则后端记 403 审计噪音
    enabled: computed(() => auth.hasPermission('stock_return_view')),
    staleTime: 30_000,
    gcTime: 60_000,
    placeholderData: keepPreviousData,
  })

  const returns = computed(() => result.value?.data ?? [])
  const totalItems = computed(() => result.value?.total ?? 0)

  function goPage(p: number) {
    currentPage.value = p
  }

  // ---------- 新增退货（按产品制） ----------
  const formOpen = ref(false)
  const form = reactive<StockReturnFormData>(emptyForm())
  const submitting = ref(false)
  /** P1-③ 幂等令牌：打开弹窗时生成一次 */
  const requestId = ref('')

  /** 产品/客户下拉（catalog store 懒加载 + 跨页缓存） */
  const products = computed<Product[]>(() => catalog.products)
  const customers = computed<Customer[]>(() => catalog.customers)
  const loadingCatalog = ref(false)

  async function openStandalone() {
    Object.assign(form, emptyForm())
    requestId.value = newRequestId()
    formOpen.value = true
    if (products.value.length > 0 && customers.value.length > 0) return
    loadingCatalog.value = true
    try {
      await Promise.all([catalog.ensureProducts(), catalog.ensureCustomers()])
    } catch {
      showToast('产品/客户列表加载失败', 'warning')
    } finally {
      loadingCatalog.value = false
    }
  }

  function onProductPicked(productId: number | null) {
    const row = products.value.find((p) => p.id === productId) ?? null
    Object.assign(form, {
      product_id: row?.id ?? null,
      product_name: row?.name ?? '',
    })
  }

  const createMutation = useApiMutation(
    (payload: StockReturnCreatePayload) => stockReturnApi.create(payload),
    {
      invalidateKeys: ['stock-returns-list', 'inventory'],
      successMsg: '退货添加成功',
      errorMsg: '退货添加失败',
    },
  )

  async function handleSubmit() {
    const error = validateReturnForm(form)
    if (error) {
      showToast(error, 'warning')
      return
    }
    submitting.value = true
    try {
      const created = await createMutation.run({
        product_id: form.product_id as number,
        quantity: form.quantity as number,
        customer: form.customer || undefined,
        reason: form.reason,
        note: form.note || undefined,
        request_id: requestId.value || undefined,
      })
      if (created !== undefined) {
        formOpen.value = false
        Object.assign(form, emptyForm())
      }
    } finally {
      submitting.value = false
    }
  }

  // ---------- 取消退货（P1-① 软取消） ----------
  const deleteMutation = useApiMutation((id: number) => stockReturnApi.remove(id), {
    invalidateKeys: ['stock-returns-list', 'inventory'],
    successMsg: '退货取消成功',
    errorMsg: '退货取消失败',
  })

  async function handleDelete(row: { id: number; return_no: string; quantity: number }) {
    const ok = await confirmDialog.confirm(
      `确定要取消退货单 ${row.return_no}（${row.quantity} 件）吗？库存将对称扣回，记录保留可追溯。`,
    )
    if (!ok) return
    actionId.value = row.id
    await deleteMutation.run(row.id)
    actionId.value = 0
  }

  return {
    confirmDialog,
    actionId,
    searchTerm,
    startDate,
    endDate,
    currentPage,
    perPage,
    onSearchInput,
    clearSearch,
    applyFilter,
    isLoading,
    returns,
    totalItems,
    goPage,
    debouncedSearch,
    formOpen,
    form,
    submitting,
    products,
    customers,
    loadingCatalog,
    openStandalone,
    onProductPicked,
    handleSubmit,
    handleDelete,
  }
}
