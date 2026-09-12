import { ref, reactive } from 'vue'
import type { Ref } from 'vue'
import { useQueryClient } from '@tanstack/vue-query'
import { caseApi } from '@/api'
import type { CaseStockRecord } from '@/api/case'
import { showToast } from '@/composables/useToast'
import { useConfirmDialog } from '@/composables/useConfirmDialog'
import { getErrorMessage } from '@/types/errors'
import { CASE_QUERY_KEYS } from './useCaseStockWorkbench'

export type StockMode = 'stockin' | 'stockout'

/** 编辑弹窗表单状态 */
export interface EditFormState {
  id: number
  no: string
  customer: string
  date: string
  productName: string
  quantity: number
  note: string
}

/** 记录详情响应（入库/出库通用字段别名） */
interface RecordDetail {
  id: number
  stockin_no?: string
  stockout_no?: string
  stockin_date?: string
  stockout_date?: string
  customer?: string
  case_name?: string
  quantity: number
  note?: string
}

/**
 * 入库/出库记录的编辑与删除动作。
 * 复用工作台的 confirmDialog 实例（页面只渲染一个确认弹窗）；
 * 删除入库会同步扣减库存、删除出库会同步回补库存，确认文案需明示。
 */
export function useCaseRecordActions(
  mode: Ref<StockMode>,
  confirmDialog: ReturnType<typeof useConfirmDialog>,
) {
  const queryClient = useQueryClient()

  const invalidateAll = () => {
    for (const key of CASE_QUERY_KEYS) {
      queryClient.invalidateQueries({ queryKey: [key] })
    }
  }

  // ===== 编辑 =====
  const editDialogOpen = ref(false)
  const saving = ref(false)
  const editForm = reactive<EditFormState>({ id: 0, no: '', customer: '', date: '', productName: '', quantity: 1, note: '' })

  async function openEdit(row: CaseStockRecord) {
    editForm.id = row.id
    editForm.no = (mode.value === 'stockin' ? row.stockin_no : row.stockout_no) || ''
    editForm.customer = row.customer || ''
    editForm.date = (mode.value === 'stockin' ? row.stockin_date : row.stockout_date) || ''
    editForm.productName = row.case_name || ''
    editForm.quantity = row.quantity || 1
    editForm.note = row.note || ''
    editDialogOpen.value = true
    // 用详情接口回填权威数据（列表接口可能截断备注等字段）
    try {
      const detail = await (mode.value === 'stockin' ? caseApi.getStockin(row.id) : caseApi.getStockout(row.id)) as RecordDetail
      if (!editDialogOpen.value || editForm.id !== row.id) return
      editForm.no = (mode.value === 'stockin' ? detail.stockin_no : detail.stockout_no) || editForm.no
      editForm.customer = detail.customer || ''
      editForm.date = (mode.value === 'stockin' ? detail.stockin_date : detail.stockout_date) || ''
      editForm.productName = detail.case_name || editForm.productName
      editForm.quantity = detail.quantity || 1
      editForm.note = detail.note || ''
    } catch {
      /* 详情拉取失败时保留列表行数据 */
    }
  }

  async function saveEdit() {
    if (saving.value) return
    saving.value = true
    try {
      const payload = {
        customer: editForm.customer,
        quantity: editForm.quantity,
        note: editForm.note,
        ...(mode.value === 'stockin' ? { stockin_date: editForm.date } : { stockout_date: editForm.date }),
      }
      const res = await (mode.value === 'stockin'
        ? caseApi.updateStockin(editForm.id, payload)
        : caseApi.updateStockout(editForm.id, payload))
      showToast(res.message || '更新成功', 'success')
      editDialogOpen.value = false
      invalidateAll()
    } catch (err: unknown) {
      showToast(getErrorMessage(err, '更新失败'), 'error')
    } finally {
      saving.value = false
    }
  }

  // ===== 删除 =====
  const deletingId = ref<number | 0>(0)

  async function handleDelete(row: CaseStockRecord) {
    const effect = mode.value === 'stockin'
      ? `库存将同步扣减 ${row.quantity} 件`
      : `库存将同步回补 ${row.quantity} 件`
    const ok = await confirmDialog.confirm(
      `确定删除这条${mode.value === 'stockin' ? '入库' : '出库'}记录吗？`,
      effect,
      'danger',
    )
    if (!ok) return
    deletingId.value = row.id
    try {
      await (mode.value === 'stockin' ? caseApi.deleteStockin(row.id) : caseApi.deleteStockout(row.id))
      showToast('删除成功', 'success')
      invalidateAll()
    } catch (err: unknown) {
      showToast(getErrorMessage(err, '删除失败'), 'error')
    } finally {
      deletingId.value = 0
    }
  }

  return {
    editDialogOpen,
    editForm,
    saving,
    openEdit,
    saveEdit,
    deletingId,
    handleDelete,
  }
}
