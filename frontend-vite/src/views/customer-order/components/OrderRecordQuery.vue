<template>
  <div class="co-tab-content">
    <OrderRecordFilter
      v-model:keyword="keyword"
      :total-records="totalRecords"
      :is-loading="isLoadingRecords || isFetchingRecords"
      @search="search"
      @clear="clearKeyword"
    />
    <OrderRecordTable
      :order-records="orderRecords"
      :is-loading-records="isLoadingRecords"
      :is-fetching-records="isFetchingRecords"
      :error-message="errorMessage"
      :total-pages="totalPages"
      :total-records="totalRecords"
      :per-page="perPage"
      :can-delete="canDelete"
      :fetch-orders="fetchOrders"
      @view-detail="(r) => emit('view-detail', r)"
      @delete-record="(r) => emit('delete-record', r)"
      @update:per-page="(v) => emit('update:perPage', v)"
      @change-page="(p) => emit('change-page', p)"
      @retry="() => emit('retry')"
    />
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import OrderRecordFilter from './OrderRecordFilter.vue'
import OrderRecordTable from './OrderRecordTable.vue'
import type { OrderRecord } from '../composables/types'

const props = defineProps<{
  keyword: string
  orderRecords: OrderRecord[]
  isLoadingRecords: boolean
  isFetchingRecords: boolean
  errorMessage: string
  currentPage: number
  totalPages: number
  totalRecords: number
  perPage: number
  canDelete: boolean
  fetchOrders: () => void
  search: () => void
  clearKeyword: () => void
}>()

const emit = defineEmits<{
  'update:keyword': [value: string]
  'view-detail': [record: OrderRecord]
  'delete-record': [record: OrderRecord]
  'update:perPage': [value: number]
  'change-page': [page: number]
  retry: []
}>()

const keyword = computed({
  get: () => props.keyword,
  set: (v: string) => emit('update:keyword', v),
})
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
