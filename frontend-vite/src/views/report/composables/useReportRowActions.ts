/**
 * useReportRowActions — 报表页行内编辑/删除的动作编排
 *
 * 报表行是聚合行（同日+客户+产品一组，group 内多条记录由后端下发单号串）。
 * 点编辑/删除时先「还原」：按该组的单号取回具体记录，恰好一条 → 直接打开对应
 * 编辑弹窗/删除确认；多条 → 弹选择弹窗逐条操作。还原数据源按维度不同：
 *   订单/备货 → orderApi.records（结构化筛选 + 组内单号精确回比，缺失补查）
 *   出货/抵扣 → stockApi.stockoutRecords（按 stockout_no / order_no 取明细）
 *   退货      → stockReturnApi.records（按 return_no 取明细）
 *
 * 写路径（2026-10-07 扩展出货/抵扣/退货）：
 *   订单 → orderApi.update / delete（订单域）
 *   备货 → PUT /stock/in/edit · DELETE /stock/in/delete（库存域）
 *   出货 → PUT /stock/out/edit · DELETE /stock/out/delete（独立出货）
 *   抵扣 → 同上端点（后端按 stockin_id 区分，抵扣行客户不可改）
 *   退货 → PUT /stock-returns/{id}（取消+重建）· DELETE /stock-returns/{id}（软取消）
 *
 * 权限（迁移 075/079）：各维度独立职责分离码，见 TAB_ROW_PERMISSIONS；
 * 按钮渲染由 ReportView 按当前 tab 门控，这里再做一次兜底（程序化调用/入口遗漏）。
 */
import { ref, computed } from 'vue'
import { useQueryClient } from '@tanstack/vue-query'
import { orderApi, stockApi, stockReturnApi } from '@/api'
import { useAuthStore } from '@/stores/auth'
import type { UnifiedRecord, OrderRecordsQuery } from '@/api/order'
import type { StockFlowRecord } from '@/api/stock'
import type { StockReturnFlowRecord } from '@/api/stockReturn'
import { showToast } from '@/composables/useToast'
import { useConfirmDialog } from '@/composables/useConfirmDialog'
import { getErrorMessage } from '@/types/errors'
import { getStatusClass, useOrderDetailEdit } from './useOrderDetailEdit'
import { useOrderDelete } from './useOrderDelete'
import { useStockinEdit } from './useStockinEdit'
import type { OrderRecord } from './orderRecordTypes'

export type ReportActionTab = 'order' | 'stockin' | 'stockout' | 'deduction' | 'return'
export type ReportAction = 'edit' | 'delete'

/** 各维度行内操作的权限码（迁移 075 订单/备货；079 出货/抵扣/退货） */
export const TAB_ROW_PERMISSIONS: Record<ReportActionTab, { edit: string; delete: string }> = {
  order: { edit: 'order_edit', delete: 'order_delete' },
  stockin: { edit: 'order_edit', delete: 'order_delete' },
  stockout: { edit: 'stockout_edit', delete: 'stockout_delete' },
  deduction: { edit: 'deduction_edit', delete: 'deduction_delete' },
  return: { edit: 'return_edit', delete: 'return_delete' },
}

/** picker 选择弹窗的列取值键（按维度；order/stockin 的备注在 items 内，见 recordNote） */
const PICKER_KEYS: Record<ReportActionTab, { noKey: string; dateKey: string; noteKey?: string }> = {
  order: { noKey: 'order_no', dateKey: 'order_date' },
  stockin: { noKey: 'order_no', dateKey: 'order_date' },
  stockout: { noKey: 'stockout_no', dateKey: 'stockout_date', noteKey: 'note' },
  deduction: { noKey: 'stockout_no', dateKey: 'stockout_date', noteKey: 'note' },
  return: { noKey: 'return_no', dateKey: 'return_date', noteKey: 'note' },
}

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

/** 出货/抵扣编辑弹窗表单态（字段与后端 `StockOutUpdate` 对齐） */
export interface StockoutEditForm {
  id: number
  stockoutNo: string
  productName: string
  quantity: number
  customer: string
  /** `YYYY-MM-DD` */
  date: string
  note: string
}

/** 退货编辑弹窗表单态（字段与后端 `StockReturnUpdate` 对齐） */
export interface ReturnEditForm {
  id: number
  returnNo: string
  productName: string
  quantity: number
  customer: string
  /** `YYYY-MM-DD` */
  date: string
  reason: string
  note: string
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
  const pickerRecords = ref<object[]>([])
  const pickerAction = ref<ReportAction>('edit')
  const pickerTab = ref<ReportActionTab>('order')
  /** 还原查询进行中：防重入 */
  const resolving = ref(false)

