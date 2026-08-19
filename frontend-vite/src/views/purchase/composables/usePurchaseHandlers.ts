import { ref, computed, onBeforeUnmount } from 'vue'
import { useQueryClient } from '@tanstack/vue-query'
import { purchaseApi } from '@/api'
import type { ApiResponse, PurchaseOrder, UnprocessedOrder } from '@/types'
import { usePurchaseOrders } from './usePurchaseOrders'
import { useUnprocessedOrders } from './useUnprocessedOrders'
import { useCompletedOrders } from './useCompletedOrders'
import { useSummaryModal } from './useSummaryModal'
import { useConfirmDialog } from '@/composables/useConfirmDialog'
import { useAutoRefresh } from './useAutoRefresh'
import { useWebSocket } from '@/composables/useWebSocket'
import { showToast } from '@/composables/useToast'
import { useExport } from '@/composables/useExport'

export function usePurchaseHandlers() {
  const queryClient = useQueryClient()
  const purchaseOrders = usePurchaseOrders()
  const unprocessed = useUnprocessedOrders()
  const completed = useCompletedOrders()
  const summary = useSummaryModal()
  const confirm = useConfirmDialog()

  const activeTab = ref<'pending' | 'active' | 'history'>('pending')
  const ordersTabActive = computed(() => activeTab.value === 'pending' || activeTab.value === 'active')
  const historyInitialized = ref(false)
  const isSubmitting = ref(false)

  function switchTab(tab: 'pending' | 'active' | 'history') {
    activeTab.value = tab
    if (tab === 'pending') {
      unprocessed.load()
    } else if (tab === 'active') {
      purchaseOrders.load()
    } else if (tab === 'history') {
      if (!historyInitialized.value) {
        Promise.all([completed.loadQuickFilters(), completed.load()])
        historyInitialized.value = true
      } else {
        completed.load()
      }
    }
  }

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
    showToast('正在汇总订单数据...', 'info')
    try {
      await summary.openSummary([...purchaseOrders.selectedIds])
    } catch (err: unknown) {
      showToast((err as Error).message || '汇总失败', 'error')
    }
  }

  function handleOrderPageChange(page: number) {
    purchaseOrders.page = page
    purchaseOrders.load()
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

  function handleFilterUpdate(payload: { key: string; value: string }) {
    ;(completed.filters as Record<string, string>)[payload.key] = payload.value
  }

  function handleCompletedSearch() {
    completed.page = 1
    completed.load()
  }

  const { runExport } = useExport({ success: '已导出 下单查询汇总.xls' })

  function handleExport() {
    runExport(async () => {
      const ok = await completed.exportOrders()
      if (!ok) throw new Error('导出失败')
    })
  }

  function handleCompletedPageChange(page: number) {
    completed.page = page
    completed.load()
  }

  const autoRefresh = useAutoRefresh(async () => {
    if (activeTab.value === 'pending') {
      try {
        const uRes = await purchaseApi.unprocessedOrders({ page: unprocessed.currentPage, per_page: unprocessed.perPage })
        if (uRes) {
          unprocessed.total = uRes.total || 0
          if (uRes.orders) unprocessed.orders = (uRes.orders as UnprocessedOrder[])
          unprocessed.totalPages = uRes.pages || Math.max(1, Math.ceil((uRes.total || 0) / unprocessed.perPage))
          unprocessed.currentPage = uRes.current_page || unprocessed.currentPage
        }
      } catch {
        /* silent */
      }
    } else if (activeTab.value === 'active') {
      try {
        const res = await purchaseApi.orders({ page: purchaseOrders.page, per_page: 15, status: 'pending,confirmed' })
        if (res.total !== purchaseOrders.total) {
          purchaseOrders.total = res.total || 0
          purchaseOrders.orders = (res.orders || []) as PurchaseOrder[]
        }
      } catch {
        /* silent */
      }
    }
  })

  useWebSocket({
    onMessage: (data) => {
      if (data.type === 'order_created' || data.type === 'order_updated' || data.type === 'order_deleted' || data.type === 'purchase_order_created') {
        if (activeTab.value === 'pending') {
          unprocessed.load()
          autoRefresh.resetTimer()
        } else if (activeTab.value === 'active') {
          purchaseOrders.load()
          autoRefresh.resetTimer()
        }
      }
    },
    isActive: ordersTabActive,
  })

  Promise.all([unprocessed.load(), purchaseOrders.load()])
  autoRefresh.start()

  onBeforeUnmount(() => {
    autoRefresh.stop()
  })

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
    handleOneClickGenerate,
    handleQuickGenerate,
    handleNoBomError,
    handleCompleteOrder,
    handleBatchComplete,
    handleSummary,
    handleOrderPageChange,
    handleSaveFactoryEdits,
    handleUpdateFactoryQty,
    handleViewDetail,
    handleFilterUpdate,
    handleCompletedSearch,
    handleExport,
    handleCompletedPageChange,
  }
}