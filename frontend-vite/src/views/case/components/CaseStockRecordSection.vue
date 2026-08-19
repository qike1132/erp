<template>
  <!-- 入库/出库记录列表（自 CaseStockTab.vue 原样搬移，入库与出库共用） -->
  <div class="cs-record-section">
    <div class="cs-section-header">
      <div class="cs-section-title">
        <FontAwesomeIcon :icon="kind === 'stockin' ? 'truck-loading' : 'shipping-fast'" :style="{ color: kind === 'stockin' ? 'var(--color-primary-500)' : 'var(--color-danger-500)' }" />
        {{ kind === 'stockin' ? '入库记录列表' : '出库记录列表' }}
      </div>
      <button class="cs-action-btn cs-action-outline" @click="showFilter = !showFilter" aria-label="筛选">
        <FontAwesomeIcon icon="filter" style="margin-right: 4px" />筛选
      </button>
    </div>
    <div v-if="showFilter" class="cs-filter-panel">
      <div class="cs-filter-row">
        <div class="cs-filter-field">
          <label class="cs-form-label">客户</label>
          <UiSelect v-model="fCustomer" placeholder="全部" :options="customerOptions" style="width: 100%" />
        </div>
        <div class="cs-filter-field">
          <label class="cs-form-label">开始日期</label>
          <UiDatePicker v-model="fStart" style="width: 100%" />
        </div>
        <div class="cs-filter-field">
          <label class="cs-form-label">结束日期</label>
          <UiDatePicker v-model="fEnd" style="width: 100%" />
        </div>
        <div class="cs-filter-action">
          <button class="cs-action-btn cs-action-primary" @click="emit('search')" aria-label="查询">
            <FontAwesomeIcon icon="search" style="margin-right: 4px" />查询
          </button>
        </div>
      </div>
    </div>
    <div v-if="isLoading && list.length === 0" class="cs-loading"><UiSpinner /></div>
    <template v-else>
      <div v-if="isFetching" class="cs-fetching-bar"><div class="cs-fetching-progress" /></div>
      <UiDataTable
        :data="list"
        :columns="columns"
        :loading="isLoading"
        :paginator="totalPages > 1"
        :rows="perPage"
        :total-records="totalPages * perPage"
        row-key="id"
        @page="emit('page', $event)"
      >
        <template #empty><div class="cs-empty"><FontAwesomeIcon icon="inbox" /><span>{{ kind === 'stockin' ? '暂无入库记录' : '暂无出库记录' }}</span></div></template>
        <template #column-body-case_name="{ row }"><span style="text-align: left; display: inline-block">{{ row.case_name }}</span></template>
        <template #column-body-case_barcode="{ row }"><small>{{ row.case_barcode || '-' }}</small></template>
        <template #column-body-quantity="{ row }"><strong :style="kind === 'stockout' ? 'color: var(--color-danger-500)' : undefined">{{ row.quantity }}</strong></template>
        <template #column-body-note="{ row }"><small>{{ row.note || '-' }}</small></template>
        <template #column-body-actions="{ row }">
          <button class="cs-icon-btn cs-icon-warning" @click="emit('edit', row)" aria-label="编辑"><FontAwesomeIcon icon="edit" /></button>
          <button class="cs-icon-btn cs-icon-danger" :disabled="actionId === row.id" @click="emit('delete', row)" aria-label="删除"><FontAwesomeIcon icon="trash" /></button>
        </template>
      </UiDataTable>
    </template>
  </div>
</template>

<script setup lang="ts">
/**
 * CaseStockRecordSection — 皮套入库/出库记录列表区块（筛选面板 + 数据表格）
 * 模板与样式自 CaseStockTab.vue 原样搬移，仅将原组件内变量改为 props/emits 绑定；
 * 入库与出库两处仅文案/图标/数量列颜色差异，通过 kind 区分。
 */
import type { TableColumn } from '@/components/ui/UiDataTable.vue'
import type { CaseStockRecord } from '../composables/useCaseStockRecords'
import type { CustomerOption } from '../composables/useCaseStockEntry'