  /** 出货/抵扣编辑弹窗 */
  const stockoutEditVisible = ref(false)
  const stockoutEditForm = ref<StockoutEditForm | null>(null)
  const stockoutEditIsDeduction = ref(false)
  const savingStockout = ref(false)
  /** 退货编辑弹窗 */
  const returnEditVisible = ref(false)
  const returnEditForm = ref<ReturnEditForm | null>(null)
  const savingReturn = ref(false)

  /** 订单/备货：还原聚合行为具体记录（orderApi.records 结构化筛选 + 单号精确回比） */
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

  /** 出货/抵扣：按单号取明细（出货=stockout_no，抵扣=关联订单号）；带产品名收窄 */
  async function resolveStockoutRecords(row: Record<string, unknown>, kind: 'stockout' | 'deduction'): Promise<StockFlowRecord[]> {
    const rawNos = kind === 'deduction' ? row.order_nos : row.stockout_nos
    const nos = parseGroupNos(String(rawNos ?? ''))
    if (nos.length === 0) {
      showToast('未能找到该组对应的明细记录', 'error')
      return []
    }
    // 同一订单可能对多个产品分别抵扣：只凭订单号会还原出他产品的抵扣行，带上行内产品名收窄
    const res = await stockApi.stockoutRecords(kind, nos.join(','), String(row.product_name ?? ''))
    return res.data ?? []
  }

  /** 退货：按退货单号取明细 */
  async function resolveReturnRecords(row: Record<string, unknown>): Promise<StockReturnFlowRecord[]> {
    const nos = parseGroupNos(String(row.return_nos ?? ''))
    if (nos.length === 0) {
      showToast('未能找到该组对应的明细记录', 'error')
      return []
    }
    const res = await stockReturnApi.records(nos.join(','))
    return res.data ?? []
  }

  /** 打开出货/抵扣编辑弹窗（抵扣行的客户不可改） */
  function openStockoutEdit(record: StockFlowRecord, isDeduction: boolean) {
    stockoutEditIsDeduction.value = isDeduction
    stockoutEditForm.value = {
      id: record.id,
      stockoutNo: record.stockout_no || '',
      productName: record.product_name || '',
      quantity: record.quantity,
      customer: record.customer || '',
      date: (record.stockout_date || '').slice(0, 10),
      note: record.note || '',
    }
    stockoutEditVisible.value = true
  }

  /** 打开退货编辑弹窗 */
  function openReturnEdit(record: StockReturnFlowRecord) {
    returnEditForm.value = {
      id: record.id,
      returnNo: record.return_no || '',
      productName: record.product_name || '',
      quantity: record.quantity,
      customer: record.customer || '',
      date: (record.return_date || '').slice(0, 10),
      reason: record.reason || '',
      note: record.note || '',
    }
    returnEditVisible.value = true
  }

  async function saveStockoutEdit() {
    const form = stockoutEditForm.value
    if (!form) return
    if (!Number.isFinite(form.quantity) || form.quantity < 1) {
      showToast('请填写大于 0 的数量', 'error')
      return
    }
    savingStockout.value = true
    try {
      await stockApi.editStockout(form.id, {
        quantity: form.quantity,
        // 抵扣行客户由订单/备货带出，不下发
        ...(stockoutEditIsDeduction.value ? {} : { customer: form.customer }),
        // 日期清空 = 保留原值（后端对空串先做格式校验，拿不到「空则保留」分支）
        ...(form.date ? { stockout_date: form.date } : {}),
        note: form.note,
      })
      showToast('出货修改成功', 'success')
      stockoutEditVisible.value = false
      refreshAfterWrite()
    } catch (e: unknown) {
      showToast(getErrorMessage(e, '出货修改失败'), 'error')
    } finally {
      savingStockout.value = false
    }
  }

  async function saveReturnEdit() {
    const form = returnEditForm.value
    if (!form) return
    if (!Number.isFinite(form.quantity) || form.quantity < 1) {
      showToast('请填写大于 0 的退货数量', 'error')
      return
    }
    savingReturn.value = true
    try {
      const res = await stockReturnApi.update(form.id, {
        quantity: form.quantity,
        ...(form.date ? { return_date: form.date } : {}),
        reason: form.reason,
        note: form.note,
      })
      showToast(res?.message || '退货修改成功', 'success')
      returnEditVisible.value = false
      refreshAfterWrite()
    } catch (e: unknown) {
      showToast(getErrorMessage(e, '退货修改失败'), 'error')
    } finally {
      savingReturn.value = false
    }
  }

  async function handleDeleteStockout(record: StockFlowRecord) {
    const ok = await confirmDialog.confirm(
      `确定删除出货「${record.stockout_no}」吗？`,
      '删除会回补产品库存；若为订单抵扣出货，还会释放所属备货的可用量并重算订单状态。此操作不可撤销。',
      'danger',
    )
    if (!ok) return
    try {
      await stockApi.deleteStockout(record.id)
      showToast('出货删除成功', 'success')
      refreshAfterWrite()
    } catch (e: unknown) {
      showToast(getErrorMessage(e, '删除出货失败'), 'error')
    }
  }

