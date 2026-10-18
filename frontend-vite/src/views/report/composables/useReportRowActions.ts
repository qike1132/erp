/**
 * useReportRowActions — 报表页行内编辑/删除的动作编排
 *
 * 2026-10-13：报表行改为「一行一记录 / 订单母行-明细」，不再有跨记录聚合行 ——
 * 行内按钮直接作用于该行对应的**单条记录**，无需「还原聚合行 + 选择弹窗」：
 *   订单 tab：一行 = 一个 SKU → PUT/DELETE `/orders/items/{item_id}`（单 SKU 语义；
 *             删到最后一个 SKU 时后端等价删整张订单，非超管会变成提交审批）
 *   备货/出货/抵扣/退货：一行 = 一条记录 → 各自单条接口（用 `row.record_id`）
 *
 * 写路径：
 *   订单 → orderApi.updateItem / deleteItem（订单域）
 *   备货 → PUT /stock/in/edit · DELETE /stock/in/delete（库存域）
 *   出货 → PUT /stock/out/edit · DELETE /stock/out/delete（独立出货）
 *   抵扣 → 同上端点（后端按 stockin_id 区分，抵扣行客户不可改）
 *   退货 → PUT /stock-returns/{id}（取消+重建）· DELETE /stock-returns/{id}（硬删除）
 *
 * 权限（迁移 075/079/091）：各维度独立职责分离码，见 TAB_ROW_PERMISSIONS；
 * 按钮渲染由 ReportView 按当前 tab 门控，这里再做一次兜底（程序化调用/入口遗漏）。
 */
import { ref } from 'vue'
import { useQueryClient } from '@tanstack/vue-query'
import { orderApi, stockApi, stockReturnApi } from '@/api'
import { useAuthStore } from '@/stores/auth'
import type { StockFlowRecord } from '@/api/stock'
import type { StockReturnFlowRecord } from '@/api/stockReturn'
import { showToast } from '@/composables/useToast'
import { useConfirmDialog } from '@/composables/useConfirmDialog'
import { getErrorMessage } from '@/types/errors'
import { useStockinEdit } from './useStockinEdit'
import type { OrderRecord } from './orderRecordTypes'

export type ReportActionTab = 'order' | 'stockin' | 'stockout' | 'deduction' | 'return'
export type ReportAction = 'edit' | 'delete'

/** 各维度行内操作的权限码（迁移 075 订单/备货；079 出货/抵扣/退货；091 备货拆出独立码）。
 * 数组镜像后端 require_any_permission 的全部可放行码（含 manage 粗锁兜底）——
 * 漏 manage 会让「只有页面级 manage 权限」的用户被前端误拦 403（后端本会放行）。
 * TAB 名与权限码前缀的单一来源见 @/constants/reportRowActions。 */
export const TAB_ROW_PERMISSIONS: Record<ReportActionTab, { edit: string[]; delete: string[] }> = {
  order: { edit: ['order_edit', 'order_manage'], delete: ['order_delete', 'order_manage'] },
  stockin: { edit: ['stockin_edit', 'order_manage', 'stockin_manage'], delete: ['stockin_delete', 'order_manage', 'stockin_manage'] },
  stockout: { edit: ['stockout_edit', 'stockout_manage'], delete: ['stockout_delete', 'stockout_manage'] },
  deduction: { edit: ['deduction_edit', 'stockout_manage'], delete: ['deduction_delete', 'stockout_manage'] },
  return: { edit: ['return_edit', 'stock_return_manage'], delete: ['return_delete', 'stock_return_manage'] },
}

