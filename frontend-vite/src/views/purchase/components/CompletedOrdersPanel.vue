<template>
  <div class="pc-section">
    <div class="pc-section-header">
      <div class="pc-section-title">
        <i class="fas fa-check-circle" /> 下单查询
      </div>
      <div class="pc-section-actions">
        <button
          class="pc-btn"
          @click="filterExpanded = !filterExpanded"
        >
          <i class="fas fa-filter" /> {{ filterExpanded ? '收起筛选' : '展开筛选' }}
        </button>
        <button
          class="pc-btn pc-btn-primary"
          @click="$emit('export')"
        >
          <i class="fas fa-file-excel" /> 导出
        </button>
      </div>
    </div>

    <!-- Quick Filters -->
    <div class="pc-quick-filters">
      <button
        v-for="f in quickFilters"
        :key="f.id"
        :class="['pc-filter-pill', currentQuickFilterId === f.id ? 'active' : '']"
        @click="$emit('applyQuickFilter', f.id)"
      >
        {{ f.name }}
      </button>
    </div>

    <!-- Advanced Filters (collapsible) -->
    <div v-show="filterExpanded" class="pc-filters-panel">
      <div class="pc-filters-grid">
        <!-- Basic conditions -->
        <div class="pc-filter-group">
          <div class="pc-filter-group-title">
            <i class="fas fa-info-circle" /> 基本条件
          </div>
          <div class="pc-filter-fields">
            <div v-for="field in basicFields" :key="field.key" class="pc-filter-field">
              <label class="pc-filter-label">{{ field.label }}</label>
              <div class="pc-filter-input-wrap">
                <i :class="[field.icon, 'pc-filter-input-icon']" />
                <input
                  type="text"
                  class="pc-filter-input"
                  :placeholder="field.placeholder"
                  :value="filters[field.key]"
                  @input="$emit('updateFilter', { key: field.key, value: ($event.target as HTMLInputElement).value })"
                />
              </div>
            </div>
          </div>
        </div>

        <!-- Time & Material -->
        <div class="pc-filter-group">
          <div class="pc-filter-group-title">
            <i class="fas fa-calendar-alt" /> 时间与物料
          </div>
          <div class="pc-filter-fields">
            <div class="pc-filter-field">
              <label class="pc-filter-label">开始日期</label>
              <UiDatePicker
                :model-value="filters.start_date"
                @update:model-value="$emit('updateFilter', { key: 'start_date', value: $event })"
              />
            </div>
            <div class="pc-filter-field">
              <label class="pc-filter-label">结束日期</label>
              <UiDatePicker
                :model-value="filters.end_date"
                @update:model-value="$emit('updateFilter', { key: 'end_date', value: $event })"
              />
            </div>
            <div class="pc-filter-field pc-filter-field-wide">
              <label class="pc-filter-label">物料名称</label>
              <div class="pc-filter-input-wrap">
                <i class="fas fa-search pc-filter-input-icon" />
                <input
                  type="text"
                  class="pc-filter-input"
                  placeholder="输入物料名称"
                  :value="filters.material_name"
                  @input="$emit('updateFilter', { key: 'material_name', value: ($event.target as HTMLInputElement).value })"
                />
              </div>
            </div>
          </div>
        </div>
      </div>
      <div class="pc-filter-actions">
        <button class="pc-btn" @click="$emit('resetFilters')">
          <i class="fas fa-redo" /> 重置
        </button>
        <button class="pc-btn pc-btn-primary" @click="$emit('search')">
          <i class="fas fa-search" /> 查询
        </button>
      </div>
    </div>

    <!-- Results -->
    <div class="pc-results">
      <div v-if="loading && orders.length === 0" class="pc-loading-state">
        <i class="fas fa-spinner fa-spin" />
        <span>加载中...</span>
      </div>
      <div v-else-if="orders.length === 0" class="pc-empty-state">
        <i class="fas fa-check-circle" />
        <span>暂无已完成的订单</span>
      </div>
      <template v-else>
        <div v-if="fetching" class="pc-fetching-bar"><div class="pc-fetching-progress" /></div>
        <div class="pc-result-info">
          共 <strong>{{ total }}</strong> 条记录
        </div>
        <div class="pc-table-wrap">
          <table>
            <thead>
              <tr>
                <th style="width:15%">下单时间</th>
                <th style="width:15%">订单号</th>
                <th style="width:12%">客户名称</th>
                <th style="width:30%">产品名称</th>
                <th style="width:10%;text-align:right">订单数量</th>
                <th style="width:10%">完成时间</th>
                <th>操作</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="o in orders" :key="o.id">
                <td>{{ o.order_date || '-' }}</td>
                <td class="pc-td-bold">{{ o.source_order_no || o.order_no }}</td>
                <td>{{ o.customer_name || '-' }}</td>
                <td>{{ o.product_name || '-' }}</td>
                <td class="pc-td-right pc-td-bold">{{ o.quantity?.toLocaleString() || '-' }}</td>
                <td class="pc-td-muted pc-td-small">{{ o.completed_at || '-' }}</td>
                <td class="pc-td-center">
                  <button
                    class="pc-btn pc-btn-sm"
                    @click="$emit('viewDetail', o.id)"
                  >
                    <i class="fas fa-eye" /> 查看
                  </button>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </template>

      <!-- Pagination -->
      <UiPagination v-if="totalPages > 1" :current-page="currentPage" :total-pages="totalPages" :total-items="total" @update:current-page="$emit('update:currentPage', $event)" />
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import UiDatePicker from '@/components/ui/UiDatePicker.vue'
import UiPagination from '@/components/ui/UiPagination.vue'
import type { PurchaseOrder } from '@/types'

