<template>
  <div class="ci-section">
    <div class="ci-section-header">
      <div class="ci-section-title">
        <FontAwesomeIcon icon="history" style="color: var(--color-primary-500)" aria-hidden="true" />
        库存流水记录 <small style="color: var(--color-text-muted)">- {{ selectedCaseName }}</small>
      </div>
      <button class="ci-action-btn ci-action-outline" @click="showLogFilterModel = !showLogFilterModel" aria-label="筛选">
        <FontAwesomeIcon icon="filter" style="margin-right: 4px" aria-hidden="true" />筛选
      </button>
    </div>
    <div v-if="showLogFilterModel" class="ci-filter-panel">
      <div class="ci-filter-row">
        <div class="ci-filter-field">
          <label class="ci-form-label">操作类型</label>
          <UiSelect v-model="logFilterTypeModel" placeholder="全部" :options="LOG_TYPE_OPTIONS" style="width: 140px" />
        </div>
        <div class="ci-filter-field">
          <label class="ci-form-label">开始日期</label>
          <UiDatePicker v-model="logFilterStartModel" style="width: 100%" />
        </div>
        <div class="ci-filter-field">
          <label class="ci-form-label">结束日期</label>
          <UiDatePicker v-model="logFilterEndModel" style="width: 100%" />
        </div>
        <div class="ci-filter-action">
          <button class="ci-action-btn ci-action-primary" @click="logPageModel = 1; logRefetch()" aria-label="查询">
            <FontAwesomeIcon icon="search" style="margin-right: 4px" aria-hidden="true" />查询
          </button>
          <button class="ci-action-btn ci-action-outline" style="margin-left: 8px" @click="clearLogFilter" aria-label="关闭">
            <FontAwesomeIcon icon="times" aria-hidden="true" />
          </button>
        </div>
      </div>
    </div>
    <div v-if="logIsLoading && logList.length === 0" class="ci-loading"><UiSpinner /></div>
    <template v-else>
      <div v-if="logIsFetching" class="ci-fetching-bar"><div class="ci-fetching-progress" /></div>
      <UiDataTable
        :data="logList"
        :columns="LOG_COLUMNS"
        :loading="logIsLoading"
        :paginator="logTotalPages > 1"
        :rows="logPerPage"
        :total-records="logTotalPages * logPerPage"
        row-key="id"
        @page="onLogPageChange"
      >
        <template #empty><div class="ci-empty"><FontAwesomeIcon icon="history" aria-hidden="true" /><span>暂无流水记录</span></div></template>
        <template #column-body-change_type="{ row }">
          <span :class="['ci-badge', logBadgeClass((row as InventoryLogItem).change_type)]">{{ (row as InventoryLogItem).change_type }}</span>
        </template>
        <template #column-body-change_quantity="{ row }">
          <strong :style="{ color: (row as InventoryLogItem).change_quantity >= 0 ? 'var(--color-success-500)' : 'var(--color-danger-500)' }">
            {{ (row as InventoryLogItem).change_quantity >= 0 ? '+' : '' }}{{ (row as InventoryLogItem).change_quantity }}
          </strong>
        </template>
        <template #column-body-customer="{ row }">{{ (row as InventoryLogItem).customer || '-' }}</template>
        <template #column-body-related_id="{ row }">{{ (row as InventoryLogItem).related_id || '-' }}</template>
        <template #column-body-change_date="{ row }"><small>{{ (row as InventoryLogItem).change_date }}</small></template>
        <template #column-body-note="{ row }"><small>{{ (row as InventoryLogItem).note || '-' }}</small></template>
      </UiDataTable>
    </template>
  </div>
</template>

<script setup lang="ts">
import UiSelect from '@/components/ui/UiSelect.vue'
import UiDatePicker from '@/components/ui/UiDatePicker.vue'
import UiDataTable from '@/components/ui/UiDataTable.vue'
import {
  LOG_COLUMNS,
  LOG_TYPE_OPTIONS,
  type InventoryLogItem,
} from '@/views/case/composables/useCaseInventory'

defineProps<{
  selectedCaseName: string
  logPerPage: number
  logTotalPages: number
  logIsLoading: boolean
  logIsFetching: boolean
  logList: InventoryLogItem[]
  onLogPageChange: (event: { page: number; rows: number }) => void
  logRefetch: () => void
  clearLogFilter: () => void
  logBadgeClass: (t: string) => string
}>()

const showLogFilterModel = defineModel<boolean>('showLogFilter', { default: false })
const logFilterTypeModel = defineModel<string>('logFilterType', { default: '' })
const logFilterStartModel = defineModel<string>('logFilterStart', { default: '' })
const logFilterEndModel = defineModel<string>('logFilterEnd', { default: '' })
const logPageModel = defineModel<number>('logPage', { default: 1 })
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
.ci-action-outline { }
.ci-action-btn:disabled { opacity: 0.4; cursor: not-allowed; }

.ci-filter-panel {
  border-bottom: 1px solid var(--color-border-light);
  padding: 12px 16px;
}
.ci-filter-row {
  display: flex;
  gap: 12px;
  flex-wrap: wrap;
  align-items: flex-end;
}
.ci-filter-field { flex: 0 0 auto; }
.ci-filter-action { display: flex; align-items: flex-end; }
.ci-form-label {
  display: block;
  font-size: 12px;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  color: var(--color-text-secondary);
  margin-bottom: 6px;
}

.ci-loading, .ci-empty {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  padding: 32px 0;
  color: var(--color-text-muted);
}
.ci-empty { flex-direction: column; }
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

.ci-badge {
  display: inline-block;
  padding: 4px 10px;
  border-radius: 16px;
  font-size: 12px;
  font-weight: 600;
}
.ci-badge-success { background: var(--color-success-50); color: var(--color-success-600); }
.ci-badge-danger { background: var(--color-danger-50); color: var(--color-danger-600); }
.ci-badge-warning { background: var(--color-warning-50); color: var(--color-warning-600); }
.ci-badge-info { background: var(--color-info-50); color: var(--color-info-600); }
</style>