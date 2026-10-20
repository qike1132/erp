<template>
  <div class="mr-container">
    <div class="page-card page-card-main">
      <!-- Unified Header + Tabs -->
      <div class="mr-top-bar">
        <div class="mr-tabs">
          <button :class="['mr-tab-btn', { active: activeTab === 'progress' }]" aria-label="来料进度" @click="switchToProgress">
            来料进度 <span v-if="progressCount > 0" :class="['notification-badge', activeTab === 'progress' ? 'notification-badge-active' : '']">{{ progressCount }}</span>
          </button>
          <button :class="['mr-tab-btn', { active: activeTab === 'history' }]" aria-label="历史查询" @click="switchToHistory">
            历史查询
          </button>
          <button v-if="canManage && activeTab === 'history'" class="mr-btn mr-btn-ghost" title="导出历史数据" aria-label="导出" @click="exportHistory"><FontAwesomeIcon icon="file-export" /> 导出</button>
        </div>
      </div>

      <!-- 来料进度单行工具条：搜索 · KPI 四格 · 导出（与 /stock 同构） -->
      <MaterialToolbar
        v-if="activeTab === 'progress'"
        v-model:search="searchKeyword"
        :stats="stats"
        :has-data="progressOrderRows.length > 0"
        :can-export="canManage"
        @export="exportData"
      />

      <!-- ========== 来料进度（方案A改版：同单合并·默认展开·分段堆叠条） ========== -->
      <ProgressTab
        v-if="activeTab === 'progress'"
        :filtered-rows="filteredOrderRows"
        :progress-order-rows="progressOrderRows"
        :p-is-loading="pIsLoading"
        :p-is-fetching="pIsFetching"
        :p-per-page="pPerPage"
        :p-pages="pPages"
        :p-count="progressCount"
        :p-page="pPage"
        :show-search-empty="showSearchEmpty"
        @page="onProgressPageChange"
        @view-supplier="viewSupplierDetail"
      />

      <!-- ========== 历史查询（子组件化，模板与列定义原样搬移） ========== -->
      <HistoryTab
        v-if="activeTab === 'history'"
        :h-registrations="hRegistrations"
        :h-is-loading="hIsLoading"
        :h-is-fetching="hIsFetching"
        :h-per-page="hPerPage"
        :h-pages="hPages"
        :h-count="historyCount"
        :h-page="hPage"
        @page="onHistoryPageChange"
        @view-detail="viewDetail"
      />

      <!-- Detail Dialog -->
      <MaterialDetailDialog
        v-model:open="showDetailDialog"
        :detail-data="detailData"
        :can-manage="canManage"
        @open-receive="openReceive"
      />

      <!-- Supplier Detail Dialog -->
      <SupplierDialog
        v-model:open="showSupplierDialog"
        :supplier-detail="supplierDetail"
        :supplier-detail-order-no="supplierDetailOrderNo"
        :can-manage="canManage"
        @open-receive-by-sub-items="openReceiveBySubItems"
      />

      <!-- Receive Dialog -->
      <ReceiveDialog
        v-model:open="showReceiveDialog"
        :item="receiveItem"
        @submit="submitReceive"
      />

      <div :class="['mr-toast', { show: toastMsg }, toastType]"><FontAwesomeIcon :icon="toastIcon" /> {{ toastMsg }}</div>
    </div>
  </div>
</template>

<script setup lang="ts">
/**
 * MaterialView.vue — 来料进度管理页面
 *
 * 职责：
 * - 来料进度标签页：展示供应商-订单-物料层级的收货进度（ProgressTab）
 * - 历史查询标签页：查询已完成的来料登记记录（HistoryTab）
 * - 收货登记、供应商详情、数据导出
 * - 数据加载 / SWR 缓存逻辑抽至 composables/useMaterialRegistrations.ts
 */
import { ref, computed, onMounted, defineAsyncComponent } from 'vue'
import { materialApi } from '@/api'
import type { RegItem, Registration } from '@/api/material'
import { useAuthStore } from '@/stores/auth'
import { useExport } from '@/composables/useExport'
import type { SupMatItem, SupplierDetail } from './material-types'
import { useMaterialRegistrations } from './composables/useMaterialRegistrations'
import { formatQuantity } from '@/utils/quantity'
import { mapSupplierDetail, updateSupplierDialogLocally, updateDetailDialogLocally } from './composables/useSupplierDetailTransform'
import ProgressTab from './components/ProgressTab.vue'
import HistoryTab from './components/HistoryTab.vue'
import MaterialToolbar from './components/MaterialToolbar.vue'
const MaterialDetailDialog = defineAsyncComponent(() => import('./components/MaterialDetailDialog.vue'))
const SupplierDialog = defineAsyncComponent(() => import('./components/SupplierDialog.vue'))
const ReceiveDialog = defineAsyncComponent(() => import('./components/ReceiveDialog.vue'))

