/**
 * useOrderDetailEdit — 订单详情与编辑动作域（批次 2-3 拆分自 useOrderActions）
 *
 * 承载详情弹窗、保存编辑（含抵扣两步更新与失败重试）。逻辑原样搬移。
 */
import { ref, reactive } from 'vue'
import { useQueryClient } from '@tanstack/vue-query'
import { get } from '@/api/request'
import { orderApi } from '@/api'
import { showToast } from '@/composables/useToast'
import { getErrorMessage } from '@/types/errors'
import type { OrderRecord, OrderDetailData } from './types'

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
          const availRes = await get<{ available_quantity?: number; available?: number; data?: { available_quantity?: number; available?: number } }>('/aux/available-stockins', { product_id: data.product.id, customer: data.customer })
          const availData = availRes.data ?? availRes
          availableStockin.value = (availData.available_quantity ?? availData.available ?? 0) + (data.deduct_quantity || 0)
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
          queryClient.invalidateQueries({ queryKey: ['orders-list'] })
          queryClient.invalidateQueries({ queryKey: ['inventory'] })
          queryClient.invalidateQueries({ queryKey: ['stockins-list'] })
          queryClient.invalidateQueries({ queryKey: ['stockouts-list'] })
          fetchOrders()
          return
        }
      }

      showToast('保存成功', 'success')
      detailOpen.value = false
      queryClient.invalidateQueries({ queryKey: ['orders-list'] })
      queryClient.invalidateQueries({ queryKey: ['inventory'] })
      queryClient.invalidateQueries({ queryKey: ['stockins-list'] })
      queryClient.invalidateQueries({ queryKey: ['stockouts-list'] })
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
      queryClient.invalidateQueries({ queryKey: ['orders-list'] })
      queryClient.invalidateQueries({ queryKey: ['inventory'] })
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
