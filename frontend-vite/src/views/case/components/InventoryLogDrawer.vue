<template>
  <UiDrawer v-model:visible="visibleModel" title="出入库流水" width="640px">
    <template #header>
      <div class="ild-header">
        <div>
          <div class="ild-title">出入库流水</div>
          <div class="ild-sub">
            <strong>{{ selectedCase?.name }}</strong>
            <span v-if="selectedCase?.barcode" class="ild-barcode">{{ selectedCase.barcode }}</span>
          </div>
        </div>
      </div>
    </template>

    <div v-if="logIsFetching && logList.length" class="ild-fetching-bar"><div class="ild-fetching-progress" /></div>
    <UiDataTable
      :data="logList"
      :columns="MOVEMENT_COLUMNS"
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
      <template #column-body-direction="{ row }">
        <span :class="['ild-badge', row.direction === 'in' ? 'ild-badge-success' : 'ild-badge-danger']">
          {{ directionLabel(row.direction) }}
        </span>
      </template>
      <template #column-body-quantity="{ row }">
        <strong :style="{ color: row.direction === 'in' ? 'var(--color-success-600)' : 'var(--color-danger-500)' }">
          {{ row.direction === 'in' ? '+' : '-' }}{{ row.quantity }}
        </strong>
      </template>
      <template #column-body-movement_date="{ row }"><small class="ild-date">{{ row.movement_date }}</small></template>
      <template #column-body-note="{ row }"><small>{{ row.note || '-' }}</small></template>
    </UiDataTable>
  </UiDrawer>
</template>

<script setup lang="ts">
/**
 * InventoryLogDrawer — 单 SKU 出入库流水抽屉（服务端分页）。
 */
import UiDrawer from '@/components/ui/UiDrawer.vue'
import UiDataTable from '@/components/ui/UiDataTable.vue'
import { MOVEMENT_COLUMNS, directionLabel, type CaseMovement } from '../composables/useCaseInventory'

defineProps<{
  /** 当前查看流水的 SKU（null 时抽屉关闭） */
  selectedCase: { id: number; name: string; barcode?: string } | null
  logTotalPages: number
  logPerPage: number
  logIsLoading: boolean
  logIsFetching: boolean
  logList: CaseMovement[]
  onLogPageChange: (event: { page: number; rows: number }) => void
}>()

const visibleModel = defineModel<boolean>('visible', { default: false })
</script>

<style scoped>
.ild-header { display: flex; align-items: center; }
.ild-title { font-size: 16px; font-weight: 700; color: var(--color-text); }
.ild-sub { margin-top: 2px; font-size: 13px; color: var(--color-text-secondary); display: flex; gap: 8px; align-items: center; }
.ild-barcode { color: var(--color-text-muted); font-size: 12px; }
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
.ild-date { color: var(--color-text-secondary); }
</style>
