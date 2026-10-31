<template>
  <div class="pc-container">
    <!-- 汇总下单整页视图（2026-10-31 由弹窗改为铺满内容区）：open 时替换整个订单列表卡片，
         侧边栏保留。数据层 useSummaryModal 不变，仅承载方式从 UiDialog 换成页面视图。 -->
    <div v-if="summary.open" class="page-card page-card-main">
      <SummaryPanel
        :factory-data="summary.factoryData"
        :supplier-data="summary.supplierData"
        :edit-mode="summary.editMode"
        :loss-rate="summary.lossRate"
        :loss-rate-save-state="summary.lossRateSaveState"
        :loss-rate-mixed="summary.lossRateMixed"
        :fabric-loss-rates="summary.fabricLossRates"
        :fabric-loss-rate-mixed="summary.fabricLossRateMixed"
        :group-spare-rates="summary.groupSpareRates"
        :order-count="purchaseOrders.selectedIds.length"
        :supplier-groups="summary.supplierGroups"
        @close="handleSummaryClose"
        @toggle-edit-mode="summary.toggleEditMode"
        @save-edits="handleSaveFactoryEdits"
        @update-qty="handleUpdateFactoryQty"
        @apply-loss-rate="handleApplyLossRate"
        @apply-fabric-loss-rate="handleApplyFabricLossRate"
        @export-factory="summary.exportFactory"
        @export-supplier="handleExportSupplier"
        @print-factory="summary.printFactory"
        @print-supplier="summary.printSupplier"
      />
    </div>

    <div v-else class="page-card page-card-main">
      <div class="page-card-header">
        <div class="pc-tab-group" role="tablist">
          <button
            role="tab"
            :aria-selected="activeTab === 'active'"
            :class="['pc-tab-btn', { active: activeTab === 'active' }]"
            @click="switchTab('active')"
          >
            待生产订单
            <span v-if="activeOrderCount > 0" class="pc-tab-badge">{{ activeOrderCount }}</span>
          </button>
          <button
            role="tab"
            :aria-selected="activeTab === 'history'"
            :class="['pc-tab-btn', { active: activeTab === 'history' }]"
            @click="switchTab('history')"
          >
            记录查询
          </button>
        </div>

        <!-- 待生产订单 TAB 的操作区 -->
        <div v-if="activeTab === 'active'" class="pc-header-actions">
          <button
            class="pc-btn pc-btn-purple"
            :disabled="purchaseOrders.selectedIds.length === 0 || isSummarizing"
            @click="handleSummary"
          >
            <UiLoadingIcon :loading="isSummarizing" icon="clipboard-list" /> 汇总下单 ({{ purchaseOrders.selectedIds.length }})
          </button>
          <button
            class="pc-btn pc-btn-success"
            :disabled="purchaseOrders.selectedIds.length === 0"
            @click="handleBatchComplete"
          >
            <FontAwesomeIcon icon="check-double" aria-hidden="true" /> 批量确认订单 ({{ purchaseOrders.selectedIds.length }})
          </button>
        </div>

        <!-- 记录查询 TAB 的筛选区（与 TAB 同一行、右上角） -->
        <div v-else class="pc-header-actions pc-header-filters">
          <CompletedOrdersFilterInputs v-model:draft="completed.draft" @search="completed.search" />
          <button
            class="pc-btn pc-btn-primary"
            :class="{ 'pc-btn-dirty': completed.isDirty }"
            @click="completed.search"
          >
            查询
          </button>
          <button class="pc-btn" :disabled="!completed.hasFilter && !completed.isDirty" @click="completed.reset">
            重置
          </button>
          <button class="pc-btn" :disabled="exporting" @click="handleExport">
            <UiLoadingIcon :loading="exporting" icon="download" />
            {{ exporting ? '导出中…' : '导出' }}
          </button>
          <span class="count-badge">共 {{ completed.total }} 条</span>
        </div>
      </div>

      <div class="page-card-body">
        <div
          v-if="bomResume.phase.value !== 'IDLE' && bomResume.message.value"
          class="pc-resume-status"
          role="status"
        >
          <span>{{ bomResume.message.value }}</span>
          <button
            v-if="bomResume.phase.value === 'RESUME_FAILED'"
            class="pc-btn pc-btn-primary pc-btn-sm"
            :disabled="bomResume.resumeInFlight.value"
            @click="bomResume.retryResume"
          >重试续提</button>
        </div>
        <!-- P1-9: v-if 替代 v-show，非当前 tab 卸载 DOM 减轻 paint；
             数据层在 usePurchaseHandlers 顶层 composable（不随 Panel 卸载），
             配合 Vue Query 缓存切回秒出 -->
        <template v-if="activeTab === 'active'">
          <!-- 待生成行与待生产行同表并列（同列、无颜色区分）。
               采购订单已改为自动生成：缺 BOM 的行在操作列提示「未配置BOM，无法下单」，
               配好 BOM 后自动生成、自然变为待生产行。 -->
          <ActiveOrdersPanel
            :orders="purchaseOrders.orders"
            :unprocessed-orders="unprocessed.orders"
            :loading="purchaseOrders.loading"
            :fetching="purchaseOrders.fetching || unprocessed.fetching"
            :error="purchaseOrders.error"
            :total="purchaseOrders.total"
            :current-page="purchaseOrders.page"
            :total-pages="purchaseOrders.pages"
            :selected-ids="purchaseOrders.selectedIds"
            :all-selected="purchaseOrders.allSelected"
            :can-manage-bom="bomResume.canManageBom.value"
            :resume-source-id="bomResume.resumeSourceId.value"
            :resume-in-flight="bomResume.resumeInFlight.value"
            @configure-bom="bomResume.startConfiguration"
            @toggle-all="purchaseOrders.toggleAll"
            @toggle-selection="purchaseOrders.toggleSelection"
            @complete-order="handleCompleteOrder"
            @update:current-page="handleOrderPageChange"
            @retry="handleOrdersRetry"
          />
        </template>

        <!-- 记录查询面板 -->
        <CompletedOrdersPanel
          v-else
          :filters="completed.filters"
          :orders="completed.orders"
          :loading="completed.loading"
          :fetching="completed.fetching"
          :error="completed.error"
          :total="completed.total"
          :current-page="completed.page"
          :total-pages="completed.totalPages"
          :has-filter="completed.hasFilter"
          @reset="completed.reset"
          @remove-filter="handleRemoveCompletedFilter"
          @view-detail="handleViewDetail"
          @update:current-page="handleCompletedPageChange"
          @retry="completed.retry"
        />
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
    <OrderDetailModal
      :open="detailVisible"
      :order="detailOrder"
      @close="detailVisible = false"
      @saved="handleDetailSaved"
    />

    <!-- 同页 BOM 配置：不再跳 /product；保存/关闭直接回到本页续提状态机 -->
    <component
      :is="bomEditorComponent"
      v-if="bomEditorComponent"
      ref="bomEditorRef"
      @saved="bomResume.completeConfiguration($event.product_id)"
      @closed="bomResume.cancelConfiguration()"
    />
  </div>
