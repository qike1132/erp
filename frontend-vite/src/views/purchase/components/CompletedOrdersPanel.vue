<template>
  <div class="coq-panel">
    <!-- 搜索 + 查询 + 导出 -->
    <div class="coq-bar">
      <div class="coq-fields">
        <input
          v-model="draft.order_no"
          class="coq-input"
          type="text"
          placeholder="订单号"
          autocomplete="off"
          @keyup.enter="emit('search')"
        />
        <input
          v-model="draft.customer_name"
          class="coq-input"
          type="text"
          placeholder="客户名称"
          autocomplete="off"
          @keyup.enter="emit('search')"
        />
        <input
          v-model="draft.product_name"
          class="coq-input"
          type="text"
          placeholder="产品名称"
          autocomplete="off"
          @keyup.enter="emit('search')"
        />
        <UiDatePicker v-model="draft.start_date" placeholder="完成日期从" />
        <span class="coq-sep">~</span>
        <UiDatePicker v-model="draft.end_date" placeholder="完成日期到" />
      </div>

      <div class="coq-actions">
        <button class="coq-btn coq-btn-primary" :class="{ 'coq-dirty': isDirty }" @click="emit('search')">
          查询
        </button>
        <button class="coq-btn" :disabled="!hasFilter && !isDirty" @click="emit('reset')">重置</button>
        <button class="coq-btn" :disabled="exporting" @click="emit('export')">
          <span v-if="exporting" class="coq-spin" aria-hidden="true" />
          {{ exporting ? '导出中…' : '导出' }}
        </button>
        <span class="coq-total">共 {{ total }} 条</span>
      </div>
    </div>

    <!-- 已生效条件（可单个移除） -->
    <div v-if="activePills.length" class="coq-pills">
      <span class="coq-pill-label">当前条件</span>
      <span v-for="p in activePills" :key="p.key" class="coq-pill">
        {{ p.label }}
        <button :aria-label="`移除${p.label}`" @click="emit('remove-filter', p.key)">✕</button>
      </span>
      <button class="coq-clear" @click="emit('reset')">清空全部</button>
    </div>

    <div class="coq-body">
      <!-- 首屏加载骨架 -->
      <div v-if="loading && orders.length === 0" class="coq-skeleton">
        <div v-for="i in 8" :key="i" class="coq-skeleton-row" />
      </div>

      <!-- 错误态（可重试） -->
      <div v-else-if="error && orders.length === 0" class="coq-empty coq-error">
        <FontAwesomeIcon icon="exclamation-triangle" aria-hidden="true" />
        <p class="coq-empty-text">加载失败，请检查网络后重试</p>
        <button class="coq-btn coq-btn-primary" @click="emit('retry')">重试</button>
      </div>

      <!-- 空状态：区分"无数据"与"条件过窄" -->
      <div v-else-if="orders.length === 0" class="coq-empty">
        <FontAwesomeIcon :icon="hasFilter ? 'filter' : 'folder-open'" aria-hidden="true" />
        <p class="coq-empty-text">{{ hasFilter ? '没有符合条件的订单' : '暂无订单记录' }}</p>
        <button v-if="hasFilter" class="coq-btn" @click="emit('reset')">清空筛选条件</button>
      </div>

      <!-- 数据表格 -->
      <template v-else>
        <div v-if="fetching" class="coq-fetching"><div class="coq-fetching-bar" /></div>

        <div class="coq-table-scroll">
          <table class="coq-table">
            <thead>
              <tr>
                <th class="coq-th coq-w-date">完成时间</th>
                <th class="coq-th coq-w-customer">客户</th>
                <th class="coq-th coq-w-product">产品名称</th>
                <th class="coq-th coq-th-num coq-w-num">数量</th>
                <th class="coq-th coq-w-status">状态</th>
                <th class="coq-th coq-w-op">操作</th>
              </tr>
            </thead>
            <tbody
              v-for="row in flatRows"
              :key="row.o.id"
              class="coq-po-group"
              tabindex="0"
              @click="emit('viewDetail', row.o.id)"
              @keydown.enter="emit('viewDetail', row.o.id)"
            >
              <tr v-for="(sku, idx) in row.skus" :key="row.o.id + '-' + idx" class="coq-row">
                <td v-if="idx === 0" class="coq-td coq-td-muted" :rowspan="row.skuCount">
                  {{ formatDateTime(row.o.completed_at) }}
                </td>
                <td v-if="idx === 0" class="coq-td" :rowspan="row.skuCount">
                  {{ row.o.customer_name || '—' }}
                </td>
                <td class="coq-td coq-td-product" :title="sku.product_name">
                  {{ sku.product_name || '—' }}
                </td>
                <td class="coq-td coq-td-num">{{ formatNumber(sku.quantity) }}</td>
                <td v-if="idx === 0" class="coq-td" :rowspan="row.skuCount">
                  <span :class="['coq-badge', getStatusClass(row.o.status)]">
                    {{ getStatusLabel(row.o.status) }}
                  </span>
                </td>
                <td v-if="idx === 0" class="coq-td" :rowspan="row.skuCount">
                  <button class="coq-op" @click.stop="emit('viewDetail', row.o.id)">查看</button>
                </td>
              </tr>
            </tbody>
          </table>
        </div>

        <!-- 分页 -->
        <div v-if="totalPages > 1" class="coq-pagination">
          <UiPagination
            :current-page="currentPage"
            :total-pages="totalPages"
            :total-items="total"
            @update:current-page="emit('update:currentPage', $event)"
          />
        </div>
      </template>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import UiPagination from '@/components/ui/UiPagination.vue'
