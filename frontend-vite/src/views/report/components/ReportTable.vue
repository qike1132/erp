<template>
  <div class="rp-table-wrap">
    <div v-if="isFetching" class="rp-fetching-bar"><div class="rp-fetching-progress" /></div>
    <UiDataTable
      :data="logs"
      :columns="columns"
      :loading="isLoading && searched && !logs.length"
      :paginator="(pagination?.pages ?? 0) > 1"
      :rows="perPage"
      :total-records="pagination?.total ?? 0"
      row-key="id"
      @page="emit('page', $event)"
    >
      <template #empty>
        <div class="rp-empty">
          <FontAwesomeIcon icon="chart-line" aria-hidden="true" />
          <span>{{ isFetching ? '加载中…' : '暂无数据' }}</span>
        </div>
      </template>
      <template #column-body-date="{ row }">
        {{ (row as Record<string, unknown>)[currentCfg.dateKey] || '-' }}
      </template>
      <template #column-body-customer="{ row }">
        {{ (row as Record<string, unknown>).customer || '-' }}
      </template>
      <template #column-body-product_name="{ row }">
        {{ (row as Record<string, unknown>).product_name || '-' }}
      </template>
      <template #column-body-quantity="{ row }">
        {{ (row as Record<string, unknown>).quantity }}
      </template>
      <template #column-body-note="{ row }">
        <span :title="String((row as Record<string, unknown>)[currentCfg.noteKey] || '')">{{ (row as Record<string, unknown>)[currentCfg.noteKey] || '-' }}</span>
      </template>
    </UiDataTable>
  </div>
</template>

<script setup lang="ts">
import UiDataTable from '@/components/ui/UiDataTable.vue'
import type { TableColumn } from '@/components/ui/UiDataTable.vue'
import type { TabConfig } from '../composables/useReportConfig'

defineProps<{
  logs: Record<string, unknown>[]
  columns: TableColumn[]
  isLoading: boolean
  isFetching: boolean
  searched: boolean
  perPage: number
  pagination: { pages?: number; total?: number } | undefined
  currentCfg: TabConfig
}>()

const emit = defineEmits<{
  'page': [event: { page: number; rows: number }]
}>()
</script>

<style scoped>
.rp-table-wrap {
  flex: 1;
  overflow-y: auto;
  min-height: 0;
}
.rp-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 10px;
  padding: 40px 20px;
  color: var(--color-text-muted);
}
.rp-empty i { font-size: 28px; opacity: 0.5; }
.rp-empty span { font-size: 14px; }
.rp-fetching-bar {
  height: 2px;
  background: var(--color-primary-100, #e0f2fe);
  overflow: hidden;
  border-radius: 1px;
}
.rp-fetching-progress {
  height: 100%;
  width: 30%;
  background: var(--color-primary-500, #3b82f6);
  border-radius: 1px;
  animation: rp-progress-slide 1s ease-in-out infinite;
}
@keyframes rp-progress-slide {
  0% { transform: translateX(-100%); }
  100% { transform: translateX(400%); }
}
</style>