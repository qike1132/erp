<template>
  <div class="coq-panel">
    <CompletedOrdersTable
      :orders="orders"
      :loading="loading"
      :fetching="fetching"
      :error="error"
      :total="total"
      :current-page="currentPage"
      :total-pages="totalPages"
      @view-detail="onViewDetail"
      @update:current-page="onUpdateCurrentPage"
      @retry="onRetry"
    />
  </div>
</template>

<script setup lang="ts">
import type { PurchaseOrder } from '@/types'
import CompletedOrdersTable from './CompletedOrdersTable.vue'

defineProps<{
  orders: PurchaseOrder[]
  loading: boolean
  fetching?: boolean
  error?: boolean
  total: number
  currentPage: number
  totalPages: number
}>()

const emit = defineEmits<{
  viewDetail: [id: number]
  'update:currentPage': [page: number]
  retry: []
}>()

function onViewDetail(id: number) {
  emit('viewDetail', id)
}
function onUpdateCurrentPage(page: number) {
  emit('update:currentPage', page)
}
function onRetry() {
  emit('retry')
}
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
  padding-top: 16px;
}
</style>
