/**
 * useReportRowActions — 报表页行内编辑/删除的动作编排
 *
 * 报表行是聚合行（同日+客户+产品+状态一组，group 内多张单/多条备货由后端
 * `order_nos` / `stockin_nos`（`, ` 连接）下发）。点编辑/删除时先「还原」：
 * 用 orderApi.records 的结构化筛选（customer+start_date+end_date+record_type 单请求
 * + 组内单号精确回比，缺失单号逐个补查）把聚合行还原成具体记录，再走迁入的
 * useOrderDetailEdit / useOrderDelete / useStockinEdit 单条流程——零复制粘贴。
 *
 * 已知口径差异（后端既有，纯前端不可修）：/orders/records 对绑定工厂的非超管
 * 强制按本厂过滤，而 /reports/*-logs 不做工厂隔离——工厂绑定用户看到他厂行时
 * 点还原会查不到单，落入「未能找到该组对应的明细记录」toast。
 */
import { ref, computed } from 'vue'
import { useQueryClient } from '@tanstack/vue-query'
import { orderApi } from '@/api'
import { useAuthStore } from '@/stores/auth'
import type { UnifiedRecord, OrderRecordsQuery } from '@/api/order'
import { showToast } from '@/composables/useToast'
import { useConfirmDialog } from '@/composables/useConfirmDialog'
import { getErrorMessage } from '@/types/errors'
import { getStatusClass, useOrderDetailEdit } from './useOrderDetailEdit'
import { useOrderDelete } from './useOrderDelete'
import { useStockinEdit } from './useStockinEdit'
import type { OrderRecord } from './orderRecordTypes'

/** 报表行上承载组内单号的字段（后端 _string_agg(..., ', ')，report_service.py） */
export type ReportActionTab = 'order' | 'stockin'
export type ReportAction = 'edit' | 'delete'

/** 逗号切分 → trim → 去空（后端以 ', ' 连接聚合单号） */
export function parseGroupNos(raw: string): string[] {
  return raw
    .split(',')
    .map((s) => s.trim())
    .filter((s) => s.length > 0)
}

/** 按组内单号精确匹配还原结果；返回命中行与缺失单号清单（供补查与测试） */
export function matchRecordsByNos(
  rows: UnifiedRecord[],
  nos: string[],
): { matched: UnifiedRecord[]; missing: string[] } {
  const byNo = new Map<string, UnifiedRecord>()
  for (const r of rows) {
    if (!byNo.has(r.order_no)) byNo.set(r.order_no, r)
  }
  const matched: UnifiedRecord[] = []
  const missing: string[] = []
  for (const no of nos) {
    const hit = byNo.get(no)
    if (hit) matched.push(hit)
    else missing.push(no)
  }
  return { matched, missing }
}