defineProps<{
  /** 记录类型：入库 / 出库 */
  kind: 'stockin' | 'stockout'
  /** 记录列表数据 */
  list: CaseStockRecord[]
  /** 表格列定义 */
  columns: TableColumn[]
  /** 是否加载中 */
  isLoading: boolean
  /** 是否后台刷新中 */
  isFetching: boolean
  /** 每页条数 */
  perPage: number
  /** 总页数 */
  totalPages: number
  /** 客户下拉选项 */
  customerOptions: CustomerOption[]
  /** 行操作进行中的记录 ID（禁用对应删除按钮） */
  actionId: number | ''
}>()

/** 筛选面板展开状态（v-model:show-filter） */
const showFilter = defineModel<boolean>('showFilter', { default: false })
/** 筛选：客户（v-model:f-customer） */
const fCustomer = defineModel<string>('fCustomer', { default: '' })
/** 筛选：开始日期（v-model:f-start） */
const fStart = defineModel<string>('fStart', { default: '' })
/** 筛选：结束日期（v-model:f-end） */
const fEnd = defineModel<string>('fEnd', { default: '' })

const emit = defineEmits<{
  /** 筛选查询（父组件重置回第 1 页后 refetch） */
  search: []
  /** 分页变化（PrimeVue page 为 0 索引，父组件换算） */
  page: [event: { page: number; rows: number }]
  /** 点击编辑行 */
  edit: [row: CaseStockRecord]
  /** 点击删除行 */
  delete: [row: CaseStockRecord]
}>()
</script>

<style scoped>
.cs-record-section {
  border: 1px solid var(--color-border-light, #e2e8f0);
  border-radius: 13px;
  overflow: hidden;
  background: var(--color-surface-card, white);
}

/* Section headers */
.cs-section-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 12px 16px;
  border-bottom: 1px solid var(--color-border-light, #f1f5f9);
}
.cs-section-title {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 14px;
  font-weight: 700;
  color: var(--color-text);
}
.cs-section-title i {
  font-size: 14px;
}

.cs-form-label {
  display: block;
  font-size: 12px;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  color: var(--color-text-secondary);
  margin-bottom: 6px;
}

/* Icon buttons */
.cs-icon-btn {
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
.cs-icon-danger { background: var(--color-danger-50); color: var(--color-danger-500); }
.cs-icon-danger:hover { background: var(--color-danger-100); }
.cs-icon-warning { background: var(--color-warning-50); color: var(--color-warning-500); }
.cs-icon-warning:hover { background: var(--color-warning-100); }

/* Action buttons */
.cs-action-btn {
  padding: 6px 12px;
  border: 2px solid var(--color-border-light, #e2e8f0);
  border-radius: 9px;
  background: white;
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
  transition: background 0.2s ease;
  color: var(--color-text-secondary);
}
.cs-action-primary { color: var(--color-primary-600); }
.cs-action-primary:hover:not(:disabled) { background: var(--color-primary-50); border-color: var(--color-primary-300); transform: translateY(-1px); }
.cs-action-outline { }
.cs-action-btn:disabled { opacity: 0.4; cursor: not-allowed; }

/* Filter panel */
.cs-filter-panel { border-bottom: 1px solid var(--color-border-light); padding: 12px 16px; }
.cs-filter-row { display: flex; gap: 12px; flex-wrap: wrap; align-items: flex-end; }
.cs-filter-field { flex: 0 0 auto; }
.cs-filter-action { display: flex; align-items: flex-end; }

/* Loading & Empty */
.cs-loading, .cs-empty {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  padding: 32px 0;
  color: var(--color-text-muted);
}
.cs-empty {
  flex-direction: column;
}
.cs-empty i { font-size: 28px; opacity: 0.5; }

/* Fetching progress bar */
.cs-fetching-bar {
  height: 2px;
  background: var(--color-primary-100, #e0f2fe);
  overflow: hidden;
  border-radius: 1px;
}
.cs-fetching-progress {
  height: 100%;
  width: 30%;
  background: var(--color-primary-500, #3b82f6);
  border-radius: 1px;
  animation: cs-progress-slide 1s ease-in-out infinite;
}
@keyframes cs-progress-slide {
  0% { transform: translateX(-100%); }
  100% { transform: translateX(400%); }
}
</style>
