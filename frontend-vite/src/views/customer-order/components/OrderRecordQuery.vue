<template>
  <div class="co-tab-content">
    <div class="co-records-header">
      <div class="co-records-title-group">
        <span class="co-records-title"><FontAwesomeIcon icon="list-alt" aria-hidden="true" /> 记录列表</span>
        <span class="co-record-type-switch">
          <button
            v-for="opt in recordTypeOptions"
            :key="opt.value"
            :class="['co-type-btn', recordType === opt.value && 'active']"
            @click="emit('change-record-type', opt.value)"
          >{{ opt.label }}</button>

        </span>
      </div>
      <UiButton variant="outline" size="sm" @click="showFilter = !showFilter">
        <FontAwesomeIcon icon="filter" style="margin-right: 4px" aria-hidden="true" />筛选
      </UiButton>
    </div>

    <div v-if="showFilter" class="co-filter-panel">
      <div class="co-filter-row">
        <div class="co-filter-field">
          <label class="co-label"><FontAwesomeIcon icon="user" aria-hidden="true" /> 客户</label>
          <UiSelect v-model="filterCustomer" placeholder="全部" :options="customerOptions" style="width: 100%" />
        </div>
        <div class="co-filter-field">
          <label class="co-label"><FontAwesomeIcon icon="tag" aria-hidden="true" /> 订单类型</label>
          <UiSelect v-model="filterOrderType" placeholder="全部" :options="filterOrderTypeOptions" style="width: 100%" />
        </div>
        <div v-if="recordType === 'order'" class="co-filter-field">
          <label class="co-label"><FontAwesomeIcon icon="info-circle" aria-hidden="true" /> 状态</label>
          <UiSelect v-model="filterStatus" placeholder="全部" :options="statusOptions" style="width: 100%" />
        </div>
        <div v-if="recordType === 'order'" class="co-filter-field">
          <label class="co-label"><FontAwesomeIcon icon="industry" aria-hidden="true" /> 工厂</label>
          <UiSelect v-model="filterFactory" placeholder="全部" :options="factoryOptions" :disabled="factoryDisabled" style="width: 100%" />
        </div>
        <div class="co-filter-field">
          <label class="co-label"><FontAwesomeIcon icon="calendar-alt" aria-hidden="true" /> 开始日期</label>
          <UiDatePicker v-model="filterStart" style="width: 100%" />
        </div>
        <div class="co-filter-field">
          <label class="co-label"><FontAwesomeIcon icon="calendar-alt" aria-hidden="true" /> 结束日期</label>
          <UiDatePicker v-model="filterEnd" style="width: 100%" />
        </div>
        <div class="co-filter-field co-filter-action">
          <UiButton variant="primary" size="sm" @click="fetchOrders">
            <FontAwesomeIcon icon="search" style="margin-right: 4px" aria-hidden="true" />查询
          </UiButton>
          <UiButton variant="outline" size="sm" @click="resetFilter">
            <FontAwesomeIcon icon="undo" style="margin-right: 4px" aria-hidden="true" />重置
          </UiButton>
        </div>
      </div>
    </div>

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
            <button class="co-btn-icon co-btn-info" @click="emit('view-detail', row as OrderRecord)" aria-label="详情">
              <FontAwesomeIcon icon="eye" aria-hidden="true" />
            </button>
          </div>
        </template>
      </UiDataTable>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import UiSelect from '@/components/ui/UiSelect.vue'
import UiDatePicker from '@/components/ui/UiDatePicker.vue'
import UiButton from '@/components/ui/UiButton.vue'
import UiDataTable from '@/components/ui/UiDataTable.vue'
import type { TableColumn } from '@/components/ui/UiDataTable.vue'
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
    // 每页条数变化：回到首页并以新条数重新查询
    emit('update:perPage', event.rows)
    emit('change-page', 1)
  } else {
    emit('change-page', event.page + 1)
  }
  props.fetchOrders()
}
</script>

<style scoped>
.co-tab-content {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-height: 0;
  overflow: hidden;
}

/* ===== 记录查询 ===== */
.co-records-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 20px;
  border-bottom: 1px solid var(--color-border, #cbd5e1);
  flex-shrink: 0;
}
.co-records-title-group {
  display: flex;
  align-items: center;
  gap: 12px;
}
.co-records-title {
  font-size: 14px;
  font-weight: 700;
  color: var(--color-text);
  display: flex;
  align-items: center;
  gap: 8px;
}
.co-records-title i {
  color: var(--color-primary-500);
}
.co-record-type-switch {
  display: inline-flex;
  border: 1px solid var(--color-border, #cbd5e1);
  border-radius: 6px;
  overflow: hidden;
}
.co-record-type-switch .co-type-btn {
  padding: 4px 14px;
  font-size: 12px;
  font-weight: 600;
  border: none;
  background: var(--color-bg, #fff);
  color: var(--color-text-secondary, #64748b);
  cursor: pointer;
  transition: all 0.15s;
}
.co-record-type-switch .co-type-btn.active {
  background: var(--color-primary-500, #3b82f6);
  color: #fff;
}

.co-filter-panel {
  padding: 12px 20px;
  border-bottom: 1px solid var(--color-border, #cbd5e1);
  background: var(--color-surface, #f8fafc);
}
.co-filter-row {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
  align-items: flex-end;
}
.co-filter-field {
  min-width: 140px;
  flex: 1;
}
.co-filter-field .co-label {
  font-size: 12px;
  margin-bottom: 4px;
}
.co-filter-action {
  display: flex;
  gap: 8px;
  flex: 0 0 auto;
  min-width: auto;
}

.co-records-body {
  flex: 1;
  overflow-y: auto;
  padding: 0;
  min-height: 0;
}

.co-label {
  display: block;
  font-size: 13px;
  font-weight: 500;
  margin-bottom: 4px;
  color: var(--color-text-secondary);
}

/* ===== 类型徽章 ===== */
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

/* ===== 加载/空状态 ===== */
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

/* ===== Fetching 进度条 ===== */
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

/* ===== 数据表格 ===== */
.co-cell-main {
  font-weight: 500;
  color: var(--color-text);
}
.co-cell-muted {
  color: var(--color-text-muted);
  font-size: 12px;
}

/* ===== Badge tags ===== */
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

/* ===== Action buttons ===== */
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

/* ===== 响应式筛选 ===== */
@media (max-width: 768px) {
  .co-filter-row {
    flex-direction: column;
  }
  .co-filter-field {
    min-width: 100%;
  }
}
</style>
