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

  async function handleViewDetail(id: number) {
    try {
      const res = await purchaseApi.orderDetail(id)
      if (res.success && res.order) {
        detailOrder.value = res.order
        detailVisible.value = true
      } else showToast(res.message || '获取详情失败', 'error')
    } catch (err: unknown) {
      showToast((err as Error).message || '获取详情失败', 'error')
    }
  }

  return { detailVisible, detailOrder, handleViewDetail }
}