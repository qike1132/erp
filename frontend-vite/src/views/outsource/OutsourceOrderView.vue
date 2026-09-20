<template>
  <div class="hu-container">
    <div class="page-card page-card-main">
      <!-- 卡片头部：Tab 导航与搜索框同一行（Tab 靠左，筛选靠右） -->
      <div class="page-card-header">
        <HubeiRouteTabs />
        <HubeiSearchBar
          v-model:product-query="filters.orderNo"
          v-model:customer-query="filters.customer"
          @select-product="applyProductFilter"
          @select-customer="applyCustomerFilter"
          @search="handleSearch"
          @reset="handleReset"
        />
        <div class="oso-header-actions">
          <button
            type="button"
            class="oso-toolbar-btn oso-toolbar-btn--export"
            :disabled="exporting || loading"
            @click="handleExport"
          >
            <FontAwesomeIcon icon="file-csv" aria-hidden="true" /> 导出未到货
          </button>
          <button
            type="button"
            class="oso-toolbar-btn oso-toolbar-btn--print"
            :disabled="exporting || loading"
            @click="handlePrint"
          >
            <FontAwesomeIcon icon="print" aria-hidden="true" /> 打印未到货
          </button>
        </div>
      </div>

      <!-- 内容区：外发工序 -->
      <div class="page-card-body">
        <div class="hu-tab-content">
          <OutsourceOrderTab
            :product-filter="appliedProduct"
            :customer-filter="appliedCustomer"
          />
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
/**
 * OutsourceOrderView.vue — 外发工序页面（/outsource）
 *
 * 原 /beile-order 合并页中「外发工序」Tab 拆分为独立路由页面，
 * 展示湖北工厂订单 + 外发工序进度（OutsourceOrderTab）。
 * 产品/客户筛选在本页面维护，确认后传入子组件。
 */
import { ref } from 'vue'
import OutsourceOrderTab from '@/views/outsource/components/OutsourceOrderTab.vue'
import HubeiRouteTabs from '@/views/hubei/HubeiRouteTabs.vue'
import HubeiSearchBar from '@/views/hubei/HubeiSearchBar.vue'
import { useOutsourceUnshipped } from '@/views/outsource/composables/useOutsourceUnshipped'

// ===== 筛选状态 =====
const filters = ref({ orderNo: '', customer: '' })
const appliedProduct = ref('')
const appliedCustomer = ref('')

// ===== 未到货明细导出/打印（跨全部订单聚合） =====
const { exporting, loading, handleExport, handlePrint } = useOutsourceUnshipped()

/** 点击查询：确认筛选后传入 OutsourceOrderTab */
function handleSearch() {
  appliedProduct.value = filters.value.orderNo
  appliedCustomer.value = filters.value.customer
}

/** 直接选择候选项时同步确认筛选值（不依赖查询按钮） */
function applyProductFilter(name: string) {
  appliedProduct.value = name
}

function applyCustomerFilter(name: string) {
  appliedCustomer.value = name
}

function handleReset() {
  filters.value = { orderNo: '', customer: '' }
  appliedProduct.value = ''
  appliedCustomer.value = ''
}
</script>

<style scoped lang="scss">
@use '@/styles/hubei-page.scss' as *;

/* Tab 导航与搜索框同一行：Tab 靠左，搜索靠右，避免搜索框被挤压 */
.page-card-header {
  flex-wrap: nowrap;
  gap: 12px;
}
.page-card-header :deep(.hu-tabs-bar) {
  padding: 0;
  flex-shrink: 0;
}
.page-card-header :deep(.hu-filter-bar) {
  margin-left: auto;
  flex-shrink: 0;
}
.oso-header-actions {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-shrink: 0;
}
.oso-toolbar-btn {
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
  white-space: nowrap;
  transition: all 0.15s ease;
}
.oso-toolbar-btn:hover:not(:disabled) {
  border-color: var(--color-primary-300, #93c5fd);
  color: var(--color-primary-600, #2563eb);
  background: var(--color-primary-50, #eff6ff);
}
.oso-toolbar-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
.oso-toolbar-btn--export:hover:not(:disabled) {
  border-color: var(--color-success-400, #4ade80);
  color: var(--color-success-600, #16a34a);
  background: var(--color-success-50, #f0fdf4);
}
.oso-toolbar-btn--print:hover:not(:disabled) {
  border-color: var(--color-warning-400, #fbbf24);
  color: var(--color-warning-600, #d97706);
  background: var(--color-warning-50, #fffbeb);
}
</style>