import UiDatePicker from '@/components/ui/UiDatePicker.vue'
import type { PurchaseOrder } from '@/types'
import { formatDateTime, formatNumber } from '@/utils/format'
import type { CompletedOrderFilters } from '../composables/useCompletedOrders'

const props = defineProps<{
  orders: PurchaseOrder[]
  loading: boolean
  fetching?: boolean
  error?: boolean
  total: number
  currentPage: number
  totalPages: number
  /** 草稿与已提交条件是否有差异 */
  isDirty: boolean
  /** 是否处于筛选状态 */
  hasFilter: boolean
  /** 导出进行中 */
  exporting: boolean
}>()

/** 筛选表单草稿（v-model:draft，父组件持有状态，子组件负责编辑） */
const draft = defineModel<CompletedOrderFilters>('draft', { required: true })

const emit = defineEmits<{
  search: []
  reset: []
  export: []
  'remove-filter': [key: keyof CompletedOrderFilters]
  viewDetail: [id: number]
  'update:currentPage': [page: number]
  retry: []
}>()

const FILTER_LABELS: Record<keyof CompletedOrderFilters, string> = {
  order_no: '订单号',
  customer_name: '客户',
  product_name: '产品',
  start_date: '起始日期',
  end_date: '截止日期',
}

/** 已生效条件胶囊：从草稿推导，与页面上看到的输入框保持一致 */
const activePills = computed(() =>
  (Object.keys(FILTER_LABELS) as (keyof CompletedOrderFilters)[])
    .filter((key) => !!draft.value[key])
    .map((key) => ({ key, label: `${FILTER_LABELS[key]}：${draft.value[key]}` })),
)

const statusMap: Record<string, { label: string; cls: string }> = {
  completed: { label: '已完成', cls: 'coq-badge-success' },
  pending: { label: '待处理', cls: 'coq-badge-primary' },
  partial: { label: '部分', cls: 'coq-badge-warning' },
  cancelled: { label: '已取消', cls: 'coq-badge-danger' },
}

function getStatusClass(status: string): string {
  return statusMap[status]?.cls || 'coq-badge-muted'
}

function getStatusLabel(status: string): string {
  return statusMap[status]?.label || status || '—'
}

function getSkuRows(o: PurchaseOrder): { product_name: string; quantity: number }[] {
  if (o.sku_items && o.sku_items.length > 0) {
    return o.sku_items.map((s) => ({ product_name: s.product_name || '', quantity: s.quantity || 0 }))
  }
  return [{ product_name: o.product_name || '', quantity: o.quantity || 0 }]
}

/** 预计算，避免模板内每行重复调用 getSkuRows */
const flatRows = computed(() =>
  props.orders.map((o) => {
    const skus = getSkuRows(o)
    return { o, skus, skuCount: skus.length }
  }),
)
</script>

