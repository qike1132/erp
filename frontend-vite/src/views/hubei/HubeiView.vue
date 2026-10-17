<template>
  <div class="hu-container">
    <div class="page-card page-card-main">
      <!-- 卡片头部：确认状态TAB与产品搜索框（合并为一行） -->
      <div class="page-card-header">
        <!-- 确认状态 TAB（未确认/已确认）放左上角 -->
        <div class="bo-confirm-filter">
          <button
            type="button"
            :class="['bo-confirm-filter-btn', { 'is-active': confirmStatus === 'unconfirmed' }]"
            @click="setConfirmStatus('unconfirmed')"
          >未确认</button>
          <button
            type="button"
            :class="['bo-confirm-filter-btn', { 'is-active': confirmStatus === 'confirmed' }]"
            @click="setConfirmStatus('confirmed')"
          >已确认</button>
        </div>
        <!-- 未确认提醒：位于「已确认」TAB 右侧 -->
        <div v-if="unconfirmedCount > 0" class="bo-unconfirmed-hint">
          <FontAwesomeIcon icon="exclamation-triangle" aria-hidden="true" />
          <span>提醒：共有 <strong>{{ unconfirmedCount }}</strong> 条订单记录待确认，请及时确认</span>
        </div>
        <!-- 右侧操作区：搜索框 + 导出/打印（右上角） -->
        <div class="hu-header-actions">
          <HubeiSearchBar
            v-model:product-query="filterOrderNo"
            v-model:customer-query="filterCustomer"
            :show-customer-search="false"
            :show-actions="false"
            @select-product="onSelectProduct"
            @reset="onReset"
          />
          <div class="hu-order-actions">
            <span v-if="canPrint && selectedCount > 0" class="bo-selected-count">已选 {{ selectedCount }} 条</span>
            <button
              v-if="canExport"
              type="button"
              class="bo-toolbar-btn bo-toolbar-btn--export"
              :disabled="exporting || displayOrders.length === 0"
              @click="handleExport"
            >
              <FontAwesomeIcon icon="file-csv" aria-hidden="true" /> 导出
            </button>
            <button
              v-if="canPrint"
              type="button"
              class="bo-toolbar-btn bo-toolbar-btn--print"
              :disabled="selectedCount === 0"
              @click="handlePrint"
            >
              <FontAwesomeIcon icon="print" aria-hidden="true" /> 打印
            </button>
          </div>
        </div>
      </div>

      <!-- 内容区：湖北订单 -->
      <div class="page-card-body">
        <div class="hu-tab-content">
          <BeileOrderTab />
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
/**
 * HubeiView.vue — 湖北订单页面（/beile-order）
 *
 * 湖北订单页面：展示湖北工厂生产订单（BeileOrderTab，含通知跳转高亮）。
 *
 * - 路由：/beile-order
 * - 状态管理：调用 provideBeileOrders() 创建唯一状态实例并 provide 给
 *   BeileOrderTab，消除原先经 defineExpose + template ref 的反向桥接，
 *   避免子组件状态变化触发父组件 computed 重算与联动重渲染。
 * - 筛选：产品搜索状态经 computed 双向绑定到 composable 的 filters；
 *   确认状态 TAB（未确认/已确认）调用 setConfirmStatus（含回到首页）。
 * - 提示：顶部仅保留「未确认」汇总横幅；「未下单」汇总横幅已按业务反馈移除
 *   （行内「未开单」徽章与确认按钮禁用态/门控提示保持不变）。
 */
import { computed, ref } from 'vue'
import BeileOrderTab from '@/views/beile-order/BeileOrderTab.vue'
import HubeiSearchBar from '@/views/hubei/HubeiSearchBar.vue'
import { provideBeileOrders } from '@/views/beile-order/composables/useBeileOrders'
import { useWebSocket } from '@/composables/useWebSocket'

const {
  filters,
  confirmStatus,
  unconfirmedCount,
  setConfirmStatus,
  applyProductFilter,
  handleReset,
  // 导出 / 打印（按钮位于页头右上角 .hu-header-actions）
  displayOrders,
  selectedCount,
  canExport,
  canPrint,
  exporting,
  handleExport,
  handlePrint,
  refetch: refetchBeileOrders,
} = provideBeileOrders()

// 实时刷新：客户订单写入（删除/改数量/新建）由后端广播 WebSocket 事件，
// 收到即重新拉取当前列表。与采购页（usePurchaseHandlers）同款通道；
// 此前本页无任何实时通道，跨标签页操作只能等 30s staleTime 过期。
useWebSocket({
  isActive: ref(true),
  onMessage: (data) => {
    const t = String(data.type)
    if (t === 'order_created' || t === 'order_updated' || t === 'order_deleted') {
      refetchBeileOrders()
    }
  },
})

/** 筛选栏 v-model：双向绑定到 composable 的 filters（reactive） */
const filterOrderNo = computed({
  get: () => filters.productKw,
  set: (v: string) => { filters.productKw = v },
})
const filterCustomer = computed({
  get: () => filters.customer,
  set: (v: string) => { filters.customer = v },
})

