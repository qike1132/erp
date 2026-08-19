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
            @click="confirmStatus = 'unconfirmed'"
          >未确认</button>
          <button
            type="button"
            :class="['bo-confirm-filter-btn', { 'is-active': confirmStatus === 'confirmed' }]"
            @click="confirmStatus = 'confirmed'"
          >已确认</button>
        </div>
        <!-- 未确认提醒：位于「已确认」TAB 右侧 -->
        <div v-if="unconfirmedCount > 0" class="bo-unconfirmed-hint">
          <FontAwesomeIcon icon="exclamation-triangle" aria-hidden="true" />
          <span>提醒：共有 <strong>{{ unconfirmedCount }}</strong> 条订单记录待确认，请及时确认</span>
        </div>
        <HubeiSearchBar
          v-model:product-query="filterOrderNo"
          v-model:customer-query="filterCustomer"
          :show-customer-search="false"
          :show-actions="false"
          @select-product="onSelectProduct"
          @reset="onReset"
        />
        <!-- 导出 / 打印按钮：位于产品搜索框右侧 -->
        <div class="bo-header-actions">
          <button
            v-if="canExport"
            type="button"
            class="bo-header-btn bo-header-btn--export"
            :disabled="exporting || !hasDisplayOrders"
            @click="handleExport"
          >
            <FontAwesomeIcon icon="file-csv" aria-hidden="true" /> 导出
          </button>
          <button
            v-if="canPrint"
            type="button"
            class="bo-header-btn bo-header-btn--print"
            :disabled="selectedCount === 0"
            @click="handlePrint"
          >
            <FontAwesomeIcon icon="print" aria-hidden="true" /> 打印
          </button>
        </div>
      </div>

      <!-- 内容区：湖北订单 -->
      <div class="page-card-body">
        <div class="hu-tab-content">
          <BeileOrderTab ref="beileTab" />
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
/**
 * HubeiView.vue — 湖北订单页面（/beile-order）
 *
 * 湖北订单页面：展示湖北工厂生产订单（BeileOrderTab，含详情弹窗/通知跳转高亮）。
 *
 * - 路由：/beile-order
 * - 筛选：产品/客户搜索状态在 BeileOrderTab 内部，本页面经 ref 桥接
 *   到头部筛选栏；确认状态 TAB（未确认/已确认）在左上角，
 *   读写 BeileOrderTab 内部的确认状态。
 */
import { ref, computed } from 'vue'
import BeileOrderTab from '@/views/beile-order/BeileOrderTab.vue'
import HubeiSearchBar from '@/views/hubei/HubeiSearchBar.vue'

/** 湖北订单筛选：状态在 BeileOrderTab 内部，经 ref 暴露 */
const beileTab = ref<InstanceType<typeof BeileOrderTab> | null>(null)

/** 筛选栏 v-model：桥接到 BeileOrderTab 内部 filters */
const filterOrderNo = computed({
  get: () => beileTab.value?.filters.orderNo ?? '',
  set: (v: string) => {
    if (beileTab.value) beileTab.value.filters.orderNo = v
  },
})
const filterCustomer = computed({
  get: () => beileTab.value?.filters.customer ?? '',
  set: (v: string) => {
    if (beileTab.value) beileTab.value.filters.customer = v
  },
})

/** 确认状态（未确认/已确认）TAB：读写 BeileOrderTab 内部 confirmStatus */
const confirmStatus = computed({
  get: () => beileTab.value?.confirmStatus ?? 'unconfirmed',
  set: (v: string) => beileTab.value?.setConfirmStatus(v),
})

/** 未确认订单数（提醒横幅用） */
const unconfirmedCount = computed(() => beileTab.value?.unconfirmedCount ?? 0)

// ===== 导出 / 打印（按钮在头部搜索框右侧，状态经 ref 桥接自 BeileOrderTab） =====
const canExport = computed(() => beileTab.value?.canExport ?? false)
const canPrint = computed(() => beileTab.value?.canPrint ?? false)
const exporting = computed(() => beileTab.value?.exporting ?? false)
const selectedCount = computed(() => beileTab.value?.selectedCount ?? 0)
const hasDisplayOrders = computed(() => beileTab.value?.hasDisplayOrders ?? false)

function handleExport() {
  beileTab.value?.handleExport()
}
function handlePrint() {
  beileTab.value?.handlePrint()
}



function onSelectProduct(name: string) {
  beileTab.value?.applyProductFilter(name)
}

function onReset() {
  beileTab.value?.handleReset()
}
</script>

<style scoped lang="scss">
@use '@/styles/hubei-page.scss' as *;

/* 头部布局：TAB 靠左，搜索框 + 导出/打印按钮靠右 */
.page-card-header :deep(.hu-filter-bar) {
  margin-left: auto;
  flex-shrink: 0;
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

/* ===== 导出 / 打印按钮（位于产品搜索框右侧） ===== */
.bo-header-actions {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  flex-shrink: 0;
}
.bo-header-btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 7px 14px;
  font-size: 13px;
  font-weight: 600;
  border: 1px solid var(--color-border-light, #e2e8f0);
  border-radius: 9px;
  background: #fff;
  color: var(--color-text-secondary, #475569);
  cursor: pointer;
  font-family: inherit;
  transition: all 0.15s ease;
  white-space: nowrap;
}
.bo-header-btn:hover:not(:disabled) {
  border-color: var(--color-primary-300, #93c5fd);
  color: var(--color-primary-600, #2563eb);
  background: var(--color-primary-50, #eff6ff);
}
.bo-header-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
.bo-header-btn--export:hover:not(:disabled) {
  border-color: var(--color-success-400, #4ade80);
  color: var(--color-success-600, #16a34a);
  background: var(--color-success-50, #f0fdf4);
}
.bo-header-btn--print:hover:not(:disabled) {
  border-color: var(--color-warning-400, #fbbf24);
  color: var(--color-warning-600, #d97706);
  background: var(--color-warning-50, #fffbeb);
}
</style>
