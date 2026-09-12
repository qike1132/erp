import { ref, computed } from 'vue'
import { useQueryClient } from '@tanstack/vue-query'
import { usePurchaseOrders } from './usePurchaseOrders'
import { useUnprocessedOrders } from './useUnprocessedOrders'
import { useCompletedOrders } from './useCompletedOrders'
import { useSummaryModal } from './useSummaryModal'
import { useConfirmDialog } from '@/composables/useConfirmDialog'
import { useWebSocket } from '@/composables/useWebSocket'
import { usePurchaseDetail } from './usePurchaseDetail'
import { usePurchaseActions } from './usePurchaseActions'

/**
 * usePurchaseHandlers — 采购页面顶层协调器
 *
 * P0-3 拆分后职责：
 *  - 初始化数据 composable（unprocessed/purchaseOrders/completed/summary）
 *  - 编排 tab 切换与按需加载（P1-10）
 *  - 编排实时刷新：Vue Query refetchInterval（P2-11）+ WebSocket
 *  - 聚合子模块返回值：usePurchaseDetail（详情）+ usePurchaseActions（业务动作）
 *
 * 业务动作实现见 usePurchaseActions.ts；详情逻辑见 usePurchaseDetail.ts。
 */
export function usePurchaseHandlers() {
  const queryClient = useQueryClient()
  const activeTab = ref<'pending' | 'active' | 'history'>('pending')
  const ordersTabActive = computed(() => activeTab.value === 'pending' || activeTab.value === 'active')

  // P2-11: 用 Vue Query refetchInterval 替代 useAutoRefresh setInterval 轮询。
  // 仅当前 tab 的 query 启用 30s 轮询；refetchIntervalInBackground 默认 false，页面不可见时自动暂停。
  const unprocessed = useUnprocessedOrders({
    refetchInterval: () => (activeTab.value === 'pending' ? 30_000 : false),
  })
  const purchaseOrders = usePurchaseOrders({
    refetchInterval: () => (activeTab.value === 'active' ? 30_000 : false),
  })
  const completed = useCompletedOrders()
  const summary = useSummaryModal()
  const confirm = useConfirmDialog()

  const historyInitialized = ref(false)
  const isSubmitting = ref(false)

  function switchTab(tab: 'pending' | 'active' | 'history') {
    activeTab.value = tab
    if (tab === 'pending') {
      unprocessed.load()
    } else if (tab === 'active') {
      purchaseOrders.load()
    } else if (tab === 'history') {
      // 快速筛选 UI 已移除，无需 loadQuickFilters
      completed.load()
      historyInitialized.value = true
    }
  }

  const { detailVisible, detailOrder, handleViewDetail } = usePurchaseDetail()

  const actions = usePurchaseActions({
    unprocessed,
    purchaseOrders,
    completed,
    summary,
    confirm,
    queryClient,
    isSubmitting,
  })

  useWebSocket({
    onMessage: (data) => {
      if (data.type === 'order_created' || data.type === 'order_updated' || data.type === 'order_deleted' || data.type === 'purchase_order_created') {
        if (activeTab.value === 'pending') {
          unprocessed.load()
        } else if (activeTab.value === 'active') {
          purchaseOrders.load()
        }
      }
    },
    isActive: ordersTabActive,
  })

  // P1-10: 初始化只加载当前 tab（pending），active/history 按需加载。
  // tab badge 数量在切到对应 tab 时显示；F5 刷新命中 sessionStorage 持久化缓存时秒出。
  unprocessed.load()

  return {
    activeTab,
    isSubmitting,
    purchaseOrders,
    unprocessed,
    completed,
    summary,
    confirm,
    detailVisible,
    detailOrder,
    switchTab,
    handleViewDetail,
    ...actions,
  }
}
