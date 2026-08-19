<template>
  <div class="ci-wrap">
    <!-- 库存汇总 -->
    <CaseInventorySummary
      v-model:inv-search="invSearch"
      :inv-per-page="invPerPage"
      :inv-is-loading="invIsLoading"
      :inv-is-fetching="invIsFetching"
      :inv-total-pages="invTotalPages"
      :inv-total-stock="invTotalStock"
      :inv-total-in="invTotalIn"
      :inv-total-out="invTotalOut"
      :inventory-list="inventoryList"
      :on-inv-search-input="onInvSearchInput"
      :on-inv-page-change="onInvPageChange"
      :inv-refetch="invRefetch"
      :select-case-row="selectCaseRow"
    />

    <!-- 库存流水记录 -->
    <CaseInventoryLogs
      v-if="selectedCaseName"
      v-model:show-log-filter="showLogFilter"
      v-model:log-filter-type="logFilterType"
      v-model:log-filter-start="logFilterStart"
      v-model:log-filter-end="logFilterEnd"
      v-model:log-page="logPage"
      :selected-case-name="selectedCaseName"
      :log-per-page="logPerPage"
      :log-total-pages="logTotalPages"
      :log-is-loading="logIsLoading"
      :log-is-fetching="logIsFetching"
      :log-list="logList"
      :on-log-page-change="onLogPageChange"
      :log-refetch="logRefetch"
      :clear-log-filter="clearLogFilter"
      :log-badge-class="logBadgeClass"
    />

    <!-- 未选中提示 -->
    <div v-if="!selectedCaseName" class="ci-section">
      <div class="ci-empty-hint">
        <FontAwesomeIcon icon="info-circle" aria-hidden="true" />
        <p>请点击上方库存表格中的产品查看流水记录</p>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
/**
 * CaseInventoryTab.vue — 皮套库存查询标签页
 *
 * 职责：
 * - 展示皮套库存汇总（统计卡片 + 分页表格）
 * - 点击产品行查看该产品的库存流水记录
 * - 支持按操作类型、日期范围筛选流水
 */
import CaseInventorySummary from './components/CaseInventorySummary.vue'
import CaseInventoryLogs from './components/CaseInventoryLogs.vue'
import { useCaseInventory } from './composables/useCaseInventory'

const {
  invSearch,
  invPerPage,
  invIsLoading,
  invIsFetching,
  invRefetch,
  inventoryList,
  invTotalPages,
  invTotalStock,
  invTotalIn,
  invTotalOut,
  onInvSearchInput,
  onInvPageChange,
  selectCaseRow,
  selectedCaseName,
  showLogFilter,
  logFilterType,
  logFilterStart,
  logFilterEnd,
  logPage,
  logPerPage,
  logTotalPages,
  logIsLoading,
  logIsFetching,
  logRefetch,
  logList,
  onLogPageChange,
  clearLogFilter,
  logBadgeClass,
} = useCaseInventory()
</script>

<style scoped>
.ci-wrap {
  padding: 20px 24px;
  display: flex;
  flex-direction: column;
  gap: 16px;
}

/* Section（用于未选中提示） */
.ci-section {
  border: 1px solid var(--color-border-light, #e2e8f0);
  border-radius: 13px;
  overflow: hidden;
  background: white;
}

/* Empty hint */
.ci-empty-hint {
  text-align: center;
  color: var(--color-text-muted);
  padding: 32px 0;
}
.ci-empty-hint i {
  font-size: 28px;
  opacity: 0.3;
  display: block;
  margin-bottom: 8px;
}
</style>
