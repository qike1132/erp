<template>
  <div class="ip-wrap">
    <!-- 统计卡 -->
    <div class="ip-stat-row">
      <UiStatCard accent="blue">
        <template #label>产品种类</template>
        {{ invTotal }}
      </UiStatCard>
      <UiStatCard accent="green">
        <template #label>当前总库存</template>
        {{ invStats?.total_stock ?? 0 }}
      </UiStatCard>
      <UiStatCard accent="purple">
        <template #label>累计入库</template>
        {{ invStats?.total_in ?? 0 }}
      </UiStatCard>
      <UiStatCard accent="red">
        <template #label>累计出库</template>
        {{ invStats?.total_out ?? 0 }}
      </UiStatCard>
    </div>

    <!-- 库存表 -->
    <div class="ip-section">
      <div class="ip-header">
        <div class="ip-title">
          <FontAwesomeIcon icon="warehouse" style="color: var(--color-primary-500)" aria-hidden="true" />
          皮套库存
        </div>
        <div class="ip-actions">
          <UiSearchInput v-model="invSearch" placeholder="搜索产品名称或69码" @search="onInvSearchInput" />
          <button class="ip-btn ip-btn-ghost" aria-label="刷新" @click="invRefetch()">
            <FontAwesomeIcon icon="sync-alt" style="margin-right: 4px" aria-hidden="true" />刷新
          </button>
        </div>
      </div>

      <div v-if="invIsFetching && inventoryList.length" class="ip-fetching-bar"><div class="ip-fetching-progress" /></div>
      <UiDataTable
        :data="inventoryList"
        :columns="INVENTORY_COLUMNS"
        :loading="invIsLoading && !inventoryList.length"
        :paginator="invTotalPages > 1"
        :rows="invPerPage"
        :total-records="invTotalPages * invPerPage"
        row-key="id"
        @page="onInvPageChange"
        @row-click="openLogDrawer"
      >
        <template #empty>
          <div class="ip-empty"><FontAwesomeIcon icon="warehouse" aria-hidden="true" /><span>暂无库存数据</span></div>
        </template>
        <template #column-body-name="{ row }"><strong class="ip-name">{{ row.name }}</strong></template>
        <template #column-body-barcode="{ row }"><small class="ip-barcode">{{ row.barcode || '-' }}</small></template>
        <template #column-body-total_in="{ row }"><span class="ip-in">{{ row.total_in }}</span></template>
        <template #column-body-total_out="{ row }"><span class="ip-out">{{ row.total_out }}</span></template>
        <template #column-body-current_stock="{ row }">
          <span :class="['ip-stock', { 'ip-stock-zero': row.current_stock <= 0 }]">{{ row.current_stock }}</span>
        </template>
        <template #column-body-actions="{ row }">
          <button class="ip-btn ip-btn-ghost" aria-label="查看流水" @click.stop="openLogDrawer(row)">
            <FontAwesomeIcon icon="history" style="margin-right: 2px" aria-hidden="true" />流水
          </button>
        </template>
      </UiDataTable>
    </div>

    <!-- 流水抽屉 -->
    <InventoryLogDrawer
      v-model:visible="drawerOpen"
      v-model:log-filter-type="logFilterType"
      v-model:log-filter-start="logFilterStart"
      v-model:log-filter-end="logFilterEnd"
      :selected-case="selectedCase"
      :log-total-pages="logTotalPages"
      :log-per-page="logPerPage"
      :log-is-loading="logIsLoading"
      :log-is-fetching="logIsFetching"
      :log-list="logList"
      :on-log-page-change="onLogPageChange"
      :search-logs="searchLogs"
      :clear-log-filter="clearLogFilter"
    />
  </div>
</template>

<script setup lang="ts">
/**
 * InventoryPanel — 皮套库存查询：统计卡 + 产品库存表 + 单产品流水抽屉。
 * 行点击（或「流水」按钮）打开该产品流水。
 */
import UiStatCard from '@/components/ui/UiStatCard.vue'
import UiDataTable from '@/components/ui/UiDataTable.vue'
import UiSearchInput from '@/components/ui/UiSearchInput.vue'
import InventoryLogDrawer from './InventoryLogDrawer.vue'
import { useCaseInventory, INVENTORY_COLUMNS } from '../composables/useCaseInventory'

const {
  invSearch,
  invPerPage,
  invIsLoading,
  invIsFetching,
  invRefetch,
  inventoryList,
  invTotal,
  invTotalPages,
  invStats,
  onInvSearchInput,
  onInvPageChange,
  openLogDrawer,
  selectedCase,
  drawerOpen,
  logFilterType,
  logFilterStart,
  logFilterEnd,
  logTotalPages,
  logPerPage,
  logIsLoading,
  logIsFetching,
  logList,
  onLogPageChange,
  searchLogs,
  clearLogFilter,
} = useCaseInventory()
</script>

<style scoped>
.ip-wrap {
  display: flex;
  flex-direction: column;
  gap: 16px;
}
.ip-stat-row {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 12px;
}
@media (max-width: 768px) {
  .ip-stat-row { grid-template-columns: repeat(2, 1fr); }
}

.ip-section {
  border: 1px solid var(--color-border-light, #e2e8f0);
  border-radius: 13px;
  overflow: hidden;
  background: var(--color-surface-card, white);
}
.ip-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 12px 16px;
  border-bottom: 1px solid var(--color-border-light, #f1f5f9);
  flex-wrap: wrap;
  gap: 8px;
}
.ip-title {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 14px;
  font-weight: 700;
  color: var(--color-text);
}
.ip-actions { display: flex; gap: 8px; align-items: center; }

.ip-btn {
  padding: 6px 12px;
  border-radius: 9px;
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
  display: inline-flex;
  align-items: center;
}
.ip-btn-ghost {
  border: 2px solid var(--color-border-light, #e2e8f0);
  background: white;
  color: var(--color-text-secondary);
}
.ip-btn-ghost:hover { background: var(--color-primary-50); color: var(--color-primary-600); }

.ip-name { color: var(--color-text); }
.ip-barcode { color: var(--color-text-muted); }
.ip-in { color: var(--color-success-600); font-weight: 600; }
.ip-out { color: var(--color-danger-500); font-weight: 600; }
.ip-stock { color: var(--color-primary-600); font-weight: 800; font-variant-numeric: tabular-nums; }
.ip-stock-zero { color: var(--color-danger-500); }

.ip-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
  padding: 32px 0;
  color: var(--color-text-muted);
}
.ip-empty i { font-size: 28px; opacity: 0.5; }

.ip-fetching-bar {
  height: 2px;
  background: var(--color-primary-100, #e0f2fe);
  overflow: hidden;
}
.ip-fetching-progress {
  height: 100%;
  width: 30%;
  background: var(--color-primary-500);
  animation: ip-slide 1s ease-in-out infinite;
}
@keyframes ip-slide {
  0% { transform: translateX(-100%); }
  100% { transform: translateX(400%); }
}
</style>
