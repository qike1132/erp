<template>
  <div class="co-tab-content">
    <OrderRecordTable
      :order-records="orderRecords"
      :is-loading-records="isLoadingRecords"
      :is-fetching-records="isFetchingRecords"
      :error-message="errorMessage"
      :total-pages="totalPages"
      :total-records="totalRecords"
      :per-page="perPage"
      :can-manage="canManage"
      :fetch-orders="fetchOrders"
      @view-detail="(r) => emit('view-detail', r)"
      @delete-record="(r) => emit('delete-record', r)"
      @edit-stockin="(r) => emit('edit-stockin', r)"
      @delete-stockin="(r) => emit('delete-stockin', r)"
      @update:per-page="(v) => emit('update:perPage', v)"
      @change-page="(p) => emit('change-page', p)"
      @retry="() => emit('retry')"
    />
  </div>
</template>

<script setup lang="ts">
/**
 * OrderRecordQuery.vue — 「记录查询」TAB 的内容区
 *
 * 2026-10-01：搜索工具条（原 OrderRecordFilter 那一行）上移到卡片页头，
 * 本组件只剩表格；关键词等搜索态由 CustomerOrderView 直接交给页头里的
 * OrderRecordFilter，不再从这里透传。
 */
import OrderRecordTable from './OrderRecordTable.vue'
import type { OrderRecord } from '../composables/types'

defineProps<{
  orderRecords: OrderRecord[]
  isLoadingRecords: boolean
  isFetchingRecords: boolean
  errorMessage: string
  currentPage: number
  totalPages: number
  totalRecords: number
  perPage: number
  canManage: boolean
  fetchOrders: () => void
}>()

const emit = defineEmits<{
  'view-detail': [record: OrderRecord]
  'delete-record': [record: OrderRecord]
  'edit-stockin': [record: OrderRecord]
  'delete-stockin': [record: OrderRecord]
  'update:perPage': [value: number]
  'change-page': [page: number]
  retry: []
}>()
</script>

<style scoped>
.co-tab-content {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-height: 0;
  overflow: hidden;
}
</style>
