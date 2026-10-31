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
  /** 服务端回传的请求内下标（仅用于文案追溯，**不要**用它回写暂存单） */
  index: number
  /** 暂存行的稳定 id（2026-10-30 审计 A-M38）：失败行靠它对回原行 */
  key: number
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
    // 提交在途：此时改清单会让「按请求快照对回失败行」失去依据（A-M38）
    if (submitting.value) return
    const ok = await confirmDialog.confirm('移除该条暂存记录？', '仅从暂存单移除，不影响已提交数据')
    if (!ok) return
    staged.value = staged.value.filter((s) => s.key !== key)
  }

  /** 行内直接改数量；越界时回退为 1 并提示 */
  function updateStagedQuantity(key: number, quantity: number) {
    if (submitting.value) return
    const item = staged.value.find((s) => s.key === key)
    if (!item) return
    if (!Number.isInteger(quantity) || quantity < 1) {
      showToast('数量必须为不小于 1 的整数', 'warning')
      item.quantity = 1
      return
    }
    item.quantity = quantity
  }

  /** 暂存行行内编辑方向（点击徽标切换） */
  function updateStagedDirection(key: number, direction: Direction) {
    if (submitting.value) return
    const item = staged.value.find((s) => s.key === key)
    if (item) item.direction = direction
  }

  /** 暂存行行内编辑日期。清空时**回填今天**而不是静默忽略 ——
   *  忽略会让输入框看起来已清空（Vue 只在 vnode 值变化时写 DOM，新旧都是旧日期
   *  → 不回写），用户以为走了「今天」，实际提交的还是旧日期（台账日期错记）。 */
  function updateStagedDate(key: number, date: string) {
    if (submitting.value) return
    const item = staged.value.find((s) => s.key === key)
    if (item) item.date = date || toISODate()
  }

  /** 暂存行行内编辑备注 */
  function updateStagedNote(key: number, note: string) {
    if (submitting.value) return
    const item = staged.value.find((s) => s.key === key)
    if (item) item.note = note
  }

  function clearStaged() {
    if (submitting.value) return
    staged.value = []
  }

  const submitting = ref(false)
  const lastFailures = ref<SubmitFailure[]>([])

  async function submitBatch() {
    if (!staged.value.length) return
    submitting.value = true
    lastFailures.value = []
    /**
     * 提交快照（A-M38）：请求发出后清单仍可能被改动（清空/删除/改数量），
     * 之前用「失败下标 → staged[i]」对回，一旦有行被移除就会错位——把成功行
     * 留在清单里、把失败行悄悄丢掉（用户以为提交成功，实际台账缺记录）。
     * 这里固定快照的 key 与 payload，失败一律按 key 对回。
     */
    const snapshot = staged.value.map((s) => ({
      key: s.key,
      caseName: s.caseName,
      payload: {
        case_id: Number(s.caseId),
        direction: s.direction,
        quantity: s.quantity,
        movement_date: s.date,
        note: s.note,
      } satisfies CaseMovementPayload,
    }))
    const items: CaseMovementPayload[] = snapshot.map((s) => s.payload)
    const keyByIndex = snapshot.map((s) => s.key)
    const nameByKey = new Map(snapshot.map((s) => [s.key, s.caseName]))
    try {
      const res = await caseApi.batchMovements(items)
      const failed = res.failed ?? []
      if (failed.length) {
        const failedKeys = new Set<number>()
        lastFailures.value = failed.map((f) => {
          const key = keyByIndex[f.index]
          if (key !== undefined) failedKeys.add(key)
          return {
            index: f.index,
            key: key ?? -1,
            productName: (key !== undefined ? nameByKey.get(key) : undefined) ?? `#${f.index + 1}`,
            error: f.error,
          }
        })
        // 只保留失败行（按稳定 id），与请求顺序、清单当前顺序都无关
        staged.value = staged.value.filter((s) => failedKeys.has(s.key))
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

  /**
   * 单条直提（不经暂存单）：一条走 `POST /cases/movements`，多条（勾了配件）走批量端点。
   * 方向/日期/备注取自表单当前值。
   */
  async function submitDirect(rows: StagedRowInput[]) {
    // 重入守卫：提交按钮的 :disabled 只挡点击，**挡不住 Enter**（StockEntryCard 的
    // @keydown.enter 直接调 onSubmit）。无守卫时「A 在飞 + 选好 B 按 Enter」会并发发出
    // 第二个 createMovement，且先返回者会把 submitting 置 false 让按钮提前解锁。
    if (submitting.value) return
    const valid = rows.filter((r) => r.caseId && Number.isInteger(r.quantity) && r.quantity >= 1)
    const first = valid[0]
    if (!first) {
      showToast('请先选择要录入的皮套并填写数量', 'warning')
      return
    }
    submitting.value = true
    lastFailures.value = []
    const label = form.direction === 'in' ? '入库' : '出库'
    try {
      if (valid.length === 1) {
        const res = await caseApi.createMovement({
          case_id: Number(first.caseId),
          direction: form.direction,
          quantity: first.quantity,
          movement_date: form.date,
          note: form.note.trim(),
        })
        if (res.success === false) {
          showToast(`${label}失败`, 'error')
          return
        }
        showToast(`${label}成功：${first.caseName} × ${first.quantity}`, 'success')
      } else {
        const res = await caseApi.batchMovements(
          valid.map((r) => ({
            case_id: Number(r.caseId),
            direction: form.direction,
            quantity: r.quantity,
            movement_date: form.date,
            note: form.note.trim(),
          })),
        )
        const failed = res.failed ?? []
        if (failed.length) {
          showToast(`部分失败：成功 ${valid.length - failed.length} 条，失败 ${failed.length} 条`, 'error')
        } else {
          showToast(`${label}成功，共 ${valid.length} 条`, 'success')
        }
      }
    } catch (err: unknown) {
      showToast(getErrorMessage(err, `${label}失败`), 'error')
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
    updateStagedDirection,
    updateStagedDate,
    updateStagedNote,
    clearStaged,
    submitting,
    submitBatch,
    submitDirect,
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

/** 皮套模块全部查询键（提交/导入/WS 刷新统一失效入口）。
 *  ⚠️ 必须与各处 useQuery 的**首元素**逐一对应：vue-query 的部分匹配要求首元素相等，
 *  `['case-movements']` 匹配不到 `['case-movements-drawer', ...]` —— 漏掉会让抽屉
 *  在别处提交后仍显示过期流水。（原先的 `'case-items'` 全仓无对应查询，已移除。） */
export const CASE_QUERY_KEYS = ['case-inventory', 'case-movements', 'case-movements-drawer'] as const

export function caseQueryKeys() {
  return CASE_QUERY_KEYS
}
