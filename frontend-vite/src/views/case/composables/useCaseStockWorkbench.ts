import { ref, reactive, computed } from 'vue'
import { useQueryClient } from '@tanstack/vue-query'
import { caseApi } from '@/api'
import type { CaseMovementPayload, CaseSearchItem } from '@/api/case'
import { showToast } from '@/composables/useToast'
import { useConfirmDialog } from '@/composables/useConfirmDialog'
import { getErrorMessage } from '@/types/errors'
import { toISODate } from '@/utils/format'

export type StockMode = 'stockin' | 'stockout'

/** 模式 → 后端方向标记 */
export function directionOf(mode: StockMode): 'in' | 'out' {
  return mode === 'stockin' ? 'in' : 'out'
}

/** 暂存单条目 */
export interface StagedStockItem {
  key: number
  caseId: string
  caseName: string
  customer: string
  date: string
  quantity: number
  note: string
}

/** 录入表单状态 */
export interface CaseStockFormState {
  customer: string
  date: string
  search: string
  caseId: string
  quantity: number
  note: string
}

/** 批量提交结果（含部分失败明细） */
export interface SubmitFailure {
  index: number
  productName: string
  error: string
}

/**
 * 皮套入库/出库工作台状态：录入表单、暂存单、批量提交与 Excel 导入。
 * 同一页面入库/出库各挂一个实例，互不干扰。
 *
 * 并发口径：暂存时的库存校验基于「搜索结果带出的 current_stock − 本单内同 SKU 已暂存数量」，
 * 后端行级锁校验兜底，本地只做前置提示。
 */
