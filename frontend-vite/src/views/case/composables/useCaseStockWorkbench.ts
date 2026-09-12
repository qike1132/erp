import { ref, reactive, computed } from 'vue'
import { useQueryClient } from '@tanstack/vue-query'
import { caseApi } from '@/api'
import type { CaseBatchStockItemPayload, CaseSearchItem } from '@/api/case'
import { showToast } from '@/composables/useToast'
import { useConfirmDialog } from '@/composables/useConfirmDialog'
import { getErrorMessage } from '@/types/errors'
import { toISODate } from '@/utils/format'

export type StockMode = 'stockin' | 'stockout'

/** 暂存单条目 */
export interface StagedStockItem {
  key: number
  productId: string
  productName: string
  barcode: string
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
  productId: string
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
 * 同一页面入库/出库各挂一个实例，互不干扰（替代旧版单实例 + 模式切换清空）。
 *
 * 并发口径：暂存时的库存校验基于「搜索结果带出的 current_stock − 本单内同产品已暂存数量」，
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
    productId: '',
    quantity: 1,
    note: '',
  })

  /** 选中产品的当前库存（出库用）；入库恒为 0 不展示 */
  const currentStock = ref<number | null>(null)

  /** 同一产品在暂存单中已占用的数量（出库本地校验口径） */
  const stagedQtyOf = (productId: string, exceptKey?: number) =>
    staged.value
      .filter((s) => s.productId === productId && s.key !== exceptKey)
      .reduce((sum, s) => sum + s.quantity, 0)

  const availableStock = computed(() =>
    mode === 'stockin' || currentStock.value === null
      ? null
      : currentStock.value - stagedQtyOf(form.productId),
  )

  /** 实时行内校验信息；空字符串表示通过 */
  const quantityWarning = computed(() => {
    if (mode === 'stockout' && availableStock.value !== null && form.quantity > availableStock.value) {
      return `库存不足：当前可用 ${availableStock.value}${stagedQtyOf(form.productId) ? `（已暂存 ${stagedQtyOf(form.productId)}）` : ''}`
    }
    return ''
  })

  const canAdd = computed(() => {
    if (!form.productId || !form.customer || !form.date) return false
    if (!Number.isInteger(form.quantity) || form.quantity < 1) return false
    return quantityWarning.value === ''
  })

  function onProductSelect(product: CaseSearchItem) {
    form.productId = String(product.id)
    form.search = product.name
    // 出库时以搜索结果带出的库存为基准，并扣除本单内该产品已暂存数量
    currentStock.value = mode === 'stockout' ? (product.current_stock ?? 0) : null
    form.quantity = 1
  }

  // ===== 暂存单 =====
  const staged = ref<StagedStockItem[]>([])
  let stagedSeq = 0

  const stagedTotal = computed(() =>
    staged.value.reduce((sum, s) => sum + s.quantity, 0),
  )

  function addStaged() {
    if (!canAdd.value) {
      showToast(quantityWarning.value || '请完整填写客户、产品与数量', 'warning')
      return
    }
    staged.value.push({
      key: ++stagedSeq,
      productId: form.productId,
      productName: form.search,
      barcode: '',
      customer: form.customer,
      date: form.date,
      quantity: form.quantity,
      note: form.note.trim(),
    })
    // 保留客户/日期/备注便于连续录入同一客户，仅清空产品与数量
    form.search = ''
    form.productId = ''
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
  /** 最近一次部分失败的明细（暂存单保留失败项） */
  const lastFailures = ref<SubmitFailure[]>([])

  /** 清空产品选择与基准库存：提交成功后避免基于旧库存继续录入 */
  function resetSelection() {
    form.search = ''
    form.productId = ''
    form.quantity = 1
    currentStock.value = null
  }

  async function submitBatch() {
    if (!staged.value.length) return
    submitting.value = true
    lastFailures.value = []
    const items: CaseBatchStockItemPayload[] = staged.value.map((s) => ({
      productId: s.productId,
      customer: s.customer,
      quantity: s.quantity,
      ...(mode === 'stockin' ? { stockinDate: s.date } : { stockoutDate: s.date }),
      note: s.note,
    }))
    try {
      if (mode === 'stockin') {
        const res = await caseApi.batchStockin(items)
        const failed = res.failed ?? []
        if (failed.length) {
          const failedIdx = new Set(failed.map((f) => f.index))
          lastFailures.value = failed
            .map((f) => ({ index: f.index, productName: staged.value[f.index]?.productName ?? `#${f.index + 1}`, error: f.error }))
          staged.value = staged.value.filter((_, i) => failedIdx.has(i))
          showToast(`入库部分失败：成功 ${items.length - failed.length} 条，失败 ${failed.length} 条`, 'error')
        } else {
          staged.value = []
          resetSelection()
          showToast(`入库成功，共 ${items.length} 条`, 'success')
        }
      } else {
        const res = await caseApi.batchStockout(items)
        const failed = (res.results ?? [])
          .map((r, i) => ({ index: i, ok: r.success, error: r.error ?? '出库失败' }))
          .filter((r) => !r.ok)
        if (failed.length) {
          const failedIdx = new Set(failed.map((f) => f.index))
          lastFailures.value = failed
            .map((f) => ({ index: f.index, productName: staged.value[f.index]?.productName ?? `#${f.index + 1}`, error: f.error }))
          staged.value = staged.value.filter((_, i) => failedIdx.has(i))
          showToast(`出库部分失败：成功 ${items.length - failed.length} 条，失败 ${failed.length} 条`, 'error')
        } else {
          staged.value = []
          resetSelection()
          showToast(`出库成功，共 ${items.length} 条`, 'success')
        }
      }
    } catch (err: unknown) {
      showToast(getErrorMessage(err, mode === 'stockin' ? '入库提交失败' : '出库提交失败'), 'error')
    } finally {
      submitting.value = false
      // 提交影响库存汇总、记录列表与流水，全部失效由 vue-query 重新拉取
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
export const CASE_QUERY_KEYS = ['case-stockins', 'case-stockouts', 'case-inventory', 'case-inventory-logs'] as const

export function caseQueryKeys() {
  return CASE_QUERY_KEYS
}