// --- Internal Types ---

const authStore = useAuthStore()
const canManage = computed(() => authStore.hasPermission('product_manage'))

const activeTab = ref('progress')

// 数据加载 / SWR 缓存 / 后台刷新 / 页内 toast（原文件逻辑抽至 composable，行为不变）
const {
  toastMsg, toastType, toastIcon, toast,
  pPage, pPerPage, pPages, pIsLoading, pIsFetching, progressCount,
  progressOrderRows, filteredOrderRows, showSearchEmpty, searchKeyword, stats,
  hPage, hPerPage, hPages, historyCount, hIsLoading, hIsFetching, hRegistrations,
  loadProgress, ensureProgressLoaded, ensureHistoryLoaded,
  onProgressPageChange, onHistoryPageChange,
} = useMaterialRegistrations(activeTab)

function switchToProgress() {
  activeTab.value = 'progress'
  ensureProgressLoaded()
}
function switchToHistory() {
  activeTab.value = 'history'
  ensureHistoryLoaded()
}

const showDetailDialog = ref(false), detailData = ref<Registration | null>(null)
/** 查看来料登记详情 */
async function viewDetail(regId: number) { try { const res = await materialApi.registrationDetail(regId); if (res.registration === undefined) { toast('加载失败', 'error'); return }; detailData.value = res.registration ?? null; showDetailDialog.value = true } catch { toast('加载失败', 'error') } }

const showSupplierDialog = ref(false), supplierDetail = ref<SupplierDetail | null>(null), supplierDetailOrderNo = ref('')
/** 查看来料详情（方案3B：调用服务端聚合接口，前端零计算；立即打开 dialog 显示 loading） */
async function viewSupplierDetail(_supplierName: string, orderNo: string) {
  showSupplierDialog.value = true
  supplierDetailOrderNo.value = orderNo
  supplierDetail.value = null
  try {
    const data = await materialApi.supplierDetail(orderNo)
    if (!data.supplier_groups || !data.supplier_groups.length) { toast('无采购中数据', 'warning'); showSupplierDialog.value = false; return }
    supplierDetail.value = mapSupplierDetail(data)
  } catch { toast('加载失败', 'error'); showSupplierDialog.value = false }
}

const showReceiveDialog = ref(false)
const receiveItem = ref({ id: 0, subItems: [] as SupMatItem[], name: '', ordered: 0, received: 0, remaining: 0 })
function openReceive(item: RegItem) { receiveItem.value = { id: item.id, subItems: [{ id: item.id, ordered: parseFloat(String(item.ordered_quantity || 0)), received: parseFloat(String(item.received_quantity || 0)) }], name: item.material_name, ordered: parseFloat(String(item.ordered_quantity || 0)), received: parseFloat(String(item.received_quantity || 0)), remaining: parseFloat(String(item.ordered_quantity || 0)) - parseFloat(String(item.received_quantity || 0)) }; showReceiveDialog.value = true }
function openReceiveBySubItems(subItems: SupMatItem[], name: string, ordered: number, received: number) { receiveItem.value = { id: subItems[0]?.id || 0, subItems, name, ordered, received, remaining: ordered - received }; showReceiveDialog.value = true }

/** 收货登记提交：按每条 item 的剩余额度切分，依次调用 API（串行保证 registration status 一致性） */
async function submitReceive(payload: { qty: number | null; remark: string }) {
  if (!payload.qty || payload.qty <= 0) { toast('请输入有效的收货数量', 'warning'); return }
  let remainingToReceive = payload.qty
  let totalDelta = 0
  let lastAutoCompleted = false
  try {
    for (const sub of receiveItem.value.subItems) {
      if (remainingToReceive <= 0) break
      const itemRemaining = sub.ordered - sub.received
      if (itemRemaining <= 1e-6) continue
      const qtyForThisItem = Math.min(remainingToReceive, itemRemaining)
      const res = await materialApi.receive(sub.id, { received_quantity: qtyForThisItem, remark: payload.remark })
      if (!res.success) { toast(res.message || '登记失败', 'error'); return }
      lastAutoCompleted = !!res.auto_completed
      sub.received += qtyForThisItem
      totalDelta += qtyForThisItem
      remainingToReceive -= qtyForThisItem
    }
    // 2026-10-17 审计 AUD-15：超量时不能连发两条 toast——toast 是单实例覆盖模式，
    // 后一条「收货登记成功」会立即盖掉警告，用户只看到成功、不知道超出部分被丢弃。
    // 改为单条合并消息。2026-10-18 OCR 评审：浮点残差（1e-17）按成功处理，数量格式化。
    // 2026-10-18 OCR 评审：循环体也按 1e-6 容差跳过浮点残差，
    // 且全部已收齐（totalDelta≈0）时给出准确提示，不发无意义请求。
    if (totalDelta <= 1e-6) {
      toast('该物料已全部到货，无需再登记', 'warning')
      loadProgress(pPage.value)
      return
    }
    if (remainingToReceive > 1e-6) {
      toast(`已登记 ${formatQuantity(totalDelta)}，超出采购总量的 ${formatQuantity(remainingToReceive)} 已忽略`, 'warning')
    } else {
      toast(lastAutoCompleted ? '收货完成，该订单已全部到货，已转入历史记录' : '收货登记成功', lastAutoCompleted ? 'success' : 'info')
    }
    showReceiveDialog.value = false
    const newReceived = receiveItem.value.received + totalDelta
    updateSupplierDialogLocally(supplierDetail, showSupplierDialog, receiveItem.value, newReceived)
    updateDetailDialogLocally(detailData, showDetailDialog, receiveItem.value.id, newReceived)
    loadProgress(pPage.value)
  } catch { toast('操作失败', 'error') }
}