/** 订单明细编辑弹窗表单态（与后端 `OrderItemUpdate` 对齐） */
export interface OrderItemEditForm {
  itemId: number
  productName: string
  quantity: number
  note: string
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

/** 行对象（后端 ReportLogItem）取值小工具 */
function rowStr(row: Record<string, unknown>, key: string): string {
  const v = row[key]
  return v == null ? '' : String(v)
}
function rowNum(row: Record<string, unknown>, key: string): number {
  const n = Number(row[key])
  return Number.isFinite(n) ? n : 0
}

export function useReportRowActions() {
  const queryClient = useQueryClient()
  const authStore = useAuthStore()

  /** 写入成功后的刷新：前缀失效当前报表查询（queryKey 以 'report-data' 开头） */
  const refreshAfterWrite = () => queryClient.invalidateQueries({ queryKey: ['report-data'] })

  const confirmDialog = useConfirmDialog()
  const stockinEdit = useStockinEdit(refreshAfterWrite, confirmDialog)

  /** 订单明细编辑弹窗（订单流水行内编辑单个 SKU） */
  const orderItemEditVisible = ref(false)
  const orderItemEditForm = ref<OrderItemEditForm | null>(null)
  const savingOrderItem = ref(false)

  /** 出货/抵扣编辑弹窗 */
  const stockoutEditVisible = ref(false)
  const stockoutEditForm = ref<StockoutEditForm | null>(null)
  const stockoutEditIsDeduction = ref(false)
  const savingStockout = ref(false)
  /** 退货编辑弹窗 */
  const returnEditVisible = ref(false)
  const returnEditForm = ref<ReturnEditForm | null>(null)
  const savingReturn = ref(false)

  // ---------------- 订单：单 SKU 编辑/删除 ----------------

  function openOrderItemEdit(row: Record<string, unknown>) {
    const itemId = rowNum(row, 'item_id')
    if (!itemId) {
      showToast('该行没有可编辑的明细', 'error')
      return
    }
    orderItemEditForm.value = {
      itemId,
      productName: rowStr(row, 'product_name'),
      quantity: rowNum(row, 'quantity'),
      note: rowStr(row, 'item_note') || rowStr(row, 'note'),
    }
    orderItemEditVisible.value = true
  }

  async function saveOrderItemEdit() {
    const form = orderItemEditForm.value
    if (!form) return
    // 2026-10-18 OCR 评审：与退货口径一致，数量必须是正整数
    if (!Number.isInteger(form.quantity) || form.quantity < 1) {
      showToast('数量必须为正整数', 'error')
      return
    }
    savingOrderItem.value = true
    try {
      await orderApi.updateItem(form.itemId, { quantity: form.quantity, note: form.note })
      showToast('明细修改成功', 'success')
      orderItemEditVisible.value = false
      refreshAfterWrite()
    } catch (e: unknown) {
      showToast(getErrorMessage(e, '明细修改失败'), 'error')
    } finally {
      savingOrderItem.value = false
    }
  }

  async function handleDeleteOrderItem(row: Record<string, unknown>) {
    const itemId = rowNum(row, 'item_id')
    if (!itemId) {
      showToast('该行没有可删除的明细', 'error')
      return
    }
    const ok = await confirmDialog.confirm(
      `确定删除明细「${rowStr(row, 'product_name')}」吗？`,
      '若这是该订单的最后一个 SKU，将删除整张订单（非管理员需走审批）。此操作不可撤销。',
      'danger',
    )
    if (!ok) return
    try {
      const res = (await orderApi.deleteItem(itemId)) as { message?: string } | undefined
      showToast(res?.message || '明细删除成功', 'success')
      refreshAfterWrite()
    } catch (e: unknown) {
      showToast(getErrorMessage(e, '删除明细失败'), 'error')
    }
  }

  // ---------------- 出货 / 备货抵扣 ----------------

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

  async function saveStockoutEdit() {
    const form = stockoutEditForm.value
    if (!form) return
    // 2026-10-18 OCR 评审：与退货口径一致，数量必须是正整数
    if (!Number.isInteger(form.quantity) || form.quantity < 1) {
      showToast('数量必须为正整数', 'error')
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

  // ---------------- 退货 ----------------

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

  async function saveReturnEdit() {
    const form = returnEditForm.value
    if (!form) return
    // 2026-10-17 审计 P2-47：与新建口径一致，必须为正整数
    if (!Number.isInteger(form.quantity) || form.quantity < 1) {
      showToast('退货数量必须为正整数', 'error')
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

  async function handleDeleteReturn(record: StockReturnFlowRecord) {
    const ok = await confirmDialog.confirm(
      `确定取消退货「${record.return_no}」吗？`,
      '取消将删除该退货单记录，库存与订单状态会对称回冲（对账以库存流水为准）。此操作不可撤销。',
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

  // ---------------- 行对象 → 各维度记录形状 ----------------

  /** 报表行 → 备货记录形状（useStockinEdit 期望 OrderRecord：id/quantity/customer/items…） */
  function stockinRecordFromRow(row: Record<string, unknown>): OrderRecord {
    const note = rowStr(row, 'note')
    return {
      id: rowNum(row, 'record_id'),
      order_no: '',
      stockin_no: rowStr(row, 'record_no'),
      quantity: rowNum(row, 'quantity'),
      customer: rowStr(row, 'customer'),
      order_date: rowStr(row, 'stockin_date'),
      note,
      items: [{ product_name: rowStr(row, 'product_name'), note }],
    } as unknown as OrderRecord
  }

  /** 报表行 → 出货记录形状（openStockoutEdit / handleDeleteStockout 消费）
   *
   * 抵扣行的 `quantity` 是**净量**（quantity − returned），直接回写会把出货毛量改错；
   * 故抵扣行取后端另下发的 `gross_quantity`，日期/备注也取后端补的 `stockout_date`/`note`。
   */
  function stockoutRecordFromRow(row: Record<string, unknown>, isDeduction = false): StockFlowRecord {
    const qty = isDeduction ? rowNum(row, 'gross_quantity') : rowNum(row, 'quantity')
    return {
      id: rowNum(row, 'record_id'),
      stockout_no: rowStr(row, 'record_no'),
      product_name: rowStr(row, 'product_name'),
      quantity: qty,
      customer: rowStr(row, 'customer'),
      stockout_date: rowStr(row, 'stockout_date'),
      note: rowStr(row, 'note'),
    } as unknown as StockFlowRecord
  }

  /** 报表行 → 退货记录形状（openReturnEdit / handleDeleteReturn 消费） */
  function returnRecordFromRow(row: Record<string, unknown>): StockReturnFlowRecord {
    return {
      id: rowNum(row, 'record_id'),
      return_no: rowStr(row, 'record_no'),
      product_name: rowStr(row, 'product_name'),
      quantity: rowNum(row, 'quantity'),
      customer: rowStr(row, 'customer'),
      return_date: rowStr(row, 'return_date'),
      reason: rowStr(row, 'reason'),
      note: rowStr(row, 'note'),
    } as unknown as StockReturnFlowRecord
  }

  // ---------------- 入口 ----------------

  /** 行内按钮入口：直接作用于该行对应的单条记录（不再还原聚合行/弹 picker） */
  async function onRowAction(tab: ReportActionTab, action: ReportAction, row: Record<string, unknown>) {
    // 权限二次防线：按钮渲染已由 ReportView 门控，这里兜底程序化调用与未来入口遗漏
    const perm = TAB_ROW_PERMISSIONS[tab]
    if (action === 'edit' && !authStore.hasAnyPermission(perm.edit)) {
      showToast('没有执行编辑的权限', 'error')
      return
    }
    if (action === 'delete' && !authStore.hasAnyPermission(perm.delete)) {
      showToast('没有执行删除的权限', 'error')
      return
    }
    try {
      if (tab === 'order') {
        if (action === 'edit') openOrderItemEdit(row)
        else await handleDeleteOrderItem(row)
        return
      }
      if (tab === 'stockin') {
        const rec = stockinRecordFromRow(row)
        if (action === 'edit') stockinEdit.openStockinEdit(rec)
        else await stockinEdit.handleDeleteStockin(rec)
        return
      }
      if (tab === 'stockout' || tab === 'deduction') {
        const rec = stockoutRecordFromRow(row, tab === 'deduction')
        if (action === 'edit') openStockoutEdit(rec, tab === 'deduction')
        else await handleDeleteStockout(rec)
        return
      }
      const rec = returnRecordFromRow(row)
      if (action === 'edit') openReturnEdit(rec)
      else await handleDeleteReturn(rec)
    } catch (e: unknown) {
      showToast(getErrorMessage(e, '操作失败'), 'error')
    }
  }

  return {
    // 订单明细编辑弹窗域
    orderItemEditVisible,
    orderItemEditForm,
    savingOrderItem,
    saveOrderItemEdit,
    // 备货编辑弹窗域
    stockinEditVisible: stockinEdit.stockinEditVisible,
    stockinEditForm: stockinEdit.stockinEditForm,
    savingStockin: stockinEdit.savingStockin,
    saveStockinEdit: stockinEdit.saveStockinEdit,
    // 出货/抵扣编辑弹窗域
    stockoutEditVisible,
    stockoutEditForm,
    stockoutEditIsDeduction,
    savingStockout,
    saveStockoutEdit,
    // 退货编辑弹窗域
    returnEditVisible,
    returnEditForm,
    savingReturn,
    saveReturnEdit,
    // 确认框与入口
    confirmDialog,
    onRowAction,
  }
}
