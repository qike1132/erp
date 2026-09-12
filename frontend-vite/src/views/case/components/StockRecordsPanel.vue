<template>
  <div class="srp-section">
    <div class="srp-header">
      <div class="srp-title">
        <FontAwesomeIcon :icon="kind === 'stockin' ? 'truck-loading' : 'shipping-fast'" :style="{ color: kind === 'stockin' ? 'var(--color-primary-500)' : 'var(--color-danger-500)' }" aria-hidden="true" />
        {{ kind === 'stockin' ? '入库记录' : '出库记录' }}
        <small v-if="total" class="srp-total">共 {{ total }} 条</small>
      </div>
      <div class="srp-actions">
        <button class="srp-btn srp-btn-ghost" aria-label="刷新" @click="refetch()">
          <FontAwesomeIcon icon="sync-alt" style="margin-right: 4px" aria-hidden="true" />刷新
        </button>
        <button class="srp-btn srp-btn-ghost" aria-label="筛选" @click="showFilter = !showFilter">
          <FontAwesomeIcon icon="filter" style="margin-right: 4px" aria-hidden="true" />筛选
        </button>
      </div>
    </div>

    <div v-if="showFilter" class="srp-filter">
      <div class="srp-filter-field">
        <label class="srp-label">客户</label>
        <UiSelect v-model="filters.customer" placeholder="全部" :options="customerOptions" style="width: 160px" />
      </div>
      <div class="srp-filter-field">
        <label class="srp-label">开始日期</label>
        <UiDatePicker v-model="filters.start" style="width: 140px" />
      </div>
      <div class="srp-filter-field">
        <label class="srp-label">结束日期</label>
        <UiDatePicker v-model="filters.end" style="width: 140px" />
      </div>
      <div class="srp-filter-actions">
        <button class="srp-btn srp-btn-primary" aria-label="查询" @click="search()">
          <FontAwesomeIcon icon="search" style="margin-right: 4px" aria-hidden="true" />查询
        </button>
        <button class="srp-btn srp-btn-ghost" aria-label="重置" @click="resetFilters()">重置</button>
      </div>
    </div>

    <div v-if="isFetching && list.length" class="srp-fetching-bar"><div class="srp-fetching-progress" /></div>
    <UiDataTable
      :data="list"
      :columns="columns"
      :loading="isLoading && !list.length"
      :paginator="total > perPage"
      :rows="perPage"
      :total-records="total"
      row-key="id"
      @page="onPageChange"
    >
      <template #empty>
        <div class="srp-empty">
          <FontAwesomeIcon icon="inbox" aria-hidden="true" />
          <span>{{ kind === 'stockin' ? '暂无入库记录' : '暂无出库记录' }}</span>
        </div>
      </template>
      <template #column-body-case_name="{ row }"><span class="srp-name">{{ row.case_name }}</span></template>
      <template #column-body-case_barcode="{ row }"><small class="srp-barcode">{{ row.case_barcode || '-' }}</small></template>
      <template #column-body-quantity="{ row }">
        <strong :style="{ color: kind === 'stockout' ? 'var(--color-danger-500)' : 'var(--color-success-600)' }">{{ row.quantity }}</strong>
      </template>
      <template #column-body-note="{ row }"><small class="srp-note" :title="row.note">{{ row.note || '-' }}</small></template>
      <template #column-body-actions="{ row }">
        <button class="srp-icon-btn srp-icon-edit" aria-label="编辑" @click="emit('edit', row)"><FontAwesomeIcon icon="edit" /></button>
        <button class="srp-icon-btn srp-icon-del" :disabled="actionId === row.id" aria-label="删除" @click="emit('delete', row)"><FontAwesomeIcon icon="trash" /></button>
      </template>
    </UiDataTable>
  </div>
</template>

<script setup lang="ts">
/**
 * StockRecordsPanel — 入库/出库记录列表（筛选 + 服务端分页 + 行操作入口）。
 * 数据由 useCaseStockRecords(kind) 内部持有；编辑/删除动作上抛给工作台处理。
 */
