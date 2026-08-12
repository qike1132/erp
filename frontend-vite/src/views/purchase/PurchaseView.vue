<template>
  <div class="pc-container">
    <div class="page-card page-card-main">
      <div class="page-card-header">
        <div class="pc-header-left">
          <HeaderTabs />
        </div>
        <div class="pc-header-right">
          <div class="pc-tab-group" role="tablist">
            <button
              role="tab"
              :aria-selected="activeTab === 'pending'"
              :class="['pc-tab-btn', { active: activeTab === 'pending' }]"
              @click="switchTab('pending')"
            >
              待审核订单
              <span v-if="unprocessed.total > 0" class="pc-tab-badge">{{ unprocessed.total }}</span>
            </button>
            <button
              role="tab"
              :aria-selected="activeTab === 'active'"
              :class="['pc-tab-btn', { active: activeTab === 'active' }]"
              @click="switchTab('active')"
            >
              待生产订单
              <span v-if="purchaseOrders.total > 0" class="pc-tab-badge">{{ purchaseOrders.total }}</span>
            </button>
            <button
              role="tab"
              :aria-selected="activeTab === 'history'"
              :class="['pc-tab-btn', { active: activeTab === 'history' }]"
              @click="switchTab('history')"
            >
              下单查询
            </button>
          </div>
        </div>
      </div>

      <div class="page-card-body">
        <!-- 待审核订单面板 -->
        <div v-show="activeTab === 'pending'" class="pc-tab-content">
          <PendingOrdersPanel
            :orders="unprocessed.orders"
            :loading="unprocessed.loading"
            :fetching="unprocessed.fetching"
            :total="unprocessed.total"
            :current-page="unprocessed.currentPage"
            :total-pages="unprocessed.totalPages"
            :selected-composite-ids="unprocessed.selectedCompositeIds"
            :selected-count="unprocessed.selectedCompositeIds.length"
            :valid-selected-count="unprocessed.validSelectedCompositeIds.length"
            :all-selected="unprocessed.allSelected"
            :submitting="isSubmitting"
            @toggle-all="unprocessed.toggleAll"
            @toggle-selection="unprocessed.toggleSelection"
            @one-click-generate="handleOneClickGenerate"
            @quick-generate="handleQuickGenerate"
            @no-bom-error="handleNoBomError"
            @change-page="unprocessed.load"
          />
        </div>

        <!-- 待下订单面板 -->
        <div v-show="activeTab === 'active'" class="pc-tab-content">
          <ActiveOrdersPanel
            :orders="purchaseOrders.orders"
            :loading="purchaseOrders.loading"
            :fetching="purchaseOrders.fetching"
            :total="purchaseOrders.total"
            :current-page="purchaseOrders.page"
            :total-pages="purchaseOrders.pages"
            :selected-ids="purchaseOrders.selectedIds"
            :all-selected="purchaseOrders.allSelected"
            @toggle-all="purchaseOrders.toggleAll"
            @toggle-selection="purchaseOrders.toggleSelection"
            @summary="handleSummary"
            @batch-complete="handleBatchComplete"
            @complete-order="handleCompleteOrder"
            @update:current-page="handleOrderPageChange"
          />
        </div>

        <!-- 下单查询面板 -->
        <div v-show="activeTab === 'history'" class="pc-tab-content">
          <CompletedOrdersPanel
            v-model:filter-expanded="completed.filterExpanded"
            :orders="completed.orders"
            :loading="completed.loading"
            :fetching="completed.fetching"
            :total="completed.total"
            :current-page="completed.page"
            :total-pages="completed.totalPages"
            :filters="completed.filters"
            :quick-filters="completed.quickFilters"
            :current-quick-filter-id="completed.currentQuickFilterId"
            @update-filter="handleFilterUpdate"
            @reset-filters="completed.resetFilters"
            @search="handleCompletedSearch"
            @export="handleExport"
            @apply-quick-filter="completed.applyQuickFilter"
            @view-detail="handleViewDetail"
            @update:current-page="handleCompletedPageChange"
          />
        </div>
      </div>
    </div>

    <!-- Confirm Dialog -->
    <UiConfirmDialog
      :open="confirm.open"
      :text="confirm.text"
      :sub="confirm.sub"
      :type="confirm.type"
      @confirm="confirm.onConfirm"
      @cancel="confirm.onCancel"
    />

    <!-- Order Detail Modal -->
    <OrderDetailModal :open="detailVisible" :order="detailOrder" @close="detailVisible = false" />

    <!-- Summary Modal -->
    <SummaryModal
      :open="summary.open"
      :factory-data="summary.factoryData"
      :supplier-data="summary.supplierData"
      :edit-mode="summary.editMode"
      :loss-rate="summary.lossRate"
      :order-count="purchaseOrders.selectedIds.length"
      :supplier-groups="summary.supplierGroups"
      @close="summary.close"
      @toggle-edit-mode="summary.toggleEditMode"
      @save-edits="handleSaveFactoryEdits"
      @update-qty="handleUpdateFactoryQty"
      @apply-loss-rate="summary.applyLossRate"
      @export-factory="summary.exportFactory"
      @export-supplier="summary.exportSupplier"
      @print-factory="summary.printFactory"
      @print-supplier="summary.printSupplier"
    />
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onBeforeUnmount } from 'vue'
import { useQueryClient } from '@tanstack/vue-query'
import { purchaseApi } from '@/api'
import type { ApiResponse, PurchaseOrder, UnprocessedOrder } from '@/types'

