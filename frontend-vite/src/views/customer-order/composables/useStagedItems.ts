/**
 * useStagedItems — 暂存项动作域（批次 2-3 拆分自 useOrderActions）
 *
 * 承载暂存订单/备货条目状态、删除与批量提交（含部分失败保留重试语义）。
 * 函数逻辑自 useOrderActions.ts 原样搬移。
 */
import { ref, computed, type Ref, type ComputedRef } from 'vue'
import { useQueryClient } from '@tanstack/vue-query'
import { post } from '@/api/request'
import { showToast } from '@/composables/useToast'
import { useConfirmDialog } from '@/composables/useConfirmDialog'
import { getErrorMessage } from '@/types/errors'
import type { StagedItem } from './types'

/** /aux/batch-submit-orders 批量提交响应（兼容裸返回与 { data } 包裹两种结构） */
export interface BatchSubmitOrdersResponse {
  created_count?: number
  results?: { success: boolean; error?: string }[]
  data?: BatchSubmitOrdersResponse
}

/**
 * 生成暂存项唯一标识。
 * crypto.randomUUID 仅在安全上下文（HTTPS/localhost）可用；
 * 内网 HTTP 部署下它未定义，降级为「时间戳 + 随机数」以避免崩溃。
 */
export function genUid(): string {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
    return crypto.randomUUID()
  }
  return `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}-${Math.random().toString(36).slice(2, 10)}`
}

export function useStagedItems() {
  const queryClient = useQueryClient()
  const confirmDialog = useConfirmDialog()

  const stagedItems = ref<StagedItem[]>([])

  async function removeStagedItem(uid: string) {
    const ok = await confirmDialog.confirm('确定删除？', '此操作不可恢复', 'danger')
    if (!ok) return
    // 通过 uid 安全定位，避免异步 confirm 期间索引失效
    const idx = stagedItems.value.findIndex((i) => i.uid === uid)
    if (idx >= 0) stagedItems.value.splice(idx, 1)
  }

  const stagedOrders = computed(() => stagedItems.value.filter((i) => i.type === 'order'))
  const stagedStockins = computed(() => stagedItems.value.filter((i) => i.type === 'stockin'))

  const submitting = ref(false)

  async function submitAll() {
    if (!stagedItems.value.length || submitting.value) return
    submitting.value = true
    try {
      const orderPayload = stagedOrders.value.map((i) => ({
        product_id: i.productId,
        customer: i.customer,
        quantity: i.quantity,
        deduct_stock: i.deductStock || false,
        deduct_quantity: i.deductQuantity || 0,
        note: i.note || '',
        order_date: i.date || '',
        order_type: i.orderType === 'custom' ? 'custom' : 'regular',
        country: i.country || '',
      }))
      const stockinPayload = stagedStockins.value.map((i) => ({
        product_id: i.productId,
        customer: i.customer,
        quantity: i.quantity,
        note: i.note || '',
        stockin_date: i.date || '',
        order_type: i.orderType === 'custom' ? 'custom' : 'regular',
        country: i.country || '',
      }))

      const orderUids = stagedOrders.value.map((i) => i.uid)
      const stockinUids = stagedStockins.value.map((i) => i.uid)

      let orderFailed = false
      let stockinFailed = false
      let orderRes: BatchSubmitOrdersResponse | null = null

      if (orderPayload.length) {
        try {
          orderRes = await post<BatchSubmitOrdersResponse>('/aux/batch-submit-orders', { orders: orderPayload })
        } catch (e: unknown) {
          showToast(getErrorMessage(e, '订单提交失败'), 'error')
          orderFailed = true
        }
      }
      if (!orderFailed && stockinPayload.length) {
        try {
          await post('/aux/batch-submit-stockins', { stockins: stockinPayload })
        } catch (e: unknown) {
          showToast(getErrorMessage(e, '备货提交失败'), 'error')
          stockinFailed = true
        }
      }

      // 仅移除成功提交的项，保留失败的项供用户重试
      if (!orderFailed) {
        stagedItems.value = stagedItems.value.filter((i) => !orderUids.includes(i.uid))
      }
      if (!stockinFailed) {
        stagedItems.value = stagedItems.value.filter((i) => !stockinUids.includes(i.uid))
      }

      // 反馈：部分失败时明确告知用户状态
      if (orderFailed && !stockinFailed && stockinPayload.length) {
        showToast('备货已提交成功，但订单提交失败，请重新提交订单', 'warning')
      } else if (!orderFailed && stockinFailed && orderPayload.length) {
        showToast(`订单已提交成功，但备货提交失败，请重新提交备货`, 'warning')
      } else if (!orderFailed && !stockinFailed) {
        if (orderPayload.length && orderRes) {
          const resData = orderRes.data ?? orderRes
          const createdCount = resData?.created_count ?? 0
          const skuCount = orderPayload.length
          if (createdCount === 0) {
            // 订单全部失败：提取后端返回的错误详情
            const failedResults = (resData?.results ?? []).filter((r) => !r.success)
            const firstError = failedResults[0]?.error || '未知原因'
            showToast(`订单创建失败（0/${skuCount}）：${firstError}`, 'error')
          } else {
            showToast(`提交成功：已创建 ${createdCount} 个主订单（含 ${skuCount} 个 SKU）`, 'success')
          }
        } else {
          showToast('提交成功', 'success')
        }
      }

      if (!orderFailed) queryClient.invalidateQueries({ queryKey: ['orders-list'] })
      if (!stockinFailed) queryClient.invalidateQueries({ queryKey: ['stockins-list'] })
    } finally {
      submitting.value = false
    }
  }

  return {
    stagedItems: stagedItems as Ref<StagedItem[]>,
    stagedOrders: stagedOrders as ComputedRef<StagedItem[]>,
    stagedStockins: stagedStockins as ComputedRef<StagedItem[]>,
    submitting,
    removeStagedItem,
    submitAll,
    confirmDialog,
  }
}
