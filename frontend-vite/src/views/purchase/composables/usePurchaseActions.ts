import { ref } from 'vue'
import type { QueryClient } from '@tanstack/vue-query'
import { showToast } from '@/composables/useToast'
import { useExport } from '@/composables/useExport'
import { usePurchaseOrders } from './usePurchaseOrders'
import { useCompletedOrders, type CompletedOrderFilters } from './useCompletedOrders'
import { useSummaryModal } from './useSummaryModal'
import { useConfirmDialog } from '@/composables/useConfirmDialog'

/**
 * usePurchaseActions — 采购页面业务动作（完成/汇总/筛选/导出）
 *
 * 从 usePurchaseHandlers 拆出：接收已初始化的数据 composable 与共享状态，
 * 返回所有事件处理函数。纯逻辑可独立测试，不包含数据获取/实时刷新编排。
 *
 * 注：采购订单已改为自动生成，原先的「一键审核 / 单条审核」动作（handleOneClickGenerate
 * / handleQuickGenerate / handleNoBomError）已移除。
 */
interface PurchaseActionDeps {
  purchaseOrders: ReturnType<typeof usePurchaseOrders>
  completed: ReturnType<typeof useCompletedOrders>
  summary: ReturnType<typeof useSummaryModal>
  confirm: ReturnType<typeof useConfirmDialog>
  queryClient: QueryClient
}

export function usePurchaseActions(deps: PurchaseActionDeps) {
  const { purchaseOrders, completed, summary, confirm, queryClient } = deps

  /** 汇总下单请求中（弹窗要等接口返回才 open，用于按钮 loading 态） */
  const isSummarizing = ref(false)

  async function handleCompleteOrder(orderId: number) {
    const ok = await confirm.confirm('确认将此订单标记为下单完成？', '', 'warning')
    if (!ok) return
    try {
      // 损耗率仅在其被用户交互过时随动作提交；未交互则不发送，避免用 0 覆盖已存率
      await purchaseOrders.completeOrder(orderId, summary.lossRateTouched ? summary.lossRate : undefined)
      showToast('订单已完成下单', 'success')
      queryClient.invalidateQueries({ queryKey: ['orders-list'] })
    } catch (err: unknown) {
      showToast((err as Error).message || '操作失败', 'error')
    }
  }

  async function handleBatchComplete() {
    if (purchaseOrders.selectedIds.length === 0) {
      showToast('请先选择订单', 'error')
      return
    }
    const ok = await confirm.confirm(
      `确认将选中的 ${purchaseOrders.selectedIds.length} 个订单标记为下单完成？`,
      '',
      'warning',
    )
    if (!ok) return
    try {
      const count = await purchaseOrders.batchComplete(summary.lossRateTouched ? summary.lossRate : undefined)
      showToast(`成功完成 ${count} 个订单`, 'success')
      queryClient.invalidateQueries({ queryKey: ['orders-list'] })
    } catch (err: unknown) {
      showToast((err as Error).message || '操作失败', 'error')
    }
  }

  async function handleSummary() {
    if (purchaseOrders.selectedIds.length === 0) {
      showToast('请先选择订单', 'error')
      return
    }
    // 订单时间 = 选中订单中最晚的下单时间（create_time，回退 order_date）。
    // 时间字符串格式为 'YYYY-MM-DD HH:mm:ss' / 'YYYY-MM-DD'，字典序升序排序后取末位即最晚。
    const times = purchaseOrders.orders
      .filter((o) => purchaseOrders.selectedIds.includes(o.id))
      .map((o) => o.create_time || o.order_date || '')
      .filter(Boolean)
      .sort()
    const orderTime = times.length > 0 ? times[times.length - 1]! : ''
    // 弹窗要等两个汇总接口都返回才 open（useSummaryModal.openSummary），
    // 期间无任何界面反馈，故用按钮 loading 态顶替原先的「正在汇总订单数据...」气泡。
    isSummarizing.value = true
    try {
      await summary.openSummary([...purchaseOrders.selectedIds], orderTime)
    } catch (err: unknown) {
      showToast((err as Error).message || '汇总失败', 'error')
    } finally {
      isSummarizing.value = false
    }
  }

  function handleOrderPageChange(page: number) {
    purchaseOrders.page = page
    // P3-17: 页码变更由 Vue Query queryKey 自动触发 fetch，不 invalidate 以保留 prefetch 缓存。
  }

  async function handleSaveFactoryEdits() {
    try {
      await summary.saveFactoryEdits()
      showToast('修改已保存', 'success')
    } catch (err: unknown) {
      showToast((err as Error).message || '保存失败', 'error')
    }
  }

  function handleUpdateFactoryQty(gi: number | string, si: number | string, fi: number | string, value: string) {
    summary.updateFactoryQty(Number(gi), Number(si), Number(fi), parseFloat(value) || 0)
  }

  /**
   * 非编辑态输入损耗率 → 自动落库。
   *
   * 防抖（300ms）保留在 SummaryModal.vue 组件层；此处只负责调用 composable 的落库
   * 逻辑，并在失败时通过 toast 明确告知用户（不允许静默吞掉），本地展示保持可用。
   */
  async function handleApplyLossRate(rate: number) {
    try {
      await summary.applyLossRateAndSave(rate)
    } catch (err: unknown) {
      showToast((err as Error).message || '损耗率保存失败', 'error')
    }
  }

  /**
   * 单个布料行的损耗率输入 → 自动落库到该行对应的采购单明细。
   * 防抖保留在 SummaryModal.vue；此处只负责调用 composable 并在失败时 toast。
   */
  async function handleApplyFabricLossRate(gi: number, si: number, fi: number, rate: number) {
    try {
      await summary.applyFabricLossRateAndSave(gi, si, fi, rate)
    } catch (err: unknown) {
      showToast((err as Error).message || '布料损耗率保存失败', 'error')
    }
  }

  function handleCompletedPageChange(page: number) {
    completed.page = page
    // 页码变更由 Vue Query queryKey 自动触发 fetch，不 invalidate 以保留 prefetch 缓存。
  }

  /** 移除单个筛选条件（来自条件胶囊的 ✕），随后回到第 1 页重新查询 */
  function handleRemoveCompletedFilter(key: keyof CompletedOrderFilters) {
    completed.draft[key] = ''
    completed.filters[key] = ''
    completed.page = 1
  }

  // 导出：复用统一 useExport，自动处理"正在导出/成功/失败"提示与并发防重
  const { exporting, runExport } = useExport({ success: '已导出 记录查询汇总.xls' })

  function handleExport() {
    runExport(() => completed.exportOrders())
  }

  return {
    handleCompleteOrder,
    handleBatchComplete,
    handleSummary,
    handleOrderPageChange,
    handleSaveFactoryEdits,
    handleUpdateFactoryQty,
    handleApplyLossRate,
    handleApplyFabricLossRate,
    handleCompletedPageChange,
    handleRemoveCompletedFilter,
    handleExport,
    exporting,
    isSummarizing,
  }
}