const props = defineProps<{
  orders: PurchaseOrder[]
  loading: boolean
  fetching?: boolean
  total: number
  currentPage: number
  totalPages: number
  filters: Record<string, string>
  quickFilters: any[]
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

const basicFields = [
  { key: 'order_no', label: '订单号', placeholder: '输入订单号', icon: 'fas fa-search' },
  { key: 'customer_name', label: '客户名称', placeholder: '输入客户名称', icon: 'fas fa-search' },
  { key: 'product_name', label: '产品名称', placeholder: '输入产品名称', icon: 'fas fa-search' },
  { key: 'supplier_name', label: '供应商名称', placeholder: '输入供应商名称', icon: 'fas fa-search' },
  { key: 'barcode', label: '69码', placeholder: '输入69码查询对应SKU', icon: 'fas fa-barcode' },
]
</script>

<style scoped>
.pc-section {}

.pc-section-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 14px 24px 10px;
}

.pc-section-title {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 14px;
  font-weight: 700;
  color: var(--color-text);
}

.pc-section-title i {
  font-size: 13px;
  color: var(--color-primary-500);
}

.pc-section-actions {
  display: flex;
  gap: 8px;
  align-items: center;
}

.pc-btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 7px 14px;
  border: 2px solid var(--color-border-light, #e2e8f0);
  border-radius: 9px;
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.25s ease;
  background: white;
  color: var(--color-text-secondary);
}

.pc-btn:hover {
  border-color: var(--color-primary-300);
  color: var(--color-primary-600);
  background: var(--color-primary-50);
}

.pc-btn-sm {
  padding: 5px 10px;
  font-size: 11px;
}

.pc-btn-primary {
  color: white;
  background: var(--color-primary-500);
  border-color: var(--color-primary-500);
}

.pc-btn-primary:hover {
  background: var(--color-primary-600);
  border-color: var(--color-primary-600);
  color: white;
}

/* Quick filters */
.pc-quick-filters {
  padding: 12px 24px;
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}

.pc-filter-pill {
  padding: 6px 14px;
  border: 2px solid var(--color-border-light, #e2e8f0);
  border-radius: 9px;
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.25s ease;
  background: white;
  color: var(--color-text-secondary);
}

.pc-filter-pill:hover {
  border-color: var(--color-primary-300);
  color: var(--color-primary-600);
  background: var(--color-primary-50);
}

.pc-filter-pill.active {
  background: var(--color-primary-500);
  border-color: var(--color-primary-500);
  color: white;
}

/* Advanced filters */
.pc-filters-panel {
  padding: 0 24px 16px;
}

.pc-filters-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 16px;
}

