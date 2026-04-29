<template>
  <div class="pc-container">
    <div class="pc-card pc-card-main">
      <div class="pc-card-header">
        <div class="pc-card-title-group">
          <div class="pc-icon-box pc-icon-blue">
            <i class="fas fa-store" />
          </div>
          <div>
            <h3>采购中心</h3>
            <small>用料计算 · 采购订单</small>
          </div>
        </div>
        <div class="pc-header-actions">
          <div class="pc-tabs">
            <button
              :class="['pc-tab-btn', activeTab === 'orders' ? 'active' : '']"
              @click="switchTab('orders')"
            >
              <i class="fas fa-file-invoice-dollar" /> 采购订单
              <span v-if="unprocessed.total > 0" :class="['notification-badge', activeTab === 'orders' ? 'notification-badge-active' : '']">{{ unprocessed.total }}</span>
            </button>
            <button
              :class="['pc-tab-btn', activeTab === 'history' ? 'active' : '']"
              @click="switchTab('history')"
            >
              <i class="fas fa-check-circle" /> 下单查询
            </button>
          </div>
        </div>
      </div>

      <div class="pc-body">
        <!-- 采购订单面板 -->
        <div v-show="activeTab === 'orders'" class="pc-tab-content">
          <!-- 审核订单 -->
          <PendingOrdersPanel
            :orders="unprocessed.orders"
            :loading="unprocessed.loading"
            :selected-ids="unprocessed.selectedIds"
            :selected-count="unprocessed.selectedIds.length"
            :valid-selected-count="unprocessed.validSelectedIds.length"
            :all-selected="unprocessed.allSelected"
            @toggle-all="unprocessed.toggleAll"
            @toggle-selection="unprocessed.toggleSelection"
            @one-click-generate="handleOneClickGenerate"
            @quick-generate="handleQuickGenerate"
          />

          <!-- 分隔线 -->
          <div class="pc-divider" />

          <!-- 采购中订单 -->
          <ActiveOrdersPanel
            :orders="purchaseOrders.orders"
            :loading="purchaseOrders.loading"
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
      :order-count="purchaseOrders.selectedIds.length"
      :supplier-groups="summary.supplierGroups"
      @close="summary.close"
      @toggle-edit-mode="summary.toggleEditMode"
      @save-edits="handleSaveFactoryEdits"
      @update-qty="handleUpdateFactoryQty"
      @export-factory="handleExportFactorySummary"
      @export-supplier="handleExportSupplierSummary"
      @print-factory="summary.printFactory"
      @print-supplier="summary.printSupplier"
    />
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, onUnmounted } from 'vue'
import { purchaseApi } from '@/api'

import PendingOrdersPanel from './components/PendingOrdersPanel.vue'
import ActiveOrdersPanel from './components/ActiveOrdersPanel.vue'
import CompletedOrdersPanel from './components/CompletedOrdersPanel.vue'
import OrderDetailModal from './components/OrderDetailModal.vue'
import SummaryModal from './components/SummaryModal.vue'
import UiConfirmDialog from '@/components/ui/UiConfirmDialog.vue'

import { usePurchaseOrders } from './composables/usePurchaseOrders'
import { useUnprocessedOrders } from './composables/useUnprocessedOrders'
import { useCompletedOrders } from './composables/useCompletedOrders'
import { useSummaryModal } from './composables/useSummaryModal'
import { useConfirmDialog } from '@/composables/useConfirmDialog'
import { useAutoRefresh } from './composables/useAutoRefresh'

// --- Composables ---
const purchaseOrders = usePurchaseOrders()
const unprocessed = useUnprocessedOrders()
const completed = useCompletedOrders()
const summary = useSummaryModal()
const confirm = useConfirmDialog()

// --- Tab ---
const activeTab = ref('orders')
const historyInitialized = ref(false)

function switchTab(tab: string) {
  activeTab.value = tab
  if (tab === 'orders') {
    unprocessed.load()
    purchaseOrders.load()
  } else if (tab === 'history') {
    if (!historyInitialized.value) {
      completed.loadQuickFilters()
      completed.load()
      historyInitialized.value = true
    } else {
      completed.load()
    }
  }
}

import { showToast } from '@/composables/useToast'

// --- Unprocessed handlers ---
async function handleOneClickGenerate() {
  const validIds = unprocessed.validSelectedIds
  if (validIds.length === 0) {
    showToast('请选择至少一个有BOM配置的订单', 'warning')
    return
  }
  const ok = await confirm.confirm(
    `确定要审核 ${validIds.length} 个订单吗？`,
    '审核通过后将自动计算物料用量并生成采购订单',
    'warning',
  )
  if (!ok) return
  try {
    const res = (await purchaseApi.oneClickGenerate({ order_ids: validIds })) as any
    if (res.success) {
      showToast(res.message || '审核成功', 'success')
      unprocessed.clearSelection()
      unprocessed.load()
      purchaseOrders.load()
    } else showToast(res.message || '审核失败', 'error')
  } catch (err: any) {
    showToast('审核失败: ' + (err.message || ''), 'error')
  }
}