import UiDataTable from '@/components/ui/UiDataTable.vue'
import UiSelect from '@/components/ui/UiSelect.vue'
import UiDatePicker from '@/components/ui/UiDatePicker.vue'
import { useCaseStockRecords } from '../composables/useCaseStockRecords'
import type { CaseStockRecord, CustomerOption } from '@/api/case'

const props = defineProps<{
  kind: 'stockin' | 'stockout'
  customerOptions: CustomerOption[]
  /** 删除请求进行中的记录 ID（禁用对应删除按钮） */
  actionId?: number
}>()

const emit = defineEmits<{
  edit: [row: CaseStockRecord]
  delete: [row: CaseStockRecord]
}>()

const {
  showFilter,
  filters,
  perPage,
  total,
  isLoading,
  isFetching,
  refetch,
  list,
  columns,
  onPageChange,
  search,
  resetFilters,
} = useCaseStockRecords(props.kind)
</script>

<style scoped>
.srp-section {
  border: 1px solid var(--color-border-light, #e2e8f0);
  border-radius: 13px;
  overflow: hidden;
  background: var(--color-surface-card, white);
}
.srp-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 12px 16px;
  border-bottom: 1px solid var(--color-border-light, #f1f5f9);
}
.srp-title {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 14px;
  font-weight: 700;
  color: var(--color-text);
}
.srp-total { color: var(--color-text-muted); font-weight: 400; }
.srp-actions { display: flex; gap: 8px; }

.srp-btn {
  padding: 6px 12px;
  border-radius: 9px;
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  transition: background 0.2s ease;
}
.srp-btn-ghost {
  border: 2px solid var(--color-border-light, #e2e8f0);
  background: white;
  color: var(--color-text-secondary);
}
.srp-btn-ghost:hover { background: var(--color-primary-50); color: var(--color-primary-600); }
.srp-btn-primary {
  border: none;
  background: linear-gradient(135deg, var(--color-primary-500), var(--color-primary-700));
  color: white;
}
.srp-btn-primary:hover { transform: translateY(-1px); box-shadow: 0 4px 12px rgba(91, 141, 239, 0.3); }

.srp-filter {
  display: flex;
  gap: 12px;
  flex-wrap: wrap;
  align-items: flex-end;
  padding: 12px 16px;
  border-bottom: 1px solid var(--color-border-light, #f1f5f9);
  background: var(--color-surface, #f8fafc);
}
.srp-filter-field { display: flex; flex-direction: column; }
.srp-label {
  font-size: 12px;
  font-weight: 600;
  color: var(--color-text-secondary);
  margin-bottom: 6px;
}
.srp-filter-actions { display: flex; gap: 8px; padding-bottom: 2px; }

.srp-name { font-weight: 600; color: var(--color-text); }
.srp-barcode { color: var(--color-text-muted); }
.srp-note {
  display: inline-block;
  max-width: 160px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: var(--color-text-secondary);
}

.srp-icon-btn {
  width: 28px;
  height: 28px;
  border: none;
  border-radius: 7px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  font-size: 12px;
  transition: background 0.2s ease;
}
.srp-icon-edit { background: var(--color-warning-50); color: var(--color-warning-500); }
.srp-icon-edit:hover { background: var(--color-warning-100); }
.srp-icon-del { background: var(--color-danger-50); color: var(--color-danger-500); }
.srp-icon-del:hover { background: var(--color-danger-100); }

.srp-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
  padding: 32px 0;
  color: var(--color-text-muted);
}
.srp-empty i { font-size: 28px; opacity: 0.5; }

.srp-fetching-bar {
  height: 2px;
  background: var(--color-primary-100, #e0f2fe);
  overflow: hidden;
}
.srp-fetching-progress {
  height: 100%;
  width: 30%;
  background: var(--color-primary-500, #3b82f6);
  animation: srp-slide 1s ease-in-out infinite;
}
@keyframes srp-slide {
  0% { transform: translateX(-100%); }
  100% { transform: translateX(400%); }
}
</style>
