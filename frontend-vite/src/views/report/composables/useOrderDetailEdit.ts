/**
 * useOrderDetailEdit — 订单详情与编辑动作域
 *
 * 2026-10-06 记录查询 tab 收敛至报表页时自 customer-order/composables 迁入，
 * 承载详情弹窗、保存编辑（含抵扣两步更新与失败重试）；getStatusClass（状态样式
 * 映射，原在 useOrderList）一并收编供 EditOrderModal 消费。逻辑原样搬移。
 */
import { ref, reactive } from 'vue'
import { useQueryClient } from '@tanstack/vue-query'
import { auxApi, orderApi } from '@/api'
import { showToast } from '@/composables/useToast'
import { getErrorMessage } from '@/types/errors'
import { invalidateOrderDerivedQueries } from '@/utils/queryKeys'
import { QUANTITY_RANGE_MESSAGE, isQuantityOutOfRange } from '@/utils/quantity'
import type { OrderRecord, OrderDetailData } from './orderRecordTypes'

/** 状态样式映射（EditOrderModal 的状态点配色；类名沿用 customer-order 既有前缀） */
export function getStatusClass(status: string): string {
  const map: Record<string, string> = {
    '待备货': 'co-status-pending',
    '已备货': 'co-status-stocked',
    '部分备货': 'co-status-partial',
    '待出货': 'co-status-shipping',
    '已出货': 'co-status-shipped',
    '已取消': 'co-status-cancelled',
    '批次已完成': 'co-status-completed',
  }
  return map[status] || 'co-status-pending'
}

export function useOrderDetailEdit(fetchOrders: () => Promise<void>) {
  const queryClient = useQueryClient()

  const detailOpen = ref(false)
  const detailData = ref<OrderDetailData | null>(null)
  const editForm = reactive({ quantity: 1, deductQuantity: 0, note: '' })
  const availableStockin = ref(0)
  const saving = ref(false)
  /** 标记抵扣更新是否待重试（第一次成功、第二次失败时） */
  const deductRetryPending = ref(false)

  async function openDetail(item: OrderRecord) {
    try {
      const res = await orderApi.detail(item.id) as OrderDetailData
      const data = (res.data ?? res) as OrderDetailData
      detailData.value = data
      editForm.quantity = data.quantity || 1
      editForm.deductQuantity = data.deduct_quantity || 0
      editForm.note = data.note || ''
      // 查询可用备货量
      if (data.product?.id && data.customer) {
        try {
          // 契约修正（2026-09-18）：后端 `response_model=list[AvailableStockinItem]` 返回**裸数组**，
          // 原实现按单对象读 `available_quantity` / `available`（两个键都不存在于数组响应），
          // 故 `availableStockin` 恒为 0、编辑弹窗的「可用」提示永不显示。此处与
          // useOrderForm / useStagedEdit 口径统一为「按条累加 available」。
          const availRes = await auxApi.availableStockins({ product_id: data.product.id, customer: data.customer })
          const total = (Array.isArray(availRes) ? availRes : []).reduce(
            (s, i) => s + (i.available ?? i.quantity ?? 0), 0,
          )
          availableStockin.value = total + (data.deduct_quantity || 0)
        } catch {
          availableStockin.value = 0
        }
      } else {
        availableStockin.value = 0
      }
      deductRetryPending.value = false
      detailOpen.value = true
    } catch {
      showToast('获取订单详情失败', 'error')
    }
  }

  async function saveEditOrder() {
    if (!detailData.value || saving.value) return
    // 提交前最终校验：字段实时标红可能被绕过（回车 / 直接点保存），
    // 越界数量一律不提交，避免把非法值写进订单。
    if (isQuantityOutOfRange(editForm.quantity)) {
      showToast(QUANTITY_RANGE_MESSAGE, 'warning')
      return
    }
    saving.value = true
    try {
      const originalDeduct = detailData.value.deduct_quantity || 0

      // 第一步：更新基本信息（数量、备注）
      await orderApi.update(detailData.value.id, {
        quantity: editForm.quantity,
        note: editForm.note,
      })

      // 第二步：更新抵扣数量（若变更）。非原子操作，失败后标记待重试
      if (editForm.deductQuantity !== originalDeduct) {
        try {
          await orderApi.updateDeduct(detailData.value.id, editForm.deductQuantity)
          deductRetryPending.value = false
        } catch (e: unknown) {
          deductRetryPending.value = true
          showToast(
            getErrorMessage(e, '订单信息已保存，但抵扣数量更新失败，请重试抵扣更新'),
            'warning',
          )
          // 仍然刷新列表以反映已保存的数量变更
          invalidateOrderDerivedQueries(queryClient)
          fetchOrders()
          return
        }
      }

      showToast('保存成功', 'success')
      detailOpen.value = false
      invalidateOrderDerivedQueries(queryClient)
      fetchOrders()
    } catch (e: unknown) {
      showToast(getErrorMessage(e, '保存失败'), 'error')
    } finally {
      saving.value = false
    }
  }

  /** 重试抵扣数量更新（saveEditOrder 中抵扣更新失败后调用） */
  async function retryDeductUpdate() {
    if (!detailData.value || saving.value) return
    saving.value = true
    try {
      await orderApi.updateDeduct(detailData.value.id, editForm.deductQuantity)
      deductRetryPending.value = false
      showToast('抵扣数量更新成功', 'success')
      detailOpen.value = false
      invalidateOrderDerivedQueries(queryClient)
      fetchOrders()
    } catch (e: unknown) {
      showToast(getErrorMessage(e, '抵扣更新仍失败，请稍后重试'), 'error')
    } finally {
      saving.value = false
    }
  }

  return {
    detailOpen,
    detailData,
    editForm,
    availableStockin,
    saving,
    deductRetryPending,
    openDetail,
    saveEditOrder,
    retryDeductUpdate,
  }
}