async function handleQuickGenerate(orderId: number) {
  const ok = await confirm.confirm(`确定要审核此订单吗？`, '审核通过后将自动计算物料用量并生成采购订单', 'warning')
  if (!ok) return
  try {
    const res = (await purchaseApi.oneClickGenerate({ order_ids: [orderId] })) as any
    if (res.success) {
      showToast(res.message || '审核成功', 'success')
      unprocessed.load()
      purchaseOrders.load()
    } else showToast(res.message || '审核失败', 'error')
  } catch (err: any) {
    showToast('审核失败: ' + (err.message || ''), 'error')
  }
}

// --- Purchase order handlers ---
async function handleCompleteOrder(orderId: number) {
  const ok = await confirm.confirm('确认将此订单标记为下单完成？', '', 'warning')
  if (!ok) return
  try {
    await purchaseOrders.completeOrder(orderId)
    showToast('订单已完成下单', 'success')
  } catch (err: any) {
    showToast(err.message || '操作失败', 'error')
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
  } catch (err: any) {
    showToast(err.message || '操作失败', 'error')
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
  } catch (err: any) {
    showToast(err.message || '汇总失败', 'error')
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
  } catch (err: any) {
    showToast(err.message || '保存失败', 'error')
  }
}

function handleUpdateFactoryQty(gi: number | string, si: number | string, fi: number | string, value: string) {
  summary.updateFactoryQty(Number(gi), Number(si), Number(fi), parseFloat(value) || 0)
}

async function handleExportFactorySummary() {
  showToast('正在导出Excel...', 'info')
  try {
    const res = (await purchaseApi.exportCompleted({ format: 'factory-summary' })) as any
    if (res.success && res.html) {
      const bom = '\uFEFF'
      const blob = new Blob([bom + res.html], { type: 'application/vnd.ms-excel;charset=utf-8' })
      const url = URL.createObjectURL(blob)
      const link = document.createElement('a')
      link.href = url
      link.download = '工厂内部采购汇总.xls'
      document.body.appendChild(link)
      link.click()
      document.body.removeChild(link)
      URL.revokeObjectURL(url)
    }
  } catch {
    showToast('导出失败', 'error')
  }
}

async function handleExportSupplierSummary() {
  const ids = summary.orderIds.length > 0 ? [...summary.orderIds] : [...purchaseOrders.selectedIds]
  if (ids.length === 0) {
    showToast('请先选择订单', 'error')
    return
  }
  showToast('正在生成汇总文件，请稍候...', 'info')
  try {
    const { default: axiosInstance } = await import('@/api/request')
    const blob = (await axiosInstance.post('/purchase-center/orders/supplier-summary-export', { ids }, { responseType: 'blob' })) as unknown as Blob
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = blob.type.includes('zip') ? '供应商采购订单汇总.zip' : '供应商采购订单汇总.xlsx'
    document.body.appendChild(link)
    link.click()
    document.body.removeChild(link)
    URL.revokeObjectURL(url)
    showToast('导出成功', 'success')
  } catch {
    showToast('导出失败，请稍后重试', 'error')
  }
}

// --- Completed order handlers ---
const detailVisible = ref(false)
const detailOrder = ref<any>(null)

async function handleViewDetail(id: number) {
  try {
    const res = (await purchaseApi.orderDetail(id)) as any
    if (res.success) {
      detailOrder.value = res.order
      detailVisible.value = true
    } else showToast(res.message || '获取详情失败', 'error')
  } catch (err: any) {
    showToast(err.message || '获取详情失败', 'error')
  }
}

function handleFilterUpdate(payload: { key: string; value: string }) {
  ;(completed.filters as any)[payload.key] = payload.value
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
  } catch (err: any) {
    showToast(err.message || '导出失败', 'error')
  }
}

function handleCompletedPageChange(page: number) {
  completed.page = page
  completed.load()
}

// --- Auto refresh ---
const autoRefresh = useAutoRefresh(async () => {
  if (activeTab.value !== 'orders') return
  try {
    const res = (await purchaseApi.orders({ page: purchaseOrders.page, per_page: 15 })) as any
    if (res.success !== false && res.total !== purchaseOrders.total) {
      purchaseOrders.total = res.total || 0
      purchaseOrders.orders = res.orders || []
    }
    // 刷新完整的未处理订单列表，而不仅是 total
    const uRes = (await purchaseApi.unprocessedOrders()) as any
    if (uRes.success !== false) {
      unprocessed.total = uRes.total || 0
      if (uRes.orders) unprocessed.orders = uRes.orders
    }
  } catch {
    /* silent */
  }
})

