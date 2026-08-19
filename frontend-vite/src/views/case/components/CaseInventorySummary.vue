<template>
  <div class="ci-section">
    <div class="ci-section-header">
      <div class="ci-section-title">
        <FontAwesomeIcon icon="warehouse" style="color: var(--color-primary-500)" aria-hidden="true" />
        皮套库存汇总
      </div>
      <div class="ci-header-actions">
        <UiSearchInput v-model="invSearchModel" placeholder="搜索产品名称或69码..." @search="onInvSearchInput" />
        <button class="ci-action-btn ci-action-primary" @click="invRefetch()" aria-label="刷新">
          <FontAwesomeIcon icon="sync-alt" style="margin-right: 4px" aria-hidden="true" />刷新
        </button>
      </div>
    </div>

    <!-- 统计卡片 -->
    <div class="ci-stat-row">
      <div class="ci-stat-card ci-stat-success">
        <div class="ci-stat-value">{{ invTotalStock }}</div>
        <div class="ci-stat-label">当前总库存</div>
      </div>
      <div class="ci-stat-card ci-stat-primary">
        <div class="ci-stat-value">{{ invTotalIn }}</div>
        <div class="ci-stat-label">累计入库</div>
      </div>
      <div class="ci-stat-card ci-stat-danger">
        <div class="ci-stat-value">{{ invTotalOut }}</div>
        <div class="ci-stat-label">累计出库</div>
      </div>
    </div>

    <!-- 库存表格 -->
    <div v-if="invIsFetching" class="ci-fetching-bar"><div class="ci-fetching-progress" /></div>
    <UiDataTable
      :data="inventoryList"
      :columns="INVENTORY_COLUMNS"
      :loading="invIsLoading && inventoryList.length === 0"
      :paginator="invTotalPages > 1"
      :rows="invPerPage"
      :total-records="invTotalPages * invPerPage"
      row-key="id"
      @page="onInvPageChange"
      @rowClick="(row: InventorySummaryItem) => selectCaseRow(row)"
    >
      <template #empty>
        <div class="ci-empty"><FontAwesomeIcon icon="warehouse" aria-hidden="true" /><span>暂无库存数据</span></div>
      </template>
      <template #column-body-name="{ row }"><strong>{{ (row as InventorySummaryItem).name }}</strong></template>
      <template #column-body-barcode="{ row }"><small>{{ (row as InventorySummaryItem).barcode || '-' }}</small></template>
      <template #column-body-total_in="{ row }"><span style="color: var(--color-success-500)">{{ (row as InventorySummaryItem).total_in }}</span></template>
      <template #column-body-total_out="{ row }"><span style="color: var(--color-danger-500)">{{ (row as InventorySummaryItem).total_out }}</span></template>
      <template #column-body-current_stock="{ row }">
        <strong :style="{ color: (row as InventorySummaryItem).current_stock < 0 ? 'var(--color-danger-500)' : 'var(--color-primary-500)' }">{{ (row as InventorySummaryItem).current_stock }}</strong>
      </template>
      <template #column-body-actions="{ row }">
        <button class="ci-icon-btn ci-icon-info" @click.stop="selectCaseRow(row as InventorySummaryItem)" aria-label="流水">
          <FontAwesomeIcon icon="history" style="margin-right: 2px" aria-hidden="true" />流水
        </button>
      </template>
    </UiDataTable>
  </div>
</template>

<script setup lang="ts">
import UiDataTable from '@/components/ui/UiDataTable.vue'
import {
  INVENTORY_COLUMNS,
  type InventorySummaryItem,
} from '@/views/case/composables/useCaseInventory'

defineProps<{
  invPerPage: number
  invIsLoading: boolean
  invIsFetching: boolean
  invTotalPages: number
  invTotalStock: number
  invTotalIn: number
  invTotalOut: number
  inventoryList: InventorySummaryItem[]
  onInvSearchInput: () => void
  onInvPageChange: (event: { page: number; rows: number }) => void
  invRefetch: () => void
  selectCaseRow: (row: InventorySummaryItem) => void
}>()

const invSearchModel = defineModel<string>('invSearch', { default: '' })
</script>

<style scoped>
.ci-section {
  border: 1px solid var(--color-border-light, #e2e8f0);
  border-radius: 13px;
  overflow: hidden;
  background: white;
}
.ci-section-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 12px 16px;
  border-bottom: 1px solid var(--color-border-light, #f1f5f9);
}
.ci-section-title {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 14px;
  font-weight: 700;
  color: var(--color-text);
}
.ci-section-title i { font-size: 14px; }
.ci-header-actions {
  display: flex;
  gap: 8px;
  align-items: center;
}

.ci-action-btn {
  padding: 6px 12px;
  border: 2px solid var(--color-border-light, #e2e8f0);
  border-radius: 9px;
  background: white;
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
  transition: background 0.3s ease, border-color 0.3s ease, transform 0.3s ease;
  color: var(--color-text-secondary);
}
.ci-action-primary { color: var(--color-primary-600); }
.ci-action-primary:hover:not(:disabled) { background: var(--color-primary-50); border-color: var(--color-primary-300); transform: translateY(-1px); }
.ci-action-btn:disabled { opacity: 0.4; cursor: not-allowed; }

.ci-stat-row {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 12px;
  padding: 16px;
  border-bottom: 1px solid var(--color-border-light, #f1f5f9);
}
.ci-stat-card {
  border-radius: 13px;
  padding: 16px;
  text-align: center;
  border: 1px solid transparent;
  transition: box-shadow 0.4s cubic-bezier(0.4, 0, 0.2, 1), transform 0.4s cubic-bezier(0.4, 0, 0.2, 1);
}
.ci-stat-card:hover {
  box-shadow: 0 4px 12px rgba(0,0,0,0.06);
  transform: translateY(-2px);
}
.ci-stat-value {
  font-size: 28px;
  font-weight: 800;
  margin-bottom: 4px;
  font-variant-numeric: tabular-nums;
}
.ci-stat-label {
  font-size: 12px;
  color: var(--color-text-secondary);
}
.ci-stat-success { background: var(--color-success-50); border-color: var(--color-success-200); }
.ci-stat-success .ci-stat-value { color: var(--color-success-600); }
.ci-stat-primary { background: var(--color-primary-50); border-color: var(--color-primary-200); }
.ci-stat-primary .ci-stat-value { color: var(--color-primary-600); }
.ci-stat-danger { background: var(--color-danger-50); border-color: var(--color-danger-200); }
.ci-stat-danger .ci-stat-value { color: var(--color-danger-600); }

.ci-icon-btn {
  border: none;
  border-radius: 7px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  font-size: 12px;
  transition: background 0.2s ease;
  padding: 4px 8px;
  gap: 4px;
}
.ci-icon-info { background: var(--color-info-50); color: var(--color-info-700); }
.ci-icon-info:hover { background: var(--color-info-100); }

.ci-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 8px;
  padding: 32px 0;
  color: var(--color-text-muted);
}
.ci-empty i { font-size: 28px; opacity: 0.5; }

.ci-fetching-bar {
  height: 2px;
  background: var(--color-primary-100, #e0f2fe);
  overflow: hidden;
  border-radius: 1px;
}
.ci-fetching-progress {
  height: 100%;
  width: 30%;
  background: var(--color-primary-500, #3b82f6);
  border-radius: 1px;
  animation: ci-progress-slide 1s ease-in-out infinite;
}
@keyframes ci-progress-slide {
  0% { transform: translateX(-100%); }
  100% { transform: translateX(400%); }
}
</style>