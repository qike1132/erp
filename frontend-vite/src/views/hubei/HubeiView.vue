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
        <HubeiSearchBar
          v-model:product-query="filterOrderNo"
          v-model:customer-query="filterCustomer"
          :show-customer-search="false"
          :show-actions="false"
          @select-product="onSelectProduct"
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



function onSelectProduct(name: string) {
  beileTab.value?.applyProductFilter(name)
}

function onReset() {
  beileTab.value?.handleReset()
}
</script>

<style scoped lang="scss">
@use '@/styles/hubei-page.scss' as *;

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
</style>