</template>

<script setup lang="ts">
import {
  computed, defineAsyncComponent,
} from 'vue'
import ActiveOrdersPanel from './components/ActiveOrdersPanel.vue'
import CompletedOrdersPanel from './components/CompletedOrdersPanel.vue'
import UiConfirmDialog from '@/components/ui/UiConfirmDialog.vue'
import CompletedOrdersFilterInputs from './components/CompletedOrdersFilterInputs.vue'
import { usePurchaseBomModal } from './composables/usePurchaseBomModal'
import { useSummaryLeaveGuard } from './composables/useSummaryLeaveGuard'
// P1-5: 模态框懒加载，减小 purchase 主 chunk（用户不点开则不加载）
const OrderDetailModal = defineAsyncComponent(() => import('./components/OrderDetailModal.vue'))
const SummaryPanel = defineAsyncComponent(() => import('./components/SummaryPanel.vue'))
import { usePurchaseHandlers } from './composables/usePurchaseHandlers'

const { bomEditorRef, bomEditorComponent, openBomEditor } = usePurchaseBomModal()

const {
  activeTab,
  isSummarizing,
  purchaseOrders,
  unprocessed,
  completed,
  summary,
  confirm,
  detailVisible,
  detailOrder,
  switchTab,
  handleCompleteOrder,
  handleBatchComplete,
  handleSummary,
  handleOrderPageChange,
  handleSaveFactoryEdits,
  handleUpdateFactoryQty,
  handleApplyLossRate,
  handleApplyFabricLossRate,
  handleViewDetail,
  handleCompletedPageChange,
  handleRemoveCompletedFilter,
  handleExport,
  handleExportSupplier,
  exporting,
  bomResume,
} = usePurchaseHandlers({ openBomEditor })

