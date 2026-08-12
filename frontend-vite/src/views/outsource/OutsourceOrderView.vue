<template>
  <div class="hu-container">
    <div class="page-card page-card-main">
      <!-- 卡片头部：HeaderTabs + 产品/客户/工序状态筛选 -->
      <div class="page-card-header">
        <div class="hu-header-left">
          <HeaderTabs />
        </div>
        <HubeiSearchBar
          v-model:product-query="filters.orderNo"
          v-model:customer-query="filters.customer"
          v-model:process-status="processStatusDraft"
          show-process-status
          @select-product="applyProductFilter"
          @select-customer="applyCustomerFilter"
          @search="handleSearch"
          @reset="handleReset"
        />
      </div>

      <!-- Tab 导航：湖北订单 / 外发工序 / 工序预设（各自独立路由） -->
      <HubeiRouteTabs />

      <!-- 内容区：外发工序 -->
      <div class="page-card-body">
        <div class="hu-tab-content">
          <OutsourceOrderTab
            :product-filter="appliedProduct"
            :customer-filter="appliedCustomer"
            :process-status-filter="appliedProcessStatus"
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
 * 产品/客户/工序状态筛选在本页面维护，确认后传入子组件。
 */
import { ref } from 'vue'
import OutsourceOrderTab from '@/views/outsource/components/OutsourceOrderTab.vue'
import HeaderTabs from '@/layouts/components/HeaderTabs.vue'
import HubeiRouteTabs from '@/views/hubei/HubeiRouteTabs.vue'
import HubeiSearchBar from '@/views/hubei/HubeiSearchBar.vue'

// ===== 筛选状态 =====
const filters = ref({ orderNo: '', customer: '' })
const processStatusDraft = ref('')
const appliedProduct = ref('')
const appliedCustomer = ref('')
const appliedProcessStatus = ref('')

/** 点击查询：确认筛选后传入 OutsourceOrderTab */
function handleSearch() {
  appliedProduct.value = filters.value.orderNo
  appliedCustomer.value = filters.value.customer
  appliedProcessStatus.value = processStatusDraft.value
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
  processStatusDraft.value = ''
  appliedProduct.value = ''
  appliedCustomer.value = ''
  appliedProcessStatus.value = ''
}
</script>

<style scoped>
.hu-container {
  padding: 0;
  margin: 0 auto;
  height: 100%;
  display: flex;
  flex-direction: column;
  box-sizing: border-box;
  contain: layout style;
  overflow-anchor: none;
  overflow: hidden;
}

.page-card-header :deep(.ht-bar) {
  width: auto;
  margin: 0;
}
.hu-header-left {
  display: flex;
  align-items: center;
  gap: 12px;
  flex: 1;
  min-width: 0;
}

/* 内容区 */
.page-card-body {
  padding: 0;
  scrollbar-gutter: auto;
  display: flex;
  flex-direction: column;
  min-height: 0;
}
.hu-tab-content {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
}

@media (max-width: 900px) {
  .page-card-header {
    flex-wrap: wrap;
    gap: 8px;
  }
}
</style>