import PendingOrdersPanel from './components/PendingOrdersPanel.vue'
import ActiveOrdersPanel from './components/ActiveOrdersPanel.vue'
import CompletedOrdersPanel from './components/CompletedOrdersPanel.vue'
import OrderDetailModal from './components/OrderDetailModal.vue'
import SummaryModal from './components/SummaryModal.vue'
import UiConfirmDialog from '@/components/ui/UiConfirmDialog.vue'
import HeaderTabs from '@/layouts/components/HeaderTabs.vue'

import { usePurchaseOrders } from './composables/usePurchaseOrders'
import { useUnprocessedOrders } from './composables/useUnprocessedOrders'
import { useCompletedOrders } from './composables/useCompletedOrders'
import { useSummaryModal } from './composables/useSummaryModal'
import { useConfirmDialog } from '@/composables/useConfirmDialog'
import { useAutoRefresh } from './composables/useAutoRefresh'
import { useWebSocket } from '@/composables/useWebSocket'
import { showToast } from '@/composables/useToast'

// --- Composables ---
const queryClient = useQueryClient()
const purchaseOrders = usePurchaseOrders()
const unprocessed = useUnprocessedOrders()
const completed = useCompletedOrders()
const summary = useSummaryModal()
const confirm = useConfirmDialog()

// --- Tab ---
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

// --- Unprocessed handlers ---
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
  // 提前锁定，防止 confirm 等待期间重复触发
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
  // 提前锁定，防止 confirm 等待期间重复触发
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

// --- Purchase order handlers ---
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

// --- Summary handlers ---
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

// --- Completed order handlers ---
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

async function handleExport() {
  showToast('正在导出...', 'info')
  try {
    const ok = await completed.exportOrders()
    if (ok) showToast('已导出 下单查询汇总.xls', 'success')
  } catch (err: unknown) {
    showToast((err as Error).message || '导出失败', 'error')
  }
}

function handleCompletedPageChange(page: number) {
  completed.page = page
  completed.load()
}

// --- Auto refresh ---
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
      // 与 usePurchaseOrders.load() 保持一致：仅刷新 pending/confirmed 的"待下"订单
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

// --- WebSocket notifications ---
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

// --- Init ---
Promise.all([unprocessed.load(), purchaseOrders.load()])
autoRefresh.start()

onBeforeUnmount(() => {
  autoRefresh.stop()
})
</script>

<style scoped>
/* === Layout === */
/* 与 DashboardView 的 .dashboard 保持完全一致：
   - width: 100% 确保撑满主区宽度
   - height: 100% + display: flex 让 page-card-main 撑满主区高度
   - padding/margin/box-sizing 与 dashboard 严格对齐 */
.pc-container {
  width: 100%;
  height: 100%;
  padding: 0;
  margin: 0;
  display: flex;
  flex-direction: column;
  box-sizing: border-box;
}

/* === Main Card === */
/* 卡片样式已迁移到全局 .page-card 系列（src/styles/app.css）
   与 DashboardView 共用同一 .page-card.page-card-main，
   确保 border-radius(18px)、box-shadow、border 视觉参数严格一致 */

.pc-card-header :deep(.ht-bar) {
  width: auto;
  margin: 0;
}

/* === Header Actions === */
.pc-header-actions {
  display: flex;
  align-items: center;
  gap: 8px;
}

/* === Tabs === */
.pc-tab-group {
  display: inline-flex;
  gap: 4px;
  padding: 4px;
  border-radius: 12px;
  background: white;
  border: 1px solid var(--color-border-light);
  box-shadow: 0 1px 3px rgba(0,0,0,0.04), 0 4px 12px rgba(0,0,0,0.06);
}

.pc-tab-btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 8px 14px;
  border: none;
  border-radius: 9px;
  font-size: 13px;
  font-weight: 600;
  color: var(--color-text-secondary);
  background: transparent;
  cursor: pointer;
  transition: background 0.3s ease, color 0.3s ease, box-shadow 0.3s ease, transform 0.3s ease;
  white-space: nowrap;
}

.pc-tab-btn:hover {
  background: var(--color-primary-50);
  color: var(--color-primary-600);
  box-shadow: 0 4px 12px rgba(0,0,0,0.08);
  transform: translateY(-1px);
}

.pc-tab-btn.active {
  background: linear-gradient(135deg, var(--color-primary-50), var(--color-primary-100));
  color: var(--color-primary-700);
  box-shadow: 0 4px 12px rgba(0,0,0,0.08), 0 2px 8px rgba(91, 141, 239, 0.2);
  transform: translateY(-1px);
}

.pc-tab-badge {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 18px;
  height: 18px;
  padding: 0 5px;
  background: var(--color-danger-500);
  color: white;
  font-size: 10px;
  font-weight: 700;
  border-radius: 9px;
  line-height: 1;
}

/* === Body === */
/* 卡片主体样式已迁移到全局 .page-card-body（src/styles/app.css） */

.pc-tab-content {
  padding: 0;
}
</style>
