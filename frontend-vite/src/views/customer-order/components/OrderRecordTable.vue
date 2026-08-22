<template>
  <div class="co-records-body">
    <template v-if="isFetchingRecords && orderRecords.length > 0">
      <div class="co-fetching-bar"><div class="co-fetching-progress" /></div>
    </template>
    <UiDataTable
      :data="orderRecords"
      :columns="orderColumns"
      :loading="isLoadingRecords && orderRecords.length === 0"
      :paginator="totalPages > 1"
      :rows="perPage"
      :total-records="totalPages * perPage"
      row-key="id"
      @page="onPageChange"
    >
      <template #empty>
        <div class="co-state-placeholder co-state-empty">
          <div class="co-empty-illustration"><FontAwesomeIcon icon="clipboard-list" aria-hidden="true" /></div>
          <p class="co-state-text">暂无{{ recordType === 'stockin' ? '备货' : '订单' }}记录</p>
        </div>
      </template>
      <template #column-body-order_date="{ row }">
        <span class="co-cell-muted">{{ (row as OrderRecord).order_date }}</span>
      </template>
      <template #column-body-order_no="{ row }">
        <span :class="['co-type-badge', (row as OrderRecord).record_type === 'stockin' ? 'stockin' : 'order']">
          {{ (row as OrderRecord).record_type === 'stockin' ? '备货' : '订单' }}
        </span>
        <span class="co-cell-muted" style="margin-left: 4px;">{{ (row as OrderRecord).order_no }}</span>
      </template>
      <template #column-body-customer="{ row }">
        <span class="co-cell-main">{{ (row as OrderRecord).customer }}</span>
      </template>
      <template #column-body-factories="{ row }">
        <span class="co-cell-muted">{{ (row as OrderRecord).factories?.join(', ') || '-' }}</span>
      </template>
      <template #column-body-sku_count="{ row }">
        <span class="co-badge-tag" :class="((row as OrderRecord).items?.length || 1) > 1 ? 'co-badge-success' : 'co-badge-muted'">
          {{ (row as OrderRecord).items?.length || 1 }}
        </span>
      </template>
      <template #column-body-product="{ row }">
        <span class="co-cell-main">{{ (row as OrderRecord).product?.name || '-' }}</span>
        <span v-if="(row as OrderRecord).product?.barcode" class="co-cell-muted" style="display: block; font-size: 11px;">{{ (row as OrderRecord).product?.barcode }}</span>
      </template>
      <template #column-body-quantity="{ row }">
        <strong>{{ (row as OrderRecord).quantity }}</strong>
      </template>
      <template #column-body-deduct="{ row }">
        <span v-if="((row as OrderRecord).deduct_quantity ?? 0) > 0" class="co-badge-tag co-badge-success">
          {{ recordType === 'stockin' ? '已抵扣' : '抵扣' }}: {{ (row as OrderRecord).deduct_quantity }}
        </span>
      </template>
      <template #column-body-actions="{ row }">
        <div class="co-action-group">
          <button class="co-btn-icon co-btn-info" aria-label="详情" @click="emit('view-detail', row as OrderRecord)">
            <FontAwesomeIcon icon="eye" aria-hidden="true" />
          </button>
        </div>
      </template>
    </UiDataTable>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import UiDataTable from '@/components/ui/UiDataTable.vue'
import type { TableColumn } from '@/components/ui/UiDataTable.vue'
import type { OrderRecord } from '../composables/types'

const props = defineProps<{
  recordType: 'order' | 'stockin'
  orderRecords: OrderRecord[]
  isLoadingRecords: boolean
  isFetchingRecords: boolean
  totalPages: number
  perPage: number
  fetchOrders: () => void
}>()

const emit = defineEmits<{
  'view-detail': [record: OrderRecord]
  'update:perPage': [value: number]
  'change-page': [page: number]
}>()

const orderColumns = computed<TableColumn[]>(() => {
  const isOrder = props.recordType === 'order'
  const cols: TableColumn[] = [
    { field: 'order_date', header: isOrder ? '订单时间' : '备货时间', align: 'center' },
    { field: 'order_no', header: '编号', align: 'center' },
    { field: 'customer', header: '客户', align: 'center' },
  ]
  if (isOrder) {
    cols.push({ field: 'factories', header: '工厂', align: 'center' })
    cols.push({ field: 'sku_count', header: 'SKU 数量', align: 'center' })
  }
  cols.push({ field: 'product', header: '产品', align: 'center' })
  cols.push({ field: 'quantity', header: '数量', align: 'center' })
  cols.push({ field: 'deduct', header: isOrder ? '抵扣备货' : '已抵扣', align: 'center' })
  if (isOrder) {
    cols.push({ field: 'actions', header: '操作', align: 'center' })
  }
  return cols
})

function onPageChange(event: { page: number; rows: number }) {
  if (event.rows !== props.perPage) {
    emit('update:perPage', event.rows)
    emit('change-page', 1)
  } else {
    emit('change-page', event.page + 1)
  }
  props.fetchOrders()
}
</script>

<style scoped>
.co-records-body {
  flex: 1;
  overflow-y: auto;
  padding: 0;
  min-height: 0;
}

.co-type-badge {
  font-size: 11px;
  padding: 2px 8px;
  border-radius: 6px;
  font-weight: 600;
}
.co-type-badge.order {
  background: var(--color-primary-50);
  color: var(--color-primary-600);
}
.co-type-badge.stockin {
  background: var(--color-success-100);
  color: var(--color-success-600);
}

.co-state-placeholder {
  text-align: center;
  padding: 60px 20px;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 12px;
}
.co-state-empty {
  color: var(--color-text-muted);
}
.co-state-text {
  font-size: 14px;
  color: var(--color-text-secondary);
  margin: 0;
}
.co-empty-illustration {
  font-size: 36px;
  opacity: 0.4;
  color: var(--color-text-muted);
}

.co-fetching-bar {
  height: 3px;
  background: var(--color-border-light);
  overflow: hidden;
}
.co-fetching-progress {
  height: 100%;
  width: 30%;
  background: var(--color-primary-500);
  animation: co-fetch-slide 1.2s ease-in-out infinite;
}
@keyframes co-fetch-slide {
  0% { transform: translateX(-100%); }
  100% { transform: translateX(400%); }
}

.co-cell-main {
  font-weight: 500;
  color: var(--color-text);
}
.co-cell-muted {
  color: var(--color-text-muted);
  font-size: 12px;
}

.co-badge-tag {
  display: inline-block;
  padding: 2px 8px;
  border-radius: 6px;
  font-size: 11px;
  font-weight: 600;
}
.co-badge-success {
  background: var(--color-success-100);
  color: var(--color-success-600);
}
.co-badge-muted {
  background: var(--color-surface, #f1f5f9);
  color: var(--color-text-muted);
}

.co-action-group {
  display: flex;
  gap: 4px;
  justify-content: center;
}
.co-btn-icon {
  width: 36px;
  height: 36px;
  border: none;
  border-radius: 9px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 14px;
  cursor: pointer;
  transition: background 0.2s ease, transform 0.2s ease;
}
.co-btn-info {
  background: var(--color-primary-50);
  color: var(--color-primary-600);
}
.co-btn-info:hover {
  background: var(--color-primary-100);
  transform: translateY(-1px);
}
</style>