/**
 * useStockinEdit — 「备货行」的编辑与删除动作域
 *
 * 2026-10-06 记录查询 tab 收敛至报表页时自 customer-order/composables 迁入。
 * 报表页把订单与备货混排在同一张表，但两者写路径不同：
 *   订单 → orderApi.update / orderApi.delete（订单域）
 *   备货 → PUT /stock/in/edit/{id} · DELETE /stock/in/delete/{id}（库存域）
 *
 * 备货没有详情端点，所以编辑弹窗的数据直接取自还原后的记录行（/orders/records
 * 已下发数量 / 客户 / 时间 / 备注）。后端删除自带两道保护（已关联出库的拒绝删、
 * 会让库存变负的拒绝删；2026-10-01 起编辑数量同样有这两道守卫），
 * 失败原因由后端消息原样回显。
 *
 * 写路径走 useApiMutation 统一封装（OPT-09 试点）：成功提示 / 领域缓存失效 /
 * in-flight 状态收敛在一处；失效键集来自 utils/queryKeys，备货数量参与库存
 * 聚合且后端会同步调整产品当前库存，故整体失效订单派生域。
 */
import { ref } from 'vue'
import { useApiMutation } from '@/composables/useApiMutation'
import { stockApi } from '@/api'
import { showToast } from '@/composables/useToast'
import { invalidateOrderDerivedQueries } from '@/utils/queryKeys'
import type { OrderRecord } from './orderRecordTypes'

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
  const stockinEditVisible = ref(false)
  const stockinEditForm = ref<StockinEditForm | null>(null)

  /** 打开备货编辑弹窗：把记录行摊成表单态 */
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

  const editStockin = useApiMutation(
    (form: StockinEditForm) =>
      stockApi.editStockin(form.id, {
        quantity: form.quantity,
        customer: form.customer,
        // 日期清空 = 保留原值：后端对空串会先做格式校验，拿不到"空则保留"分支，
        // 所以空日期直接不下发该字段
        ...(form.date ? { stockin_date: form.date } : {}),
        note: form.note,
      }),
    {
      invalidate: invalidateOrderDerivedQueries,
      successMsg: '备货修改成功',
      errorMsg: '备货修改失败',
      onSuccess: () => {
        stockinEditVisible.value = false
        fetchOrders()
      },
    },
  )

  async function saveStockinEdit() {
    const form = stockinEditForm.value
    if (!form) return
    // 数量被清空时输入框给 ''（非 number），放行只会换来后端笼统的 422。
    // 与其他三条编辑路径统一用整数校验：小数虽 isFinite 通过，后端 quantity 是整数列。
    if (!Number.isInteger(form.quantity) || form.quantity < 1) {
      showToast('请填写大于 0 的整数备货数量', 'error')
      return
    }
    await editStockin.run(form)
  }

  const removeStockin = useApiMutation(
    (id: number) => stockApi.deleteStockin(id),
    {
      invalidate: invalidateOrderDerivedQueries,
      successMsg: '备货删除成功',
      errorMsg: '删除备货失败',
      onSuccess: () => fetchOrders(),
    },
  )

  async function handleDeleteStockin(record: OrderRecord) {
    const stockinNo = record.order_no || record.stockin_no || ''
    const ok = await confirmDialog.confirm(
      `确定删除备货「${stockinNo}」吗？`,
      '删除会同时扣减该产品的当前库存；已关联出库的备货不能删除。此操作不可撤销。',
      'danger',
    )
    if (!ok) return
    await removeStockin.run(record.id)
  }

  return {
    stockinEditVisible,
    stockinEditForm,
    savingStockin: editStockin.isSaving,
    openStockinEdit,
    saveStockinEdit,
    handleDeleteStockin,
  }
}
