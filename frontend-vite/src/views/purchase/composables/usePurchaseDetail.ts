import { ref } from 'vue'
import { purchaseApi } from '@/api'
import { showToast } from '@/composables/useToast'
import type { PurchaseOrder } from '@/types'

/**
 * usePurchaseDetail — 订单详情模态状态与查看逻辑
 *
 * 从 usePurchaseHandlers 拆出：零外部依赖，可独立测试。
 */
export function usePurchaseDetail() {
  const detailVisible = ref(false)
  const detailOrder = ref<PurchaseOrder | null>(null)
  // F-FE-DESK-CORE-05：请求序号——连点两张订单详情时，慢响应后到会把弹窗内容
  // 悄悄替换成先点的那张；再加 res.order.id 与请求意图双保险。
  let detailSeq = 0
  const detailLoading = ref(false)

  async function handleViewDetail(id: number) {
    const seq = ++detailSeq
    detailLoading.value = true
    try {
      const res = await purchaseApi.orderDetail(id)
      if (seq !== detailSeq) return // 已有更新的请求在途，丢弃过期响应
      if (res.success && res.order && res.order.id === id) {
        detailOrder.value = res.order
        detailVisible.value = true
      } else showToast(res.message || '获取详情失败', 'error')
    } catch (err: unknown) {
      if (seq !== detailSeq) return
      showToast((err as Error).message || '获取详情失败', 'error')
    } finally {
      if (seq === detailSeq) detailLoading.value = false
    }
  }

  return { detailVisible, detailOrder, detailLoading, handleViewDetail }
}