export function useReportRowActions() {
  const queryClient = useQueryClient()
  const authStore = useAuthStore()

  /** 写入成功后的刷新：前缀失效当前报表查询（queryKey 以 'report-data' 开头） */
  const refreshAfterWrite = () => queryClient.invalidateQueries({ queryKey: ['report-data'] })

  const detailEdit = useOrderDetailEdit(refreshAfterWrite)
  const confirmDialog = useConfirmDialog()
  const orderDelete = useOrderDelete(refreshAfterWrite, confirmDialog)
  const stockinEdit = useStockinEdit(refreshAfterWrite, confirmDialog)

  /** 多条选择弹窗状态 */
  const pickerOpen = ref(false)
  const pickerRecords = ref<UnifiedRecord[]>([])
  const pickerAction = ref<ReportAction>('edit')
  /** 还原查询进行中：防重入 */
  const resolving = ref(false)

  /** 组内待还原的上下文（resolveRecords 与补查共享） */
  async function resolveRecords(row: Record<string, unknown>, recordType: 'order' | 'stockin'): Promise<UnifiedRecord[]> {
    const rawNos = String(row.order_nos ?? row.stockin_nos ?? '')
    const groupDate = String((recordType === 'order' ? row.order_date : row.stockin_date) ?? '')
    const nos = parseGroupNos(rawNos)
    // 守卫只挡单号或日期为空；customer 为空不拦（备货流水按 COALESCE(s.customer,'') 分组，可为 NULL）
    if (nos.length === 0 || !groupDate) {
      showToast('未能找到该组对应的明细记录', 'error')
      return []
    }
    const customer = String(row.customer ?? '')
    const baseQuery: OrderRecordsQuery = {
      page: 1,
      per_page: 500,
      record_type: recordType,
      start_date: groupDate,
      end_date: groupDate,
      ...(customer ? { customer } : {}),
    }
    const res = await orderApi.records(baseQuery)
    const rows = res.data ?? []
    const { matched, missing } = matchRecordsByNos(rows, nos)
    if (matched.length === nos.length) return matched

    // 主查询漏单（分页截断、客户串差异等）：对缺失单号逐个补查
    for (const no of missing) {
      const fallback = await orderApi.records({ page: 1, per_page: 500, record_type: recordType, order_no: no })
      const hit = (fallback.data ?? []).find((r) => r.order_no === no)
      if (hit) matched.push(hit)
    }
    // 按组内单号顺序稳定输出
    const byNo = new Map(matched.map((r) => [r.order_no, r]))
    return nos.flatMap((no) => {
      const r = byNo.get(no)
      return r ? [r] : []
    })
  }

  /** 单条直开：与原记录查询 tab 的行为一致（picker 只选，不写） */
  function openSingle(record: UnifiedRecord, action: ReportAction) {
    const rec = record as unknown as OrderRecord
    if (record.record_type === 'order') {
      if (action === 'edit') void detailEdit.openDetail(rec)
      else void orderDelete.handleDeleteOrder(rec)
    } else {
      if (action === 'edit') stockinEdit.openStockinEdit(rec)
      else void stockinEdit.handleDeleteStockin(rec)
    }
  }

  /** 行内按钮入口：还原聚合行 → 单条直开或多条选择 */
  async function onRowAction(tab: ReportActionTab, action: ReportAction, row: Record<string, unknown>) {
    // 权限二次防线（2026-10-07）：按钮渲染已由 canEdit/canDelete 门控，这里兜底
    // 程序化调用与未来入口遗漏；口径与按钮一致 = order_edit / order_delete（迁移 075）。
    if (action === 'edit' && !authStore.hasPermission('order_edit')) {
      showToast('没有执行编辑的权限', 'error')
      return
    }
    if (action === 'delete' && !authStore.hasPermission('order_delete')) {
      showToast('没有执行删除的权限', 'error')
      return
    }
    if (resolving.value) return
    resolving.value = true
    try {
      const recordType: 'order' | 'stockin' = tab === 'order' ? 'order' : 'stockin'
      const matched = await resolveRecords(row, recordType)
      if (matched.length === 0) {
        showToast('未能找到该组对应的明细记录', 'error')
        return
      }
      if (matched.length === 1) {
        openSingle(matched[0]!, action)
        return
      }
      pickerRecords.value = matched
      pickerAction.value = action
      pickerOpen.value = true
    } catch (e: unknown) {
      showToast(getErrorMessage(e, '还原记录失败'), 'error')
    } finally {
      resolving.value = false
    }
  }

  /** picker 选定一条：关 picker → 同一单条流程 */
  function onPickerPick(record: UnifiedRecord) {
    pickerOpen.value = false
    openSingle(record, pickerAction.value)
  }

  return {
    // 编辑订单弹窗域
    detailOpen: detailEdit.detailOpen,
    detailData: detailEdit.detailData,
    editForm: detailEdit.editForm,
    availableStockin: detailEdit.availableStockin,
    saving: detailEdit.saving,
    deductRetryPending: detailEdit.deductRetryPending,
    saveEditOrder: detailEdit.saveEditOrder,
    retryDeductUpdate: detailEdit.retryDeductUpdate,
    // 编辑备货弹窗域
    stockinEditVisible: stockinEdit.stockinEditVisible,
    stockinEditForm: stockinEdit.stockinEditForm,
    savingStockin: stockinEdit.savingStockin,
    saveStockinEdit: stockinEdit.saveStockinEdit,
    // 状态样式（EditOrderModal prop）
    getStatusClass,
    // picker
    pickerOpen,
    pickerRecords,
    pickerAction,
    onPickerPick,
    // 确认框与入口
    confirmDialog,
    resolving,
    onRowAction,
  }
}

/** picker 内备注列的取值：备货行备注在明细里 */
export function recordNote(record: UnifiedRecord): string {
  return record.items?.[0]?.note ?? ''
}

/** 供模板判断当前动作（computed 包装保持响应性） */
export function usePickerActionLabel(action: { value: ReportAction }) {
  return computed(() => (action.value === 'edit' ? '编辑' : '删除'))
}
