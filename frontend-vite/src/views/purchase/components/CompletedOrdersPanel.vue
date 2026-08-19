<template>
  <div class="coq-panel">
    <CompletedOrdersToolbar
      :total="total"
      :filter-expanded="filterExpanded"
      @toggle-filter="filterExpanded = !filterExpanded"
      @export="$emit('export')"
    />

    <CompletedOrdersSearchBar
      :filters="filters"
      :quick-filters="quickFilters"
      :current-quick-filter-id="currentQuickFilterId"
      @update-filter="(p) => $emit('updateFilter', p)"
      @search="$emit('search')"
      @apply-quick-filter="(id) => $emit('applyQuickFilter', id)"
    />

    <CompletedOrdersAdvancedFilter
      :filters="filters"
      :filter-expanded="filterExpanded"
      @update-filter="(p) => $emit('updateFilter', p)"
      @reset-filters="$emit('resetFilters')"
    />

    <CompletedOrdersTable
      :orders="orders"
      :loading="loading"
      :fetching="fetching"
      :total="total"
      :current-page="currentPage"
      :total-pages="totalPages"
      @view-detail="(id) => $emit('viewDetail', id)"
      @update:current-page="(p) => $emit('update:currentPage', p)"
    />
  </div>
</template>

<script setup lang="ts">
import type { PurchaseOrder } from '@/types'
import type { QuickFilter } from '../composables/useCompletedOrders'
import CompletedOrdersToolbar from './CompletedOrdersToolbar.vue'
import CompletedOrdersSearchBar from './CompletedOrdersSearchBar.vue'
import CompletedOrdersAdvancedFilter from './CompletedOrdersAdvancedFilter.vue'
import CompletedOrdersTable from './CompletedOrdersTable.vue'

defineProps<{
  orders: PurchaseOrder[]
  loading: boolean
  fetching?: boolean
  total: number
  currentPage: number
  totalPages: number
  filters: Record<string, string>
  quickFilters: QuickFilter[]
  currentQuickFilterId: string | null
}>()

const filterExpanded = defineModel<boolean>('filterExpanded', { default: false })

defineEmits<{
  updateFilter: [payload: { key: string; value: string }]
  resetFilters: []
  search: []
  export: []
  applyQuickFilter: [id: string]
  viewDetail: [id: number]
  'update:currentPage': [page: number]
}>()
</script>

<style scoped>
.coq-panel {
  --coq-navy: var(--color-primary-700, #2d5ab8);
  --coq-navy-deep: var(--color-primary-800, #234996);
  --coq-blue: var(--color-primary-500, #5b8def);
  --coq-blue-light: var(--color-primary-50, #eff5ff);
  --coq-amber: var(--color-warning-500, #ff9f43);
  --coq-green: var(--color-success-600, #1e9e55);
  --coq-red: var(--color-danger-600, #e53e3e);
  --coq-slate: #64748b;
  --coq-slate-light: #94a3b8;
  --coq-border: #e2e8f0;
  --coq-border-light: #f1f5f9;
  --coq-bg: #ffffff;
  --coq-bg-soft: #f8fafc;
  --coq-text: #0f172a;
  --coq-text-secondary: #475569;
  --coq-text-muted: #94a3b8;
  font-family: var(--font-sans);
  color: var(--coq-text);
  background: var(--coq-bg);
}
</style>