.pc-filter-group {
  border: 1px solid var(--color-border-light, #e2e8f0);
  border-radius: 12px;
  overflow: hidden;
}

.pc-filter-group-title {
  padding: 10px 16px;
  font-size: 13px;
  font-weight: 600;
  color: var(--color-text);
  border-bottom: 1px solid var(--color-border-light, #e2e8f0);
  background: var(--color-surface, #f8fafc);
  display: flex;
  align-items: center;
  gap: 6px;
}

.pc-filter-group-title i {
  color: var(--color-primary-500);
  font-size: 12px;
}

.pc-filter-fields {
  padding: 16px;
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 12px;
}

.pc-filter-field-wide {
  grid-column: span 2;
}

.pc-filter-field {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.pc-filter-label {
  font-size: 11px;
  font-weight: 600;
  color: var(--color-text-secondary);
  text-transform: uppercase;
  letter-spacing: 0.05em;
}

.pc-filter-input-wrap {
  position: relative;
}

.pc-filter-input-icon {
  position: absolute;
  left: 10px;
  top: 50%;
  transform: translateY(-50%);
  color: var(--color-text-muted, #94a3b8);
  font-size: 12px;
}

.pc-filter-input {
  width: 100%;
  padding: 7px 12px 7px 32px;
  border: 2px solid var(--color-border-light, #e2e8f0);
  border-radius: 8px;
  font-size: 13px;
  outline: none;
  transition: all 0.2s ease;
  background: white;
  font-family: inherit;
  color: var(--color-text);
  box-sizing: border-box;
}

.pc-filter-input:focus {
  border-color: var(--color-primary-400);
  box-shadow: 0 0 0 3px rgba(0, 148, 191, 0.1);
}

.pc-filter-actions {
  margin-top: 12px;
  display: flex;
  gap: 8px;
  justify-content: flex-end;
}

/* Results */
.pc-results {
  padding: 0;
}

.pc-result-info {
  padding: 12px 24px 0;
  font-size: 12px;
  color: var(--color-text-secondary);
}

.pc-result-info strong {
  color: var(--color-primary-500);
}

/* Table */
.pc-table-wrap {
  padding: 12px 24px 16px;
  overflow-x: auto;
}

.pc-table-wrap table {
  width: 100%;
  border-collapse: collapse;
  font-size: 13px;
}

.pc-table-wrap thead th {
  padding: 10px 14px;
  background: var(--color-surface, #f8fafc);
  font-weight: 600;
  color: var(--color-text-secondary);
  font-size: 12px;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  border-bottom: 2px solid var(--color-border-light, #e2e8f0);
  white-space: nowrap;
}

.pc-table-wrap tbody td {
  padding: 10px 14px;
  border-bottom: 1px solid var(--color-border-light, #f1f5f9);
  color: var(--color-text);
  vertical-align: middle;
}

.pc-table-wrap tbody tr:hover td {
  background: var(--color-primary-50);
}

.pc-table-wrap tbody tr:last-child td {
  border-bottom: none;
}

.pc-td-center { text-align: center; }
.pc-td-right { text-align: right; }
.pc-td-bold { font-weight: 600; }
.pc-td-muted { color: var(--color-text-muted, #94a3b8); }
.pc-td-small { font-size: 12px; }

/* Empty & Loading */
.pc-empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 10px;
  padding: 40px 20px;
  color: var(--color-text-muted, #94a3b8);
  font-size: 14px;
}

.pc-empty-state i {
  font-size: 28px;
  opacity: 0.5;
}

.pc-loading-state {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 10px;
  padding: 40px 20px;
  color: var(--color-primary-500);
  font-size: 14px;
}

.pc-loading-state i {
  font-size: 20px;
}

/* Fetching progress bar */
.pc-fetching-bar {
  height: 2px;
  background: var(--color-primary-100, #e0f2fe);
  overflow: hidden;
  border-radius: 1px;
}
.pc-fetching-progress {
  height: 100%;
  width: 30%;
  background: var(--color-primary-500, #3b82f6);
  border-radius: 1px;
  animation: pc-progress-slide 1s ease-in-out infinite;
}
@keyframes pc-progress-slide {
  0% { transform: translateX(-100%); }
  100% { transform: translateX(400%); }
}
</style>