// --- WebSocket 实时通知 ---
let ws: WebSocket | null = null
let wsReconnectTimer: ReturnType<typeof setTimeout> | null = null
let wsReconnectAttempts = 0
const WS_MAX_RECONNECT_ATTEMPTS = 20
const WS_RECONNECT_BASE_DELAY = 3000

function connectWebSocket() {
  if (wsReconnectAttempts >= WS_MAX_RECONNECT_ATTEMPTS) return
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
  const wsUrl = `${protocol}//${window.location.host}/ws/notifications`
  ws = new WebSocket(wsUrl)

  ws.onopen = () => {
    wsReconnectAttempts = 0
  }

  ws.onmessage = (event) => {
    try {
      const data = JSON.parse(event.data)
      if (data.type === 'order_created' || data.type === 'purchase_order_created') {
        // 收到新订单或新采购订单通知，立即刷新列表
        if (activeTab.value === 'orders') {
          unprocessed.load()
          purchaseOrders.load()
        }
      }
    } catch {
      /* ignore non-JSON messages */
    }
  }

  ws.onclose = () => {
    wsReconnectAttempts++
    if (wsReconnectAttempts < WS_MAX_RECONNECT_ATTEMPTS) {
      const delay = Math.min(WS_RECONNECT_BASE_DELAY * wsReconnectAttempts, 30000)
      wsReconnectTimer = setTimeout(connectWebSocket, delay)
    }
  }

  ws.onerror = () => {
    ws?.close()
  }
}

// --- Init ---
onMounted(() => {
  unprocessed.load()
  purchaseOrders.load()
  autoRefresh.start()
  connectWebSocket()
})

onUnmounted(() => {
  autoRefresh.stop()
  if (wsReconnectTimer) clearTimeout(wsReconnectTimer)
  ws?.close()
  ws = null
})
</script>

<style scoped>
/* === Layout === */
.pc-container {
  padding: 12px;
  margin: 0 auto;
  height: 100%;
  display: flex;
  flex-direction: column;
  box-sizing: border-box;
}

/* === Main Card === */
.pc-card {
  background: white;
  border-radius: 14px;
  border: 1px solid var(--color-border-light, #e2e8f0);
  box-shadow: 0 1px 3px rgba(0,0,0,0.04), 0 4px 12px rgba(0,0,0,0.06);
  transition: all 0.4s cubic-bezier(0.4, 0, 0.2, 1);
  overflow: hidden;
}

.pc-card:hover {
  box-shadow: 0 4px 12px rgba(0,0,0,0.08), 0 16px 48px rgba(0,0,0,0.12);
  transform: translateY(-2px);
}

.pc-card-main {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-height: 0;
}

.pc-card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 16px 24px;
  border-bottom: 1px solid var(--color-border-light, #f1f5f9);
  flex-shrink: 0;
}

.pc-card-title-group {
  display: flex;
  align-items: center;
  gap: 14px;
}

.pc-card-title-group h3 {
  font-size: 17px;
  font-weight: 700;
  color: var(--color-text);
  margin: 0;
}

.pc-card-title-group small {
  font-size: 12px;
  color: var(--color-text-secondary);
  display: block;
  margin-top: 2px;
}

/* === Icon Box === */
.pc-icon-box {
  width: 46px;
  height: 46px;
  border-radius: 13px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 19px;
  flex-shrink: 0;
}

.pc-icon-blue {
  background: linear-gradient(135deg, var(--color-primary-100), var(--color-primary-200));
  color: var(--color-primary-700);
}

/* === Header Actions === */
.pc-header-actions {
  display: flex;
  align-items: center;
  gap: 8px;
}

/* === Tabs === */
.pc-tabs {
  display: flex;
  gap: 4px;
  background: var(--color-surface, #f1f5f9);
  padding: 4px;
  border-radius: 11px;
}

.pc-tab-btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 8px 18px;
  border: none;
  border-radius: 8px;
  font-size: 13px;
  font-weight: 600;
  color: var(--color-text-secondary);
  background: transparent;
  cursor: pointer;
  transition: all 0.3s ease;
}

.pc-tab-btn:hover {
  color: var(--color-primary-600);
  background: rgba(255, 255, 255, 0.6);
}

.pc-tab-btn.active {
  background: white;
  color: var(--color-primary-600);
  box-shadow: 0 1px 4px rgba(0, 0, 0, 0.08);
}

/* === Body === */
.pc-body {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
}

.pc-tab-content {
  padding: 0;
}

.pc-divider {
  height: 1px;
  margin: 0 24px;
  background: linear-gradient(to right, transparent, var(--color-primary-300, #93c5fd), transparent);
  opacity: 0.5;
}
</style>
