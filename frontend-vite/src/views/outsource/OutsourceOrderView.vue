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
 * OutsourceOrderView.vue — 外发进度页面（/outsource）
 *
 * 展示湖北工厂订单 + 外发工序进度（OutsourceOrderTab），只读看进度。
 * 方案B：页头「导出/打印未到货」迁至发货单页（OutsourceShipmentView）信息条，
 * 本页头部仅保留 Tab 导航与产品/客户筛选。
 * 产品/客户筛选在本页面维护，确认后传入子组件。
 */
import { ref } from 'vue'
import OutsourceOrderTab from '@/views/outsource/components/OutsourceOrderTab.vue'
import HubeiRouteTabs from '@/views/hubei/HubeiRouteTabs.vue'
import HubeiSearchBar from '@/views/hubei/HubeiSearchBar.vue'

// ===== 筛选状态 =====
const filters = ref({ orderNo: '', customer: '' })
const appliedProduct = ref('')
const appliedCustomer = ref('')

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
</style>