function onSelectProduct(name: string) {
  applyProductFilter(name)
}

function onReset() {
  handleReset()
}
</script>

<style scoped lang="scss">
@use '@/styles/hubei-page.scss' as *;

/* 头部布局：TAB 与提醒靠左，搜索框 + 导出/打印靠右（右上角） */
.hu-header-actions {
  margin-left: auto;
  display: flex;
  align-items: center;
  gap: 12px;
  flex-shrink: 0;
}
.hu-header-actions :deep(.hu-filter-bar) {
  flex-shrink: 0;
}
.hu-order-actions {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-shrink: 0;
}

/* ===== 导出 / 打印按钮（自 BeileOrderTab 工具栏上移至页头右上角） ===== */
.bo-selected-count {
  font-size: 13px;
  font-weight: 600;
  color: var(--color-primary-600, #2563eb);
}
.bo-toolbar-btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 6px 14px;
  font-size: 13px;
  font-weight: 600;
  border: 1px solid var(--color-border-light, #e2e8f0);
  border-radius: 8px;
  background: #fff;
  color: var(--color-text-secondary, #475569);
  cursor: pointer;
  font-family: inherit;
  transition: all 0.15s ease;
  white-space: nowrap;
}
.bo-toolbar-btn:hover:not(:disabled) {
  border-color: var(--color-primary-300, #93c5fd);
  color: var(--color-primary-600, #2563eb);
  background: var(--color-primary-50, #eff6ff);
}
.bo-toolbar-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
.bo-toolbar-btn--export:hover:not(:disabled) {
  border-color: var(--color-success-400, #4ade80);
  color: var(--color-success-600, #16a34a);
  background: var(--color-success-50, #f0fdf4);
}
.bo-toolbar-btn--print:hover:not(:disabled) {
  border-color: var(--color-warning-400, #fbbf24);
  color: var(--color-warning-600, #d97706);
  background: var(--color-warning-50, #fffbeb);
}

/* 页头去重后：宽度不足时允许换行，保证 scrollWidth ≤ clientWidth
   （1280/1440/1600 三档均无横向溢出、无裁切） */
.page-card-header {
  flex-wrap: wrap;
  row-gap: 8px;
}

/* ===== 确认状态筛选（未确认/已确认 TAB，湖北订单确认流程） ===== */
/* 包裹容器：对齐板房管理 .pr-top-right 的分组按钮容器样式 */
.bo-confirm-filter {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 4px;
  border-radius: 12px;
  background: white;
  border: 1px solid var(--color-border-light, #e2e8f0);
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.04), 0 4px 12px rgba(0, 0, 0, 0.06);
  flex-shrink: 0;
}
.bo-confirm-filter-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  padding: 6px 14px;
  font-size: 13px;
  font-weight: 500;
  color: var(--color-text-secondary, #6b7280);
  background: #fff;
  border: 1px solid var(--color-border-light, #e5e7eb);
  border-radius: 9px;
  cursor: pointer;
  font-family: inherit;
  user-select: none;
  transition: all 0.15s ease;
}
.bo-confirm-filter-btn:hover {
  border-color: var(--color-primary-300, #93c5fd);
  color: var(--color-primary-600, #3b82f6);
  background: var(--color-primary-50, #eff6ff);
}
.bo-confirm-filter-btn.is-active {
  color: #fff;
  background: linear-gradient(135deg, var(--color-primary-500, #3b82f6), var(--color-primary-600, #2563eb));
  border-color: var(--color-primary-600, #2563eb);
  box-shadow: 0 2px 6px rgba(59, 130, 246, 0.25);
}
.bo-confirm-filter-btn.is-active:hover {
  color: #fff;
  background: linear-gradient(135deg, var(--color-primary-600, #2563eb), var(--color-primary-700, #1d4ed8));
}
.bo-confirm-filter-count {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 16px;
  height: 16px;
  padding: 0 4px;
  border-radius: 999px;
  font-size: 10px;
  font-weight: 700;
  line-height: 1;
  background: var(--color-warning-100);
  color: var(--color-warning-700);
}
.bo-confirm-filter-btn.is-active .bo-confirm-filter-count {
  background: rgba(255, 255, 255, 0.28);
  color: #fff;
}

/* ===== 未确认提醒（位于「已确认」TAB 右侧） ===== */
.bo-unconfirmed-hint {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 6px 14px;
  border-radius: 9px;
  background: var(--color-warning-50);
  border: 1px solid var(--color-warning-200);
  color: var(--color-warning-700);
  font-size: 13px;
  font-weight: 600;
  flex-shrink: 0;
}
.bo-unconfirmed-hint svg {
  flex-shrink: 0;
}
.bo-unconfirmed-hint strong {
  color: var(--color-warning-800);
  font-size: 15px;
}
</style>
