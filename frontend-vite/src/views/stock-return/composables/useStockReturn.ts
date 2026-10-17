/**
 * useStockReturn - 退货管理页面业务逻辑
 *
 * 录入流程：新建退货单 -> 搜索产品名 -> 弹出该产品全部出货明细
 * -> 勾选要退的明细 -> 录数量。可退量 = 明细出货量 - 已退量。
 * 取消为硬删除（记录移除、库存对称扣回；流水已记「退货」「退货取消」两条，不丢对账真相）。
 */
import { ref, reactive, computed } from 'vue'
import { useQuery, keepPreviousData } from '@tanstack/vue-query'
import { stockReturnApi } from '@/api'
import { showToast } from '@/composables/useToast'
import { useApiMutation } from '@/composables/useApiMutation'
import { useDebouncedSearch } from '@/composables/useDebouncedSearch'
import { useConfirmDialog } from '@/composables/useConfirmDialog'
import { useAuthStore } from '@/stores/auth'
import type {
  ShipmentOption,
  StockReturnCreatePayload,
  StockReturnRecord,
  StockReturnUpdatePayload,
} from '@/api/stockReturn'
import type { ReturnEditForm } from '@/views/report/composables/useReportRowActions'

/** 退货原因受控选项（P1 起落字典表；当前与后端 reason String(200) 自由文本兼容） */
export const RETURN_REASON_OPTIONS = ['质量问题', '错发', '多送', '客户不要', '换货', '其他'] as const

/** 新增退货表单（关联所选出货明细） */
export interface StockReturnFormData {
  stockout_id: number | null
  stockout_no: string
  product_name: string
  customer: string
  quantity: number | null
  available: number | null
  reason: string
  note: string
}

function emptyForm(): StockReturnFormData {
  return {
    stockout_id: null,
    stockout_no: '',
    product_name: '',
    customer: '',
    quantity: null,
    available: null,
    reason: '',
    note: '',
  }
}

function validateReturnForm(form: StockReturnFormData): string | null {
  if (!form.stockout_id) return '请先在出货明细中选择要退的记录'
  const qty = form.quantity
  if (qty == null || !Number.isInteger(qty) || qty <= 0) return '退货数量必须为正整数'
  if (form.available != null && qty > form.available) {
    return `退货数量超过可退数量（可退 ${form.available}）`
  }
  if (!form.reason) return '请选择退货原因'
  return null
}

/** 幂等令牌：每次打开弹窗重新生成；同一次弹窗内的网络重试视为同一请求 */
function newRequestId(): string {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
    return crypto.randomUUID()
  }
  return 'req-' + Date.now() + '-' + Math.random().toString(36).slice(2, 10)
}

export function useStockReturn() {
  const auth = useAuthStore()
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
    // 本 composable 也在库存出货列表实例化——无退货查看权限的访客不应发请求（403 审计噪音）
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

  // ---------- 新增退货：搜产品 -> 选出货明细 ----------
  const formOpen = ref(false)
  const form = reactive<StockReturnFormData>(emptyForm())
  const submitting = ref(false)
  /** P1-3 幂等令牌：打开弹窗时生成一次 */
  const requestId = ref('')

  const searchKeyword = ref('')
  const shipments = ref<ShipmentOption[]>([])
  const loadingShipments = ref(false)

  /** 按产品名搜可退出货明细（空关键词 = 最近可退明细） */
  async function searchShipments() {
    loadingShipments.value = true
    try {
      shipments.value = await stockReturnApi.shipmentOptions(searchKeyword.value.trim())
    } catch {
      showToast('出货明细搜索失败', 'warning')
    } finally {
      loadingShipments.value = false
    }
  }

  async function openStandalone() {
    Object.assign(form, emptyForm())
    requestId.value = newRequestId()
    searchKeyword.value = ''
    formOpen.value = true
    await searchShipments()
  }

  /** 勾选出货明细：客户/产品/可退量由明细带出，可退上限回填数量约束 */
  function pickShipment(row: ShipmentOption) {
    const switched = form.stockout_id !== row.stockout_id
    Object.assign(form, {
      stockout_id: row.stockout_id,
      stockout_no: row.stockout_no,
      product_name: row.product_name,
      customer: row.customer ?? '',
      available: row.available,
    })
    // 换行才清空数量：重复点同一行（固定录入条下很容易误点第二次）不该抹掉刚填的数字
    if (switched) form.quantity = null
  }

  const createMutation = useApiMutation(
    (payload: StockReturnCreatePayload) => stockReturnApi.create(payload),
    {
      invalidateKeys: ['stock-returns-list', 'stockouts-list', 'inventory'],
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
        stockout_id: form.stockout_id as number,
        quantity: form.quantity as number,
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

  // ---------- 取消退货（2026-10-09 起为硬删除：库存对称扣回，行本身移除） ----------
  const deleteMutation = useApiMutation((id: number) => stockReturnApi.remove(id), {
    invalidateKeys: ['stock-returns-list', 'stockouts-list', 'inventory'],
    successMsg: '退货取消成功',
    errorMsg: '退货取消失败',
  })

  async function handleDelete(row: { id: number; return_no: string; quantity: number }) {
    const ok = await confirmDialog.confirm(
      `确定要取消退货单 ${row.return_no}（${row.quantity} 件）吗？库存将对称扣回、订单状态重算，该退货单记录将被删除（对账以库存流水为准）。`,
    )
    if (!ok) return
    actionId.value = row.id
    await deleteMutation.run(row.id)
    actionId.value = 0
  }

  // ---------- 修改退货（后端单事务：取消原单 + 按同一出货明细重建，新单号） ----------
  // 与报表「退货流水」行内编辑同逻辑、同弹窗（EditReturnModal）。
  const returnEditVisible = ref(false)
  const returnEditForm = ref<ReturnEditForm | null>(null)

  const editMutation = useApiMutation(
    (vars: { id: number; payload: StockReturnUpdatePayload }) =>
      stockReturnApi.update(vars.id, vars.payload),
    {
      invalidateKeys: ['stock-returns-list', 'stockouts-list', 'inventory'],
      successMsg: '退货修改成功',
      errorMsg: '退货修改失败',
    },
  )

  function openReturnEdit(row: StockReturnRecord) {
    returnEditForm.value = {
      id: row.id,
      returnNo: row.return_no || '',
      productName: row.product?.name || '',
      quantity: row.quantity,
      customer: row.customer || '',
      date: (row.return_date || '').slice(0, 10),
      reason: row.reason || '',
      note: row.note || '',
    }
    returnEditVisible.value = true
  }

  async function saveReturnEdit() {
    const form = returnEditForm.value
    if (!form) return
    // 2026-10-17 审计 P2-47：与新建口径一致，必须为正整数（此前允许 1.5）
    if (!Number.isInteger(form.quantity) || form.quantity < 1) {
      showToast('退货数量必须为正整数', 'error')
      return
    }
    const saved = await editMutation.run({
      id: form.id,
      payload: {
        quantity: form.quantity,
        ...(form.date ? { return_date: form.date } : {}),
        reason: form.reason,
        note: form.note,
      },
    })
    // run() 失败返回 undefined（已弹错误 toast）——只有成功才关弹窗
    if (saved !== undefined) returnEditVisible.value = false
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
    searchKeyword,
    shipments,
    loadingShipments,
    openStandalone,
    searchShipments,
    pickShipment,
    handleSubmit,
    handleDelete,
    returnEditVisible,
    returnEditForm,
    savingReturn: editMutation.isSaving,
    openReturnEdit,
    saveReturnEdit,
  }
}
