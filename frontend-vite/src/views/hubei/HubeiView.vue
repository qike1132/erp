<template>
  <div class="hu-container">
    <div class="page-card page-card-main">
      <!-- 卡片头部：HeaderTabs + 产品/客户筛选 -->
      <div class="page-card-header">
        <div class="hu-header-left">
          <HeaderTabs />
        </div>
        <HubeiSearchBar
          v-model:product-query="filterOrderNo"
          v-model:customer-query="filterCustomer"
          @select-product="onSelectProduct"
          @select-customer="onSelectCustomer"
          @search="onSearch"
          @reset="onReset"
        />
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
 *   到 HeaderTabs 同行的筛选栏。
 */
import { ref, computed } from 'vue'
import BeileOrderTab from '@/views/beile-order/BeileOrderTab.vue'
import HeaderTabs from '@/layouts/components/HeaderTabs.vue'
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

function onSelectProduct(name: string) {
  beileTab.value?.applyProductFilter(name)
}

function onSelectCustomer(name: string) {
  beileTab.value?.applyCustomerFilter(name)
}

function onSearch() {
  beileTab.value?.handleSearch()
}

function onReset() {
  beileTab.value?.handleReset()
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
