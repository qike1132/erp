import { ref, reactive, computed } from 'vue'
import { useQueryClient } from '@tanstack/vue-query'
import { caseApi } from '@/api'
import type { CaseMovementPayload } from '@/api/case'
import { showToast } from '@/composables/useToast'
import { useConfirmDialog } from '@/composables/useConfirmDialog'
import { getErrorMessage } from '@/types/errors'
import { toISODate } from '@/utils/format'

export type Direction = 'in' | 'out'

/** 暂存单条目（自带方向与主件/配件标记） */
export interface StagedStockItem {
  key: number
  caseId: string
  caseName: string
  isPart: boolean
  direction: Direction
  date: string
  quantity: number
  note: string
}

/** 表单状态：方向 / 日期 / 备注（产品与数量由录入卡逐行持有） */
export interface CaseStockFormState {
  direction: Direction
  date: string
  note: string
}

/** 一次加入暂存单的一行 */
export interface StagedRowInput {
  caseId: string
  caseName: string
  isPart: boolean
  quantity: number
}

/** 批量提交结果（含部分失败明细） */
export interface SubmitFailure {
  index: number
  productName: string
  error: string
}

/**
 * 皮套出入库工作台（入库/出库合一）：暂存单、批量提交与 Excel 导入。
 * 方向/日期/备注在表头统一选择；产品与其主件/配件清单由录入卡展开并逐行填数量，
 * 一次性把勾选的行加入暂存单。
 */
export function useCaseStockWorkbench() {
  const queryClient = useQueryClient()
  const confirmDialog = useConfirmDialog()

  const form = reactive<CaseStockFormState>({
    direction: 'in',
    date: toISODate(),
    note: '',
  })

  const staged = ref<StagedStockItem[]>([])
  let stagedSeq = 0

  const stagedTotal = computed(() => staged.value.reduce((sum, s) => sum + s.quantity, 0))

  /** 把录入卡勾选的行（同方向/日期/备注）一次性加入暂存单 */
  function addStagedBatch(rows: StagedRowInput[]) {
    const valid = rows.filter((r) => r.caseId && Number.isInteger(r.quantity) && r.quantity >= 1)
    if (!valid.length) {
      showToast('请至少勾选一项并填写数量', 'warning')
      return
    }
    for (const r of valid) {
      staged.value.push({
        key: ++stagedSeq,
        caseId: r.caseId,
        caseName: r.caseName,
        isPart: r.isPart,
        direction: form.direction,
        date: form.date,
        quantity: r.quantity,
        note: form.note.trim(),
      })
    }
    showToast(`已加入 ${valid.length} 条到暂存单`, 'success')
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

  const submitting = ref(false)
  const lastFailures = ref<SubmitFailure[]>([])

  async function submitBatch() {
    if (!staged.value.length) return
    submitting.value = true
    lastFailures.value = []
    const items: CaseMovementPayload[] = staged.value.map((s) => ({
      case_id: Number(s.caseId),
      direction: s.direction,
      quantity: s.quantity,
      movement_date: s.date,
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
        showToast(`部分失败：成功 ${items.length - failed.length} 条，失败 ${failed.length} 条`, 'error')
      } else {
        staged.value = []
        showToast(`提交成功，共 ${items.length} 条`, 'success')
      }
    } catch (err: unknown) {
      showToast(getErrorMessage(err, '提交失败'), 'error')
    } finally {
      submitting.value = false
      for (const key of CASE_QUERY_KEYS) {
        queryClient.invalidateQueries({ queryKey: [key] })
      }
    }
  }

  // ===== Excel 批量导入（按表单当前方向） =====
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
      await caseApi.downloadTemplate(form.direction === 'in' ? '皮套入库模板.xlsx' : '皮套出库模板.xlsx')
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
      const res = await (form.direction === 'in' ? caseApi.importStockins(formData) : caseApi.importStockouts(formData))
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
    form,
    staged,
    stagedTotal,
    addStagedBatch,
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