const { runExport } = useExport()

function exportData() {
  // P1-25：进度 tab 只导出未完成登记，与页面所见一致
  runExport(() => materialApi.export({ scope: 'progress' }, '来料进度汇总.xlsx'))
}

function exportHistory() {
  // P1-25：历史 tab 只导出已完成登记，与页面所见一致
  runExport(() => materialApi.export({ scope: 'history' }, '来料历史汇总.xlsx'))
}

onMounted(() => {
  switchToProgress()
})
</script>

<style scoped lang="scss">
@use './material-dialogs.scss' as *;
/* === Layout === */
.mr-container {
  padding: 0;
  margin: 0 auto;
  height: 100%;
  display: flex;
  flex-direction: column;
  box-sizing: border-box;
}

/* 主卡片样式已迁移到全局 .page-card 系列（src/styles/app.css） */

/* === Top Bar (Header + Tabs unified) === */
.mr-top-bar {
  display: flex;
  flex-wrap: nowrap;
  justify-content: space-between;
  align-items: center;
  padding: 14px 24px;
  background: rgba(255, 255, 255, 0.95);
  border-radius: 0;
  border-bottom: 1px solid var(--color-border-light, #f1f5f9);
  box-shadow: none;
  margin-bottom: 0;
  gap: 12px;
  flex-shrink: 0;
}

/* === Tabs === */
.mr-tabs {
  display: inline-flex;
  gap: 4px;
  padding: 4px;
  border-radius: 12px;
  background: white;
  border: 1px solid var(--color-border-light);
  box-shadow: 0 1px 3px rgba(0,0,0,0.04), 0 4px 12px rgba(0,0,0,0.06);
}

.mr-tab-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  padding: 8px 14px;
  border: none;
  border-radius: 9px;
  font-size: 13px;
  font-weight: 600;
  color: var(--color-text-secondary);
  background: transparent;
  cursor: pointer;
  transition: all 0.3s ease;
}

.mr-tab-btn:hover {
  background: var(--color-primary-50);
  color: var(--color-primary-600);
  box-shadow: 0 4px 12px rgba(0,0,0,0.08);
  transform: translateY(-1px);
}

.mr-tab-btn.active {
  background: linear-gradient(135deg, var(--color-primary-50), var(--color-primary-100));
  color: var(--color-primary-700);
  box-shadow: 0 4px 12px rgba(0,0,0,0.08), 0 2px 8px rgba(91, 141, 239, 0.2);
  transform: translateY(-1px);
}

/* === Toast === */
.mr-toast {
  position: fixed;
  top: 20px;
  right: 20px;
  padding: 12px 20px;
  border-radius: 10px;
  color: white;
  font-size: 14px;
  z-index: 2000;
  display: none;
  animation: mrSlide 0.3s ease;
}

.mr-toast.show { display: flex; align-items: center; gap: 8px; }
.mr-toast.success { background: var(--color-success-500, #28C76F); }
.mr-toast.error { background: var(--color-danger-500, #EA5456); }
.mr-toast.warning { background: var(--color-warning-500, #FF9F43); }
.mr-toast.info { background: var(--color-primary-500, #5B8DEF); }

@keyframes mrSlide { from { transform: translateX(100%); opacity: 0; } to { transform: translateX(0); opacity: 1; } }

/* === Responsive === */
@media (max-width: 768px) {
  .mr-top-bar { flex-direction: column; gap: 12px; align-items: flex-start; }
}
</style>
