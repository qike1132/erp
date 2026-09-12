<template>
  <UiDrawer v-model:visible="visibleModel" title="库存流水" width="640px">
    <template #header>
      <div class="ild-header">
        <div>
          <div class="ild-title">库存流水</div>
          <div class="ild-sub">
            <strong>{{ selectedCase?.name }}</strong>
            <span v-if="selectedCase?.barcode" class="ild-barcode">{{ selectedCase.barcode }}</span>
          </div>
        </div>
      </div>
    </template>

    <!-- 筛选 -->
    <div class="ild-filter">
      <div class="ild-filter-row">
        <UiSelect v-model="logFilterType" placeholder="全部类型" :options="LOG_TYPE_OPTIONS" style="width: 130px" />
        <UiDatePicker v-model="logFilterStart" style="width: 130px" />
        <UiDatePicker v-model="logFilterEnd" style="width: 130px" />
        <button class="ild-btn ild-btn-primary" aria-label="查询" @click="searchLogs()">
          <FontAwesomeIcon icon="search" style="margin-right: 4px" aria-hidden="true" />查询
        </button>
        <button class="ild-btn ild-btn-ghost" aria-label="重置" @click="clearLogFilter()">重置</button>
      </div>
    </div>

    <div v-if="logIsFetching && logList.length" class="ild-fetching-bar"><div class="ild-fetching-progress" /></div>
    <UiDataTable
      :data="logList"
      :columns="LOG_COLUMNS"
      :loading="logIsLoading && !logList.length"
      :paginator="logTotalPages > 1"
      :rows="logPerPage"
      :total-records="logTotalPages * logPerPage"
      row-key="id"
      striped
      @page="onLogPageChange"
    >
      <template #empty>
        <div class="ild-empty"><FontAwesomeIcon icon="history" aria-hidden="true" /><span>暂无流水记录</span></div>
      </template>
      <template #column-body-change_type="{ row }">
        <span :class="['ild-badge', logBadgeClass(row.change_type)]">{{ row.change_type }}</span>
      </template>
      <template #column-body-change_quantity="{ row }">
        <strong :style="{ color: row.change_quantity >= 0 ? 'var(--color-success-600)' : 'var(--color-danger-500)' }">
          {{ row.change_quantity >= 0 ? '+' : '' }}{{ row.change_quantity }}
        </strong>
      </template>
      <template #column-body-customer="{ row }">{{ row.customer || '-' }}</template>
      <template #column-body-related_id="{ row }"><small>{{ row.related_id || '-' }}</small></template>
      <template #column-body-change_date="{ row }"><small class="ild-date">{{ row.change_date }}</small></template>
      <template #column-body-note="{ row }"><small>{{ row.note || '-' }}</small></template>
    </UiDataTable>
  </UiDrawer>
</template>

<script setup lang="ts">
/**
 * InventoryLogDrawer — 单产品库存流水抽屉（类型/日期筛选 + 分页）。
 */
import UiDrawer from '@/components/ui/UiDrawer.vue'
import UiDataTable from '@/components/ui/UiDataTable.vue'
import UiSelect from '@/components/ui/UiSelect.vue'
import UiDatePicker from '@/components/ui/UiDatePicker.vue'
import { LOG_COLUMNS, LOG_TYPE_OPTIONS, logBadgeClass, type CaseInventoryLogItem } from '../composables/useCaseInventory'

defineProps<{
  /** 当前查看流水的产品（null 时抽屉关闭） */
  selectedCase: { id: number; name: string; barcode?: string } | null
  logTotalPages: number
  logPerPage: number
  logIsLoading: boolean
  logIsFetching: boolean
  logList: CaseInventoryLogItem[]
  onLogPageChange: (event: { page: number; rows: number }) => void
  searchLogs: () => void
  clearLogFilter: () => void
}>()

const visibleModel = defineModel<boolean>('visible', { default: false })
const logFilterType = defineModel<string>('logFilterType', { default: '' })
const logFilterStart = defineModel<string>('logFilterStart', { default: '' })
const logFilterEnd = defineModel<string>('logFilterEnd', { default: '' })
</script>

<style scoped>
.ild-header { display: flex; align-items: center; }
.ild-title { font-size: 16px; font-weight: 700; color: var(--color-text); }
.ild-sub { margin-top: 2px; font-size: 13px; color: var(--color-text-secondary); display: flex; gap: 8px; align-items: center; }
.ild-barcode { color: var(--color-text-muted); font-size: 12px; }
.ild-filter { margin-bottom: 12px; }
.ild-filter-row { display: flex; gap: 8px; flex-wrap: wrap; align-items: center; }
.ild-btn {
  padding: 6px 12px;
  border-radius: 9px;
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
  display: inline-flex;
  align-items: center;
}
.ild-btn-primary { border: none; background: linear-gradient(135deg, var(--color-primary-500), var(--color-primary-700)); color: white; }
.ild-btn-ghost { border: 2px solid var(--color-border-light, #e2e8f0); background: white; color: var(--color-text-secondary); }
.ild-btn-ghost:hover { background: var(--color-surface, #f8fafc); }
.ild-fetching-bar { height: 2px; background: var(--color-primary-100, #e0f2fe); overflow: hidden; margin-bottom: 8px; }
.ild-fetching-progress { height: 100%; width: 30%; background: var(--color-primary-500); animation: ild-slide 1s ease-in-out infinite; }
@keyframes ild-slide { 0% { transform: translateX(-100%); } 100% { transform: translateX(400%); } }
.ild-empty {
  display: flex; flex-direction: column; align-items: center; gap: 8px;
  padding: 32px 0; color: var(--color-text-muted);
}
.ild-empty i { font-size: 28px; opacity: 0.5; }
.ild-badge { padding: 2px 10px; border-radius: 16px; font-size: 11px; font-weight: 600; }
.ild-badge-success { background: var(--color-success-50); color: var(--color-success-600); }
.ild-badge-danger { background: var(--color-danger-50); color: var(--color-danger-600); }
.ild-badge-warning { background: var(--color-warning-50); color: var(--color-warning-600); }
.ild-badge-info { background: var(--color-info-50); color: var(--color-info-700); }
.ild-date { color: var(--color-text-secondary); }
</style>