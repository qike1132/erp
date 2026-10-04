import { ref, reactive } from 'vue'
import type { QueryClient } from '@tanstack/vue-query'
import { caseApi } from '@/api'
import type { CaseMovement } from '@/api/case'
import { showToast } from '@/composables/useToast'
import { useConfirmDialog } from '@/composables/useConfirmDialog'
import { useApiMutation } from '@/composables/useApiMutation'
import { CASE_QUERY_KEYS } from './useCaseStockWorkbench'

/** 编辑弹窗表单状态 */
export interface EditFormState {
  id: number
  no: string
  date: string
  productName: string
  quantity: number
  note: string
}

/**
 * 出入库流水的编辑与删除动作。
 * 复用工作台的 confirmDialog 实例（页面只渲染一个确认弹窗）；
 * 删除入库会同步扣减库存、删除出库会同步回补库存，确认文案需明示。
 */
export function useCaseRecordActions(
  confirmDialog: ReturnType<typeof useConfirmDialog>,
) {
  const invalidateAll = (client: QueryClient) => {
    for (const key of CASE_QUERY_KEYS) {
      client.invalidateQueries({ queryKey: [key] })
    }
  }

  // ===== 编辑 =====
  const editDialogOpen = ref(false)
  const editForm = reactive<EditFormState>({ id: 0, no: '', date: '', productName: '', quantity: 1, note: '' })

  async function openEdit(row: CaseMovement) {
    editForm.id = row.id
    editForm.no = row.movement_no || ''
    editForm.date = row.movement_date || ''
    editForm.productName = row.case_name || ''
    editForm.quantity = row.quantity || 1
    editForm.note = row.note || ''
    editDialogOpen.value = true
    // 用详情接口回填权威数据（列表可能截断备注等字段）
    try {
      const detail = (await caseApi.getMovement(row.id)) as CaseMovement
      if (!editDialogOpen.value || editForm.id !== row.id) return
      editForm.no = detail.movement_no || editForm.no
      editForm.date = detail.movement_date || ''
      editForm.productName = detail.case_name || editForm.productName
      editForm.quantity = detail.quantity || 1
      editForm.note = detail.note || ''
    } catch {
      /* 详情拉取失败时保留列表行数据 */
    }
  }

  const saveEditMutation = useApiMutation(
    (payload: { quantity: number; note: string; movement_date?: string }) =>
      caseApi.updateMovement(editForm.id, payload),
    {
      invalidate: invalidateAll,
      errorMsg: '更新失败',
      onSuccess: (res) => {
        showToast((res as { message?: string }).message || '更新成功', 'success')
        editDialogOpen.value = false
      },
    },
  )

  async function saveEdit() {
    if (saveEditMutation.isSaving.value) return
    const payload: { quantity: number; note: string; movement_date?: string } = {
      quantity: editForm.quantity,
      note: editForm.note,
    }
    // 第十四轮：日期被清空时不提交该字段 —— 后端对 '' 调 _parse_date 会 400「日期格式错误」，
    // 省略该键则后端保持原日期不变（update_movement 是部分更新）。
    if (editForm.date) payload.movement_date = editForm.date
    await saveEditMutation.run(payload)
  }

  // ===== 删除 =====
  const deletingId = ref<number>(0)

  const deleteMutation = useApiMutation(
    (id: number) => caseApi.deleteMovement(id),
    {
      invalidate: invalidateAll,
      successMsg: '删除成功',
      errorMsg: '删除失败',
    },
  )

  async function handleDelete(row: CaseMovement) {
    const isIn = row.direction === 'in'
    const effect = isIn
      ? `库存将同步扣减 ${row.quantity} 件`
      : `库存将同步回补 ${row.quantity} 件`
    const ok = await confirmDialog.confirm(
      `确定删除这条${isIn ? '入库' : '出库'}记录吗？`,
      effect,
      'danger',
    )
    if (!ok) return
    deletingId.value = row.id
    await deleteMutation.run(row.id)
    deletingId.value = 0
  }

  return {
    editDialogOpen,
    editForm,
    saving: saveEditMutation.isSaving,
    openEdit,
    saveEdit,
    deletingId,
    handleDelete,
  }
}
