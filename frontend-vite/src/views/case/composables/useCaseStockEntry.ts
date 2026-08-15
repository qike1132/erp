import { ref, reactive, computed } from 'vue'
import { useQuery } from '@tanstack/vue-query'
import { caseApi, customerApi } from '@/api'
import { showToast } from '@/composables/useToast'
import { toISODate } from '@/utils/format'

type StockMode = 'stockin' | 'stockout'

/** 产品搜索候选项（来自 /cases/search） */
export interface CaseProductOption {
  id: number | string
  name: string
  barcode?: string
  current_stock?: number
}

/** 暂存列表项（入库/出库待提交） */
export interface StagedStockItem {
  id: number
  productId: string
  productName: string
  customer: string
  date: string
  quantity: number
  note: string
}

/** 客户下拉选项 */
export interface CustomerOption {
  value: string
  label: string
}

/** 录入表单状态 */
export interface CaseStockFormState {
  customer: string
  date: string
  search: string
  productId: string
  quantity: number
  note: string
}

/**
 * 皮套入库/出库「信息录入」区状态：
 * 模式切换、客户列表、产品搜索、录入表单与暂存列表。
 * （批量提交/导入/编辑等动作见 useCaseStockActions）
 */
export function useCaseStockEntry() {
  // === 模式 ===
  const mode = ref<StockMode>('stockin')

  // === 客户列表 ===
  const { data: customersData } = useQuery({
    queryKey: ['case-customer-names'],
    queryFn: async () => {
      const res = (await customerApi.activeNames()) as unknown as { names?: string[] } & string[]
      return res.names ?? res ?? []
    },
    staleTime: 30_000,
  })
  const customers = computed(() => (Array.isArray(customersData.value) ? customersData.value : []))
  const customerOptions = computed<CustomerOption[]>(() =>
    customers.value.map((c: string) => ({ value: c, label: c })),
  )

  // === 产品搜索 ===
  async function searchCaseProducts(query: string): Promise<CaseProductOption[]> {
    if (!query.trim()) return []
    try {
      const data = await caseApi.search(query)
      return Array.isArray(data) ? (data as CaseProductOption[]) : []
    } catch {
      return []
    }
  }

  const currentStock = ref(0)

  function onProductSelect(product: CaseProductOption) {
    form.productId = String(product.id)
    form.search = product.name
    if (mode.value === 'stockout') currentStock.value = product.current_stock ?? 0
  }

  // === 表单 ===
  const today = toISODate()
  const form = reactive<CaseStockFormState>({ customer: '', date: today, search: '', productId: '', quantity: 1, note: '' })

  const canAdd = computed(() => {
    if (!form.productId || form.quantity < 1 || !form.date) return false
    if (mode.value === 'stockin' && !form.customer) return false
    if (mode.value === 'stockout' && form.quantity > currentStock.value) return false
    return true
  })

  // === 暂存列表 ===
  const staged = ref<StagedStockItem[]>([])

  /** 切换入库/出库模式：重置表单、暂存列表与当前库存 */
  function switchEntryMode(nextMode: StockMode) {
    mode.value = nextMode
    form.customer = ''
    form.date = today
    form.search = ''
    form.productId = ''
    form.quantity = 1
    form.note = ''
    currentStock.value = 0
    staged.value = []
  }

  function addStaged() {
    if (!canAdd.value) {
      if (mode.value === 'stockout' && form.quantity > currentStock.value) {
        showToast(`库存不足，当前库存: ${currentStock.value}`, 'warning')
      } else {
        showToast('请选择产品并输入数量', 'warning')
      }
      return
    }
    staged.value.push({
      id: Date.now(),
      productId: form.productId,
      productName: form.search,
      customer: form.customer,
      date: form.date,
      quantity: form.quantity,
      note: form.note,
    })
    if (mode.value === 'stockout') currentStock.value -= form.quantity
    form.search = ''
    form.productId = ''
    form.quantity = 1
    form.note = ''
  }

  return {
    mode,
    switchEntryMode,
    customerOptions,
    searchCaseProducts,
    currentStock,
    onProductSelect,
    form,
    canAdd,
    staged,
    addStaged,
  }
}