  async function handleDeleteReturn(record: StockReturnFlowRecord) {
    const ok = await confirmDialog.confirm(
      `确定取消退货「${record.return_no}」吗？`,
      '取消为软取消（记录保留），库存与订单状态会对称回冲。此操作不可撤销。',
      'danger',
    )
    if (!ok) return
    try {
      await stockReturnApi.remove(record.id)
      showToast('退货取消成功', 'success')
      refreshAfterWrite()
    } catch (e: unknown) {
      showToast(getErrorMessage(e, '取消退货失败'), 'error')
    }
  }

  /** 单条直开：按维度走各自的编辑弹窗/删除确认（picker 只选，不写） */
  function openSingleForTab(tab: ReportActionTab, record: object, action: ReportAction) {
    if (tab === 'order' || tab === 'stockin') {
      const rec = record as OrderRecord
      if (tab === 'order') {
        if (action === 'edit') void detailEdit.openDetail(rec)
        else void orderDelete.handleDeleteOrder(rec)
      } else {
        if (action === 'edit') stockinEdit.openStockinEdit(rec)
        else void stockinEdit.handleDeleteStockin(rec)
      }
      return
    }
    if (tab === 'stockout' || tab === 'deduction') {
      const rec = record as StockFlowRecord
      if (action === 'edit') openStockoutEdit(rec, tab === 'deduction')
      else void handleDeleteStockout(rec)
      return
    }
    const rec = record as StockReturnFlowRecord
    if (action === 'edit') openReturnEdit(rec)
    else void handleDeleteReturn(rec)
  }

  /** 行内按钮入口：还原聚合行 → 单条直开或多条选择 */
  async function onRowAction(tab: ReportActionTab, action: ReportAction, row: Record<string, unknown>) {
    // 权限二次防线：按钮渲染已由 ReportView 门控，这里兜底程序化调用与未来入口遗漏
    const perm = TAB_ROW_PERMISSIONS[tab]
    if (action === 'edit' && !authStore.hasPermission(perm.edit)) {
      showToast('没有执行编辑的权限', 'error')
      return
    }
    if (action === 'delete' && !authStore.hasPermission(perm.delete)) {
      showToast('没有执行删除的权限', 'error')
      return
    }
    if (resolving.value) return
    resolving.value = true
    try {
      // 各维度记录类型（UnifiedRecord / StockFlowRecord / StockReturnFlowRecord）收进
      // 统一的行记录形态（object[]）供 picker 与单条分派使用；分派处再收窄为行对象。
      let matched: object[]
      if (tab === 'order' || tab === 'stockin') {
        matched = await resolveRecords(row, tab === 'order' ? 'order' : 'stockin')
      } else if (tab === 'stockout' || tab === 'deduction') {
        matched = await resolveStockoutRecords(row, tab)
      } else {
        matched = await resolveReturnRecords(row)
      }
      if (matched.length === 0) {
        showToast('未能找到该组对应的明细记录', 'error')
        return
      }
      if (matched.length === 1) {
        openSingleForTab(tab, matched[0]!, action)
        return
      }
      pickerTab.value = tab
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
  function onPickerPick(record: object) {
    pickerOpen.value = false
    openSingleForTab(pickerTab.value, record, pickerAction.value)
  }

  /** picker 当前维度的列取值键（noKey/dateKey/noteKey） */
  const pickerKeys = computed(() => PICKER_KEYS[pickerTab.value])

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
    // 编辑出货/抵扣弹窗域
    stockoutEditVisible,
    stockoutEditForm,
    stockoutEditIsDeduction,
    savingStockout,
    saveStockoutEdit,
    // 编辑退货弹窗域
    returnEditVisible,
    returnEditForm,
    savingReturn,
    saveReturnEdit,
    // 状态样式（EditOrderModal prop）
    getStatusClass,
    // picker
    pickerOpen,
    pickerRecords,
    pickerAction,
    pickerKeys,
    onPickerPick,
    // 确认框与入口
    confirmDialog,
    resolving,
    onRowAction,
  }
}

/** picker 内备注列的取值：备货/订单行备注在明细里；其余维度由 pickerKeys.noteKey 直接取 */
export function recordNote(record: Record<string, unknown>): string {
  const items = record.items as Array<{ note?: string }> | undefined
  return items?.[0]?.note ?? ''
}

/** 供模板判断当前动作（computed 包装保持响应性） */
export function usePickerActionLabel(action: { value: ReportAction }) {
  return computed(() => (action.value === 'edit' ? '编辑' : '删除'))
}
