/**
 * useStockinEdit — 记录查询页里「备货行」的编辑与删除动作域
 *
 * 记录查询把订单与备货混排在同一张表，但两者写路径不同：
 *   订单 → orderApi.update / orderApi.delete（订单域）
 *   备货 → PUT /stock/in/edit/{id} · DELETE /stock/in/delete/{id}（库存域）
 *
 * 备货没有详情端点，所以编辑弹窗的数据直接取自列表行（/orders/records 已下发
 * 数量 / 客户 / 时间 / 备注）。后端删除自带两道保护（已关联出库的拒绝删、
 * 会让库存变负的拒绝删），失败原因由后端消息原样回显。
 *
 * 两个动作成功后都要失效库存派生查询：备货数量参与 /stock 库存聚合，
 * 且后端会同步调整产品的当前库存。
 */
import { ref } from 'vue'
import { useQueryClient } from '@tanstack/vue-query'
import { stockApi } from '@/api'
import { showToast } from '@/composables/useToast'
import { getErrorMessage } from '@/types/errors'
import { invalidateOrderDerivedQueries } from '@/utils/queryKeys'
import type { OrderRecord } from './types'

type ConfirmDialogApi = {
  confirm: (msg: string, subMsg?: string, dialogType?: 'danger' | 'warning') => Promise<boolean>
}

/** 编辑弹窗的表单态：字段与后端 `StockInUpdate` 对齐（产品不可改，后端 schema 就没有 product_id） */
export interface StockinEditForm {
  id: number
  stockinNo: string
  productName: string
  quantity: number
  customer: string
  /** `YYYY-MM-DD`（后端只收日期，时间部分由后端保留原值） */
  date: string
  note: string
}

export function useStockinEdit(
  fetchOrders: () => Promise<void>,
  confirmDialog: ConfirmDialogApi,
) {
  const queryClient = useQueryClient()
  const stockinEditVisible = ref(false)
  const stockinEditForm = ref<StockinEditForm | null>(null)
  const savingStockin = ref(false)

  /** 打开备货编辑弹窗：把列表行摊成表单态 */
  function openStockinEdit(record: OrderRecord) {
    stockinEditForm.value = {
      id: record.id,
      stockinNo: record.order_no || record.stockin_no || '',
      productName: record.items?.[0]?.product_name || record.product?.name || '',
      quantity: record.quantity,
      customer: record.customer || '',
      // 列表下发 'YYYY-MM-DD HH:MM'，日期控件与后端都要 'YYYY-MM-DD'
      date: (record.order_date || '').slice(0, 10),
      // 备货的备注在明细里（后端备货行只有一条 items 记录）
      note: record.items?.[0]?.note || record.note || '',
    }
    stockinEditVisible.value = true
  }

  async function saveStockinEdit() {
    const form = stockinEditForm.value
    if (!form) return
    // 数量被清空时输入框给 ''（非 number），放行只会换来后端笼统的 422
    if (!Number.isFinite(form.quantity) || form.quantity < 1) {
      showToast('请填写大于 0 的备货数量', 'error')
      return
    }
    savingStockin.value = true
    try {
      await stockApi.editStockin(form.id, {
        quantity: form.quantity,
        customer: form.customer,
        // 日期清空 = 保留原值：后端对空串会先做格式校验，拿不到"空则保留"分支，
        // 所以空日期直接不下发该字段
        ...(form.date ? { stockin_date: form.date } : {}),
        note: form.note,
      })
      showToast('备货修改成功', 'success')
      stockinEditVisible.value = false
      invalidateOrderDerivedQueries(queryClient)
      fetchOrders()
    } catch (e: unknown) {
      showToast(getErrorMessage(e, '备货修改失败'), 'error')
    } finally {
      savingStockin.value = false
    }
  }

  async function handleDeleteStockin(record: OrderRecord) {
    const stockinNo = record.order_no || record.stockin_no || ''
    const ok = await confirmDialog.confirm(
      `确定删除备货「${stockinNo}」吗？`,
      '删除会同时扣减该产品的当前库存；已关联出库的备货不能删除。此操作不可撤销。',
      'danger',
    )
    if (!ok) return
    try {
      await stockApi.deleteStockin(record.id)
      showToast('备货删除成功', 'success')
      invalidateOrderDerivedQueries(queryClient)
      fetchOrders()
    } catch (e: unknown) {
      showToast(getErrorMessage(e, '删除备货失败'), 'error')
    }
  }

  return {
    stockinEditVisible,
    stockinEditForm,
    savingStockin,
    openStockinEdit,
    saveStockinEdit,
    handleDeleteStockin,
  }
}
