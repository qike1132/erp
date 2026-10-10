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
 *  - 编排 tab 切换与按需加载
 *  - 编排实时刷新：Vue Query refetchInterval + WebSocket
 *  - 聚合子模块返回值：usePurchaseDetail（详情）+ usePurchaseActions（业务动作）
 *
 * 采购订单已改为**自动生成**（订单/备货创建后由后端 ARQ 任务生成，无需人工审核）：
 * 页面只剩「待生产订单」「记录查询」两个 tab；`unprocessed` 仅用于「待生成」只读区块
 * （未配置BOM的订单在此展示，配好 BOM 后自动生成）。
 */
export function usePurchaseHandlers() {
  const queryClient = useQueryClient()
  const activeTab = ref<'active' | 'history'>('active')
  const ordersTabActive = computed(() => activeTab.value === 'active')

  // 实时刷新用 Vue Query refetchInterval 替代 setInterval 轮询。
  // unprocessed 常驻 30s：待生产 tab 的「待生成」区块依赖它，实时反映新单 / BOM 补齐。
  const unprocessed = useUnprocessedOrders({
    refetchInterval: () => 30_000,
  })
  const purchaseOrders = usePurchaseOrders({
    refetchInterval: () => (activeTab.value === 'active' ? 30_000 : false),
  })
  const completed = useCompletedOrders()
  const summary = useSummaryModal()
  const confirm = useConfirmDialog()

  function switchTab(tab: 'active' | 'history') {
    activeTab.value = tab
    if (tab === 'active') {
      purchaseOrders.load()
    } else {
      // 记录查询按当前筛选条件重新拉取最新数据
      completed.refresh()
    }
  }

  const { detailVisible, detailOrder, handleViewDetail } = usePurchaseDetail()

  const actions = usePurchaseActions({
    purchaseOrders,
    completed,
    summary,
    confirm,
    queryClient,
  })

  useWebSocket({
    onMessage: (data) => {
      if (data.type === 'order_created' || data.type === 'order_updated' || data.type === 'order_deleted' || data.type === 'purchase_order_created') {
        if (activeTab.value === 'active') {
          // 新单/删除/BOM 变化后，待生成区块与待生产列表都要刷新
          unprocessed.load()
          purchaseOrders.load()
        }
      }
    },
    isActive: ordersTabActive,
  })

  // 初始化加载默认 tab（待生产订单）+ 待生成区块的数据源。
  // tab badge 数量在切到对应 tab 时显示；F5 刷新命中 sessionStorage 持久化缓存时秒出。
  unprocessed.load()
  purchaseOrders.load()

  return {
    activeTab,
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
