import type { Ref } from 'vue'
import type { QueryClient } from '@tanstack/vue-query'
import { purchaseApi } from '@/api'
import { showToast } from '@/composables/useToast'
import { useExport } from '@/composables/useExport'
import type { UnprocessedOrder } from '@/types'
import { useUnprocessedOrders } from './useUnprocessedOrders'
import { usePurchaseOrders } from './usePurchaseOrders'
import { useCompletedOrders, type CompletedOrderFilters } from './useCompletedOrders'
import { useSummaryModal } from './useSummaryModal'
import { useConfirmDialog } from '@/composables/useConfirmDialog'

/**
 * usePurchaseActions — 采购页面业务动作（审核/完成/汇总/筛选/导出）
 *
 * 从 usePurchaseHandlers 拆出：接收已初始化的数据 composable 与共享状态，
 * 返回所有事件处理函数。纯逻辑可独立测试，不包含数据获取/实时刷新编排。
 */
interface PurchaseActionDeps {
  unprocessed: ReturnType<typeof useUnprocessedOrders>
  purchaseOrders: ReturnType<typeof usePurchaseOrders>
  completed: ReturnType<typeof useCompletedOrders>
  summary: ReturnType<typeof useSummaryModal>
  confirm: ReturnType<typeof useConfirmDialog>
  queryClient: QueryClient
  isSubmitting: Ref<boolean>
}

export function usePurchaseActions(deps: PurchaseActionDeps) {
  const { unprocessed, purchaseOrders, completed, summary, confirm, queryClient, isSubmitting } = deps

  async function handleOneClickGenerate() {
    if (isSubmitting.value) return
    const validIds = unprocessed.validSelectedCompositeIds
    const allSelectedIds = unprocessed.selectedCompositeIds
    if (validIds.length === 0) {
      showToast('请选择至少一个有BOM配置的订单', 'warning')
      return
    }
    const noBomOrders = unprocessed.orders.filter(
      (o: UnprocessedOrder) => allSelectedIds.includes(o.composite_id) && !o.has_bom,
    )
    const skippedCount = noBomOrders.length
    isSubmitting.value = true
    const ok = await confirm.confirm(
      `确定要审核 ${validIds.length} 个订单吗？`,
      skippedCount > 0
        ? `其中 ${skippedCount} 个订单因未配置BOM被排除（${noBomOrders.map((o) => o.order_no).join('、')}），审核通过后将自动计算物料用量并生成采购订单`
        : '审核通过后将自动计算物料用量并生成采购订单',
      'warning',
    )
    if (!ok) {
      isSubmitting.value = false
      return
    }
    try {
      const res = await purchaseApi.oneClickGenerate({ composite_ids: validIds })
      if (res.success) {
        showToast(res.message || '审核成功', 'success')
        unprocessed.clearSelection()
        unprocessed.load()
        purchaseOrders.load()
        queryClient.invalidateQueries({ queryKey: ['orders-list'] })
      } else showToast(res.message || '审核失败', 'error')
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } }; message?: string })?.response?.data?.detail || (err as Error).message || ''
      showToast('审核失败: ' + detail, 'error')
    } finally {
      isSubmitting.value = false
    }
  }

  async function handleQuickGenerate(compositeId: string) {
    if (isSubmitting.value) return
    const order = unprocessed.orders.find((o: UnprocessedOrder) => o.composite_id === compositeId)
    if (!order?.has_bom) {
      showToast(`订单 ${order?.order_no || ''}无法审核：该产品未配置BOM表`, 'error')
      return
    }
    isSubmitting.value = true
    const ok = await confirm.confirm(`确定要审核此订单吗？`, '审核通过后将自动计算物料用量并生成采购订单', 'warning')
    if (!ok) {
      isSubmitting.value = false
      return
    }
    try {
      const res = await purchaseApi.oneClickGenerate({ composite_ids: [compositeId] })
      if (res.success) {
        showToast(res.message || '审核成功', 'success')
        unprocessed.load()
        purchaseOrders.load()
        queryClient.invalidateQueries({ queryKey: ['orders-list'] })
      } else showToast(res.message || '审核失败', 'error')
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } }; message?: string })?.response?.data?.detail || (err as Error).message || ''
      showToast('审核失败: ' + detail, 'error')
    } finally {
      isSubmitting.value = false
    }
  }

  function handleNoBomError(order: UnprocessedOrder) {
    const noBomItems = (order.items || []).filter((it) => it.has_bom === false)
    if ((order.sku_count || 1) > 1 && noBomItems.length > 0) {
      const names = noBomItems.map((it) => it.product_name).join('、')
      showToast(`订单 ${order.order_no || ''}无法审核：以下 SKU 未配置BOM：${names}`, 'error', { duration: 6000 })
    } else {
      showToast(`订单 ${order.order_no || ''}无法审核：该产品未配置BOM表`, 'error')
    }
  }

  async function handleCompleteOrder(orderId: number) {
    const ok = await confirm.confirm('确认将此订单标记为下单完成？', '', 'warning')
    if (!ok) return
    try {
      await purchaseOrders.completeOrder(orderId)
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
      const count = await purchaseOrders.batchComplete()
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
    showToast('正在汇总订单数据...', 'info')
    try {
      await summary.openSummary([...purchaseOrders.selectedIds], orderTime)
    } catch (err: unknown) {
      showToast((err as Error).message || '汇总失败', 'error')
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
  const { exporting, runExport } = useExport({ success: '已导出 下单查询汇总.xls' })

  function handleExport() {
    runExport(() => completed.exportOrders())
  }

  return {
    handleOneClickGenerate,
    handleQuickGenerate,
    handleNoBomError,
    handleCompleteOrder,
    handleBatchComplete,
    handleSummary,
    handleOrderPageChange,
    handleSaveFactoryEdits,
    handleUpdateFactoryQty,
    handleCompletedPageChange,
    handleRemoveCompletedFilter,
    handleExport,
    exporting,
  }
}