export function useCaseStockWorkbench(mode: StockMode) {
  const queryClient = useQueryClient()
  const confirmDialog = useConfirmDialog()

  // ===== 录入表单 =====
  const today = toISODate()
  const form = reactive<CaseStockFormState>({
    customer: '',
    date: today,
    search: '',
    caseId: '',
    quantity: 1,
    note: '',
  })

  /** 选中 SKU 的当前库存（出库用）；入库恒为 null 不展示 */
  const currentStock = ref<number | null>(null)

  const stagedQtyOf = (caseId: string, exceptKey?: number) =>
    staged.value
      .filter((s) => s.caseId === caseId && s.key !== exceptKey)
      .reduce((sum, s) => sum + s.quantity, 0)

  const availableStock = computed(() =>
    mode === 'stockin' || currentStock.value === null
      ? null
      : currentStock.value - stagedQtyOf(form.caseId),
  )

  /** 实时行内校验信息；空字符串表示通过 */
  const quantityWarning = computed(() => {
    if (mode === 'stockout' && availableStock.value !== null && form.quantity > availableStock.value) {
      return `库存不足：当前可用 ${availableStock.value}${stagedQtyOf(form.caseId) ? `（已暂存 ${stagedQtyOf(form.caseId)}）` : ''}`
    }
    return ''
  })

  const canAdd = computed(() => {
    if (!form.caseId || !form.date) return false
    if (!Number.isInteger(form.quantity) || form.quantity < 1) return false
    return quantityWarning.value === ''
  })

  function onProductSelect(item: CaseSearchItem) {
    form.caseId = String(item.id)
    form.search = item.name
    currentStock.value = mode === 'stockout' ? (item.current_stock ?? 0) : null
    form.quantity = 1
  }

  // ===== 暂存单 =====
  const staged = ref<StagedStockItem[]>([])
  let stagedSeq = 0

  const stagedTotal = computed(() => staged.value.reduce((sum, s) => sum + s.quantity, 0))

  function addStaged() {
    if (!canAdd.value) {
      showToast(quantityWarning.value || '请完整填写产品与数量', 'warning')
      return
    }
    staged.value.push({
      key: ++stagedSeq,
      caseId: form.caseId,
      caseName: form.search,
      customer: form.customer,
      date: form.date,
      quantity: form.quantity,
      note: form.note.trim(),
    })
    // 保留客户/日期/备注便于连续录入，仅清空产品与数量
    form.search = ''
    form.caseId = ''
    form.quantity = 1
  }

  async function removeStaged(key: number) {
    const ok = await confirmDialog.confirm('移除该条暂存记录？', '仅从暂存单移除，不影响已提交数据')
    if (!ok) return
    staged.value = staged.value.filter((s) => s.key !== key)
  }

  /** 行内直接改数量；越界时回退为 1 并提示 */
  function updateStagedQuantity(key: number, quantity: number) {
    const item = staged.value.find((s) => s.key === key)
    if (!item) return
    if (!Number.isInteger(quantity) || quantity < 1) {
      showToast('数量必须为不小于 1 的整数', 'warning')
      item.quantity = 1
      return
    }
    item.quantity = quantity
  }

  function clearStaged() {
    staged.value = []
  }

  // ===== 批量提交 =====
  const submitting = ref(false)
  const lastFailures = ref<SubmitFailure[]>([])

  function resetSelection() {
    form.search = ''
    form.caseId = ''
    form.quantity = 1
    currentStock.value = null
  }

  async function submitBatch() {
    if (!staged.value.length) return
    submitting.value = true
    lastFailures.value = []
    const direction = directionOf(mode)
    const items: CaseMovementPayload[] = staged.value.map((s) => ({
      case_id: Number(s.caseId),
      direction,
      quantity: s.quantity,
      movement_date: s.date,
      customer: s.customer,
      note: s.note,
    }))
    try {
      const res = await caseApi.batchMovements(items)
      const failed = res.failed ?? []
      if (failed.length) {
        const failedIdx = new Set(failed.map((f) => f.index))
        lastFailures.value = failed.map((f) => ({
          index: f.index,
          productName: staged.value[f.index]?.caseName ?? `#${f.index + 1}`,
          error: f.error,
        }))
        staged.value = staged.value.filter((_, i) => failedIdx.has(i))
        showToast(`${mode === 'stockin' ? '入库' : '出库'}部分失败：成功 ${items.length - failed.length} 条，失败 ${failed.length} 条`, 'error')
      } else {
        staged.value = []
        resetSelection()
        showToast(`${mode === 'stockin' ? '入库' : '出库'}成功，共 ${items.length} 条`, 'success')
      }
    } catch (err: unknown) {
      showToast(getErrorMessage(err, mode === 'stockin' ? '入库提交失败' : '出库提交失败'), 'error')
    } finally {
      submitting.value = false
      for (const key of CASE_QUERY_KEYS) {
        queryClient.invalidateQueries({ queryKey: [key] })
      }
    }
  }

  // ===== Excel 批量导入 =====
  const showBatchUpload = ref(false)
  const excelFile = ref<File | null>(null)
  const importing = ref(false)
  const templateDownloading = ref(false)

  function onExcelFileChange(files: FileList) {
    const file = files[0]
    if (!file) return
    if (!(file.name.endsWith('.xlsx') || file.name.endsWith('.xls'))) {
      showToast('请上传 Excel 文件（.xlsx 或 .xls）', 'error')
      return
    }
    if (file.size > 10 * 1024 * 1024) {
      showToast(`文件大小不能超过 10MB，当前文件 ${(file.size / 1024 / 1024).toFixed(1)}MB`, 'error')
      return
    }
    excelFile.value = file
  }

  async function downloadTemplate() {
    templateDownloading.value = true
    try {
      await caseApi.downloadTemplate(mode === 'stockin' ? '皮套入库模板.xlsx' : '皮套出库模板.xlsx')
    } catch {
      showToast('模板下载失败', 'error')
    } finally {
      templateDownloading.value = false
    }
  }

  async function importExcel() {
    if (!excelFile.value || importing.value) return
    importing.value = true
    try {
      const formData = new FormData()
      formData.append('file', excelFile.value)
      const res = await (mode === 'stockin' ? caseApi.importStockins(formData) : caseApi.importStockouts(formData))
      if (res.success) {
        showToast(`成功导入 ${res.imported ?? 0} 条记录`, 'success')
        excelFile.value = null
        for (const key of CASE_QUERY_KEYS) {
          queryClient.invalidateQueries({ queryKey: [key] })
        }
      } else {
        showToast(res.message || '导入失败', 'error')
      }
    } catch (err: unknown) {
      showToast(getErrorMessage(err, '导入失败'), 'error')
    } finally {
      importing.value = false
    }
  }

  return {
    mode,
    form,
    currentStock,
    availableStock,
    quantityWarning,
    canAdd,
    onProductSelect,
    staged,
    stagedTotal,
    addStaged,
    removeStaged,
    updateStagedQuantity,
    clearStaged,
    submitting,
    submitBatch,
    lastFailures,
    showBatchUpload,
    excelFile,
    importing,
    templateDownloading,
    onExcelFileChange,
    downloadTemplate,
    importExcel,
    confirmDialog,
  }
}

/** 皮套模块全部查询键（提交/导入/WS 刷新统一失效入口） */
export const CASE_QUERY_KEYS = ['case-inventory', 'case-movements', 'case-items'] as const

export function caseQueryKeys() {
  return CASE_QUERY_KEYS
}
