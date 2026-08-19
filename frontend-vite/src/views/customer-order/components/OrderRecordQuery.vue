<template>
  <div class="co-tab-content">
    <OrderRecordFilter
      v-model:show-filter="showFilter"
      v-model:filter-customer="filterCustomer"
      v-model:filter-order-type="filterOrderType"
      v-model:filter-status="filterStatus"
      v-model:filter-factory="filterFactory"
      v-model:filter-start="filterStart"
      v-model:filter-end="filterEnd"
      :record-type="recordType"
      :record-type-options="recordTypeOptions"
      :customer-options="customerOptions"
      :filter-order-type-options="filterOrderTypeOptions"
      :factory-options="factoryOptions"
      :factory-disabled="factoryDisabled"
      :status-options="statusOptions"
      @change-record-type="(v) => emit('change-record-type', v)"
      @search="fetchOrders"
      @reset="resetFilter"
    />
    <OrderRecordTable
      :record-type="recordType"
      :order-records="orderRecords"
      :is-loading-records="isLoadingRecords"
      :is-fetching-records="isFetchingRecords"
      :total-pages="totalPages"
      :per-page="perPage"
      :fetch-orders="fetchOrders"
      @view-detail="(r) => emit('view-detail', r)"
      @update:per-page="(v) => emit('update:perPage', v)"
      @change-page="(p) => emit('change-page', p)"
    />
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import OrderRecordFilter from './OrderRecordFilter.vue'
import OrderRecordTable from './OrderRecordTable.vue'
import type { OrderRecord } from '../composables/types'

const props = defineProps<{
  recordType: 'order' | 'stockin'
  recordTypeOptions: { label: string; value: 'order' | 'stockin' }[]
  customerOptions: { label: string; value: string }[]
  filterOrderTypeOptions: { label: string; value: string }[]
  factoryOptions: { label: string; value: string }[]
  factoryDisabled: boolean
  statusOptions: { label: string; value: string }[]
  orderRecords: OrderRecord[]
  isLoadingRecords: boolean
  isFetchingRecords: boolean
  currentPage: number
  totalPages: number
  perPage: number
  showFilter: boolean
  filterCustomer: string
  filterOrderType: string
  filterStatus: string
  filterFactory: string
  filterStart: string
  filterEnd: string
  fetchOrders: () => void
  resetFilter: () => void
}>()

const emit = defineEmits<{
  'update:showFilter': [value: boolean]
  'update:filterCustomer': [value: string]
  'update:filterOrderType': [value: string]
  'update:filterStatus': [value: string]
  'update:filterFactory': [value: string]
  'update:filterStart': [value: string]
  'update:filterEnd': [value: string]
  'change-record-type': [value: 'order' | 'stockin']
  'view-detail': [record: OrderRecord]
  'update:perPage': [value: number]
  'change-page': [page: number]
}>()

const showFilter = computed({
  get: () => props.showFilter,
  set: (v: boolean) => emit('update:showFilter', v),
})
const filterCustomer = computed({
  get: () => props.filterCustomer,
  set: (v: string) => emit('update:filterCustomer', v),
})
const filterOrderType = computed({
  get: () => props.filterOrderType,
  set: (v: string) => emit('update:filterOrderType', v),
})
const filterStatus = computed({
  get: () => props.filterStatus,
  set: (v: string) => emit('update:filterStatus', v),
})
const filterFactory = computed({
  get: () => props.filterFactory,
  set: (v: string) => emit('update:filterFactory', v),
})
const filterStart = computed({
  get: () => props.filterStart,
  set: (v: string) => emit('update:filterStart', v),
})
const filterEnd = computed({
  get: () => props.filterEnd,
  set: (v: string) => emit('update:filterEnd', v),
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