<style scoped>
.coq-panel {
  --coq-blue: var(--color-primary-500, #5b8def);
  --coq-navy: var(--color-primary-700, #2d5ab8);
  --coq-border: #e2e8f0;
  --coq-border-light: #f1f5f9;
  --coq-bg-soft: #f8fafc;
  --coq-text: #0f172a;
  --coq-text-secondary: #475569;
  --coq-text-muted: #94a3b8;
  --coq-red: var(--color-danger-600, #e53e3e);
  font-family: var(--font-sans);
  color: var(--coq-text);
  background: #fff;
}

/* === 搜索 + 查询 + 导出 === */
.coq-bar {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 14px 24px;
  border-bottom: 1px solid var(--coq-border);
  flex-wrap: wrap;
}

.coq-fields {
  display: flex;
  align-items: center;
  gap: 8px;
  flex: 1;
  min-width: 0;
  flex-wrap: wrap;
}

.coq-input {
  height: 32px;
  padding: 0 10px;
  border: 1px solid var(--coq-border);
  border-radius: 7px;
  font-size: 13px;
  font-family: inherit;
  color: var(--coq-text);
  background: #fff;
  outline: none;
  min-width: 130px;
  flex: 1 1 130px;
  max-width: 190px;
  box-sizing: border-box;
  transition: border-color 0.15s ease, box-shadow 0.15s ease;
}

.coq-input:focus {
  border-color: var(--coq-blue);
  box-shadow: 0 0 0 3px rgba(91, 141, 239, 0.14);
}

.coq-input::placeholder {
  color: var(--coq-text-muted);
}

.coq-sep {
  color: var(--coq-text-muted);
  font-size: 12px;
  flex-shrink: 0;
}

.coq-actions {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-shrink: 0;
}

.coq-total {
  font-size: 12px;
  color: var(--coq-text-secondary);
  font-weight: 600;
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
  padding-left: 4px;
}

/* === 已生效条件 === */
.coq-pills {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
  padding: 10px 24px;
  background: var(--coq-bg-soft);
  border-bottom: 1px solid var(--coq-border);
}

.coq-pill-label {
  font-size: 12px;
  font-weight: 600;
  color: var(--coq-text-muted);
}

.coq-pill {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 3px 6px 3px 10px;
  border-radius: 999px;
  background: var(--color-primary-50, #eff5ff);
  color: var(--coq-navy);
  font-size: 12px;
  font-weight: 600;
}

.coq-pill button {
  border: none;
  background: transparent;
  color: var(--coq-navy);
  cursor: pointer;
  font-size: 12px;
  line-height: 1;
  padding: 0 2px;
  font-family: inherit;
}

.coq-pill button:hover {
  color: var(--coq-red);
}

.coq-clear {
  border: none;
  background: transparent;
  color: var(--coq-text-muted);
  font-size: 12px;
  font-family: inherit;
  cursor: pointer;
  text-decoration: underline;
  padding: 0 4px;
}

.coq-clear:hover {
  color: var(--coq-red);
}

/* === 按钮 === */
.coq-btn {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 6px 14px;
  border: 1px solid var(--coq-border);
  border-radius: 8px;
  font-size: 12px;
  font-weight: 600;
  font-family: inherit;
  color: var(--coq-text-secondary);
  background: #fff;
  cursor: pointer;
  transition: border-color 0.15s ease, color 0.15s ease, background 0.15s ease;
  white-space: nowrap;
}

.coq-btn:hover:not(:disabled) {
  border-color: var(--coq-blue);
  color: var(--coq-navy);
}

.coq-btn:disabled {
  opacity: 0.45;
  cursor: not-allowed;
}

.coq-btn-primary {
  color: #fff;
  background: var(--coq-navy);
  border-color: var(--coq-navy);
}

.coq-btn-primary:hover:not(:disabled) {
  background: var(--color-primary-800, #234996);
  border-color: var(--color-primary-800, #234996);
  color: #fff;
}

/* 有未提交改动时高亮"查询"，提示"改了还没查" */
.coq-btn-primary.coq-dirty {
  box-shadow: 0 0 0 3px rgba(91, 141, 239, 0.25);
}

.coq-spin {
  width: 11px;
  height: 11px;
  border: 2px solid rgba(71, 85, 105, 0.3);
  border-top-color: var(--coq-text-secondary);
  border-radius: 50%;
  animation: coq-spin 0.6s linear infinite;
}

@keyframes coq-spin {
  to {
    transform: rotate(360deg);
  }
}

/* === 表格 === */
.coq-table-scroll {
  overflow-x: auto;
}

.coq-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 13px;
  font-variant-numeric: tabular-nums;
}

.coq-table thead th {
  padding: 10px 14px;
  background: var(--coq-bg-soft);
  font-weight: 600;
  color: var(--coq-text-secondary);
  font-size: 12px;
  letter-spacing: 0.05em;
  border-bottom: 2px solid var(--coq-border);
  white-space: nowrap;
  text-align: left;
  position: sticky;
  top: 0;
  z-index: 1;
}

.coq-w-date { width: 140px; min-width: 140px; white-space: nowrap; }
.coq-w-customer { width: 18%; min-width: 140px; }
.coq-w-product { width: auto; min-width: 200px; }
.coq-w-num { width: 100px; min-width: 100px; white-space: nowrap; }
.coq-w-status { width: 96px; min-width: 96px; white-space: nowrap; text-align: center; }
.coq-w-op { width: 76px; min-width: 76px; white-space: nowrap; text-align: center; }

.coq-th-num {
  text-align: right !important;
  letter-spacing: 0;
}

.coq-td-num {
  text-align: right;
  font-weight: 600;
}

.coq-table tbody td {
  padding: 10px 14px;
  border-bottom: 1px solid var(--coq-border-light);
  color: var(--coq-text);
  vertical-align: middle;
}

.coq-table tbody tr:last-child td {
  border-bottom: 1px solid var(--coq-border);
}

.coq-table tbody:last-child tr:last-child td {
  border-bottom: none;
}

.coq-po-group {
  cursor: pointer;
  transition: background 0.15s ease;
}

.coq-po-group:hover td {
  background: var(--color-primary-50, #eff5ff);
}

.coq-po-group:focus-visible {
  outline: 2px solid var(--coq-blue);
  outline-offset: -2px;
}

.coq-td-muted {
  color: var(--coq-text-secondary);
  font-size: 12px;
}

.coq-td-product {
  max-width: 360px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  text-align: left;
}

/* 行操作按钮：hover / 键盘聚焦时显现 */
.coq-op {
  padding: 3px 10px;
  border: 1px solid var(--coq-border);
  border-radius: 6px;
  background: #fff;
  font-size: 12px;
  font-family: inherit;
  color: var(--coq-text-secondary);
  cursor: pointer;
  opacity: 0;
  transition: opacity 0.15s ease, border-color 0.15s ease, color 0.15s ease;
}

.coq-po-group:hover .coq-op,
.coq-po-group:focus-within .coq-op {
  opacity: 1;
}

.coq-op:hover {
  border-color: var(--coq-blue);
  color: var(--coq-navy);
  background: var(--color-primary-50, #eff5ff);
}

.coq-badge {
  display: inline-block;
  padding: 5px 12px;
  border-radius: 16px;
  font-size: 12px;
  font-weight: 600;
  white-space: nowrap;
}

.coq-badge-success { background: var(--color-success-50, #e8f9ef); color: var(--color-success-600, #1e9e55); }
.coq-badge-warning { background: var(--color-warning-50, #fff3e6); color: var(--color-warning-600, #e88e2e); }
.coq-badge-primary { background: var(--color-primary-50, #eff5ff); color: var(--color-primary-700, #2d5ab8); }
.coq-badge-danger { background: var(--color-danger-50, #fde8e8); color: var(--color-danger-600, #d44042); }
.coq-badge-muted { background: var(--coq-border-light); color: var(--coq-text-secondary); }

.coq-pagination {
  border-top: 1px solid var(--coq-border-light);
}

/* === 骨架 / 空态 / 错误态 === */
.coq-skeleton-row {
  height: 42px;
  border-bottom: 1px solid var(--coq-border-light);
  background: linear-gradient(90deg, var(--coq-bg-soft) 0%, #eef2f7 50%, var(--coq-bg-soft) 100%);
  background-size: 200% 100%;
  animation: coq-shimmer 1.5s ease-in-out infinite;
}

@keyframes coq-shimmer {
  0% { background-position: 200% 0; }
  100% { background-position: -200% 0; }
}

.coq-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 6px;
  padding: 56px 20px;
  text-align: center;
}

.coq-empty svg {
  color: var(--coq-border);
  margin-bottom: 6px;
}

.coq-empty-text {
  margin: 0 0 4px;
  font-size: 14px;
  font-weight: 600;
  color: var(--coq-text-secondary);
}

.coq-error svg {
  color: var(--coq-red);
}

/* === 顶部细进度条（翻页/刷新时） === */
.coq-fetching {
  height: 2px;
  background: var(--color-primary-100, #d6e4ff);
  overflow: hidden;
}

.coq-fetching-bar {
  height: 100%;
  width: 30%;
  background: var(--coq-blue);
  animation: coq-progress 1s ease-in-out infinite;
}

@keyframes coq-progress {
  0% { transform: translateX(-100%); }
  100% { transform: translateX(400%); }
}

/* === 响应式 === */
@media (max-width: 900px) {
  .coq-bar {
    padding: 12px 14px;
  }
  .coq-pills {
    padding: 10px 14px;
  }
  .coq-input {
    max-width: none;
  }
  .coq-actions {
    width: 100%;
  }
}

@media (max-width: 560px) {
  .coq-actions {
    flex-wrap: wrap;
  }
  .coq-actions .coq-btn {
    flex: 1;
    justify-content: center;
  }
  .coq-total {
    width: 100%;
    padding-left: 0;
  }
}
</style>