/** 待生产订单 TAB 徽标 = 表格实际行数口径：待生成行（unprocessed）+ 待生产行（purchaseOrders）。
 * 二者同表并列渲染，只取 purchaseOrders.total 会漏掉待生成行，徽标小于可见行数。
 */
const activeOrderCount = computed(() => unprocessed.total + purchaseOrders.total)

/* 汇总下单整页视图的离开守卫（编辑态确认）：判定与确认细节在 useSummaryLeaveGuard
 * （View 在 400 行门禁边缘，接线一行化；弹窗时代靠遮罩拦导航，整页化后侧边栏可点）。 */
const { handleSummaryClose } = useSummaryLeaveGuard(summary, confirm.confirm)

/** 待生产/待生成任一列表加载失败时，重试两者 */
function handleOrdersRetry() {
  purchaseOrders.retry()
  unprocessed.retry()
}

/** 采购单详情里补录完单价 → 重新拉详情，让弹窗与列表都显示最新金额 */
function handleDetailSaved(orderId: number) {
  void handleViewDetail(orderId)
}
</script>

<style scoped lang="scss">
@use './components/order-panels.scss' as *;

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

/* === Header Actions === */
.pc-header-actions {
  display: flex;
  align-items: center;
  gap: 8px;
}

.pc-btn-purple {
  color: var(--color-purple-700, #7e22ce);
  border-color: var(--color-purple-200, #e9d5ff);
  background: var(--color-purple-50, #faf5ff);
}

.pc-btn-purple:hover:not(:disabled) {
  background: var(--color-purple-600, #9333ea);
  color: white;
  border-color: transparent;
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

/* === BOM 续提状态 === */
.pc-resume-status {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 10px 16px;
  color: var(--color-text-secondary);
  background: var(--color-primary-50, #eff6ff);
  border-bottom: 1px solid var(--color-border-light);
  font-size: 13px;
}

/* === Body === */
/* 与 /beile-order 一致：内容贴卡片边缘，无内边距（覆盖全局 20px 24px） */
.page-card-body {
  padding: 0;
}

.pc-tab-content {
  padding: 0;
}

/* === 记录查询 TAB 筛选区（与 TAB 同行，右上角） === */
.pc-header-filters {
  gap: 10px;
  /* 收窄时允许内部换行，避免把 TAB 挤走 */
  flex-wrap: wrap;
  justify-content: flex-end;
  min-width: 0;
}

.pc-btn-primary {
  color: #fff;
  background: linear-gradient(135deg, var(--color-primary-500, #5b8def), var(--color-primary-600, #3a6bd6));
  border-color: transparent;
  box-shadow: 0 2px 6px rgba(58, 107, 214, 0.28);
}

.pc-btn-primary:hover:not(:disabled) {
  background: linear-gradient(135deg, var(--color-primary-600, #3a6bd6), var(--color-primary-700, #2d5ab8));
  border-color: transparent;
  box-shadow: 0 4px 12px rgba(58, 107, 214, 0.34);
  color: #fff;
}

/* 有未提交改动时高亮「查询」，提示「改了还没查」 */
.pc-btn-dirty {
  box-shadow: 0 0 0 3px rgba(91, 141, 239, 0.25);
}
</style>
