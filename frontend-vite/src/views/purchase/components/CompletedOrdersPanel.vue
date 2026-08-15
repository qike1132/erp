<template>
  <div class="coq-panel">
    <!-- 工具栏：标题 + 统计 + 操作 -->
    <div class="coq-toolbar">
      <div class="coq-toolbar-left">
        <h2 class="coq-title">下单查询</h2>
        <span v-if="total > 0" class="coq-count">{{ total }}</span>
      </div>
      <div class="coq-toolbar-right">
        <button class="coq-btn coq-btn-ghost" @click="filterExpanded = !filterExpanded">
          <FontAwesomeIcon icon="sliders-h" aria-hidden="true" />
          <span>{{ filterExpanded ? '收起' : '高级' }}</span>
        </button>
        <button class="coq-btn coq-btn-primary" @click="$emit('export')">
          <FontAwesomeIcon icon="file-export" aria-hidden="true" />
          <span>导出</span>
        </button>
      </div>
    </div>

    <!-- 快速筛选 -->
    <div v-if="quickFilters.length > 0" class="coq-quick">
      <button
        v-for="f in quickFilters"
        :key="f.id"
        :class="['coq-quick-btn', currentQuickFilterId === f.id ? 'coq-quick-active' : '']"
        @click="$emit('applyQuickFilter', f.id)"
      >
        {{ f.name }}
      </button>
    </div>

    <!-- 搜索栏（内联，无背景框） -->
    <div class="coq-search">
      <div class="coq-search-grid">
        <div class="coq-search-cell">
          <FontAwesomeIcon icon="hashtag" class="coq-search-icon" aria-hidden="true" />
          <input
            type="text"
            class="coq-search-input"
            placeholder="订单号"
            :value="filters.order_no"
            @input="$emit('updateFilter', { key: 'order_no', value: ($event.target as HTMLInputElement).value })"
            @keyup.enter="$emit('search')"
          />
        </div>
        <div class="coq-search-cell">
          <FontAwesomeIcon icon="user" class="coq-search-icon" aria-hidden="true" />
          <input
            type="text"
            class="coq-search-input"
            placeholder="客户名称"
            :value="filters.customer_name"
            @input="$emit('updateFilter', { key: 'customer_name', value: ($event.target as HTMLInputElement).value })"
            @keyup.enter="$emit('search')"
          />
        </div>
        <div class="coq-search-cell">
          <FontAwesomeIcon icon="box" class="coq-search-icon" aria-hidden="true" />
          <input
            type="text"
            class="coq-search-input"
            placeholder="产品名称"
            :value="filters.product_name"
            @input="$emit('updateFilter', { key: 'product_name', value: ($event.target as HTMLInputElement).value })"
            @keyup.enter="$emit('search')"
          />
        </div>
        <div class="coq-search-cell coq-search-date">
          <UiDatePicker
            :model-value="filters.start_date"
            placeholder="开始日期"
            @update:model-value="$emit('updateFilter', { key: 'start_date', value: $event })"
          />
        </div>
        <div class="coq-search-sep">~</div>
        <div class="coq-search-cell coq-search-date">
          <UiDatePicker
            :model-value="filters.end_date"
            placeholder="结束日期"
            @update:model-value="$emit('updateFilter', { key: 'end_date', value: $event })"
          />
        </div>
        <button class="coq-btn coq-btn-primary coq-search-go" @click="$emit('search')">
          <FontAwesomeIcon icon="search" aria-hidden="true" />
          <span>查询</span>
        </button>
      </div>
    </div>

    <!-- 高级筛选（折叠） -->
    <transition name="coq-slide">
      <div v-show="filterExpanded" class="coq-advanced">
        <div class="coq-advanced-row">
          <div class="coq-advanced-cell">
            <label class="coq-advanced-label">供应商</label>
            <input
              type="text"
              class="coq-advanced-input"
              placeholder="输入供应商名称"
              :value="filters.supplier_name"
              @input="$emit('updateFilter', { key: 'supplier_name', value: ($event.target as HTMLInputElement).value })"
            />
          </div>
          <div class="coq-advanced-cell">
            <label class="coq-advanced-label">69码</label>
            <input
              type="text"
              class="coq-advanced-input"
              placeholder="输入69码"
              :value="filters.barcode"
              @input="$emit('updateFilter', { key: 'barcode', value: ($event.target as HTMLInputElement).value })"
            />
          </div>
          <div class="coq-advanced-cell">
            <label class="coq-advanced-label">物料名称</label>
            <input
              type="text"
              class="coq-advanced-input"
              placeholder="输入物料名称"
              :value="filters.material_name"
              @input="$emit('updateFilter', { key: 'material_name', value: ($event.target as HTMLInputElement).value })"
            />
          </div>
          <button class="coq-btn coq-btn-ghost coq-advanced-reset" @click="$emit('resetFilters')">
            <FontAwesomeIcon icon="undo" aria-hidden="true" />
            <span>重置</span>
          </button>
        </div>
      </div>
    </transition>

    <!-- 结果区 -->
    <div class="coq-body">
      <!-- 加载骨架 -->
      <div v-if="loading && orders.length === 0" class="coq-skeleton">
        <div v-for="i in 8" :key="i" class="coq-skeleton-row" />
      </div>

      <!-- 空状态 -->
      <div v-else-if="orders.length === 0" class="coq-empty">
        <FontAwesomeIcon icon="folder-open" aria-hidden="true" />
        <p class="coq-empty-text">暂无订单记录</p>
        <p class="coq-empty-hint">调整搜索条件或选择其他时间范围</p>
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
              </tr>
            </thead>
            <tbody
              v-for="o in orders"
              :key="o.id"
              class="coq-po-group"
              @click="$emit('viewDetail', o.id)"
            >
              <tr
                v-for="(sku, idx) in getSkuRows(o)"
                :key="o.id + '-' + idx"
                class="coq-row"
              >
                <td v-if="idx === 0" class="coq-td coq-td-muted" :rowspan="getSkuRows(o).length">
                  {{ formatDate(o.completed_at) || '—' }}
                </td>
                <td v-if="idx === 0" class="coq-td" :rowspan="getSkuRows(o).length">
                  {{ o.customer_name || '—' }}
                </td>
                <td class="coq-td coq-td-product" :title="sku.product_name">{{ sku.product_name || '—' }}</td>
                <td class="coq-td coq-td-num">{{ formatNumber(sku.quantity) }}</td>
                <td v-if="idx === 0" class="coq-td" :rowspan="getSkuRows(o).length">
                  <span :class="['coq-badge', getStatusClass(o.status)]">
                    {{ getStatusLabel(o.status) }}
                  </span>
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
            @update:current-page="$emit('update:currentPage', $event)"
          />
        </div>
      </template>
    </div>
  </div>
</template>

<script setup lang="ts">
import UiDatePicker from '@/components/ui/UiDatePicker.vue'
import UiPagination from '@/components/ui/UiPagination.vue'
import type { PurchaseOrder } from '@/types'
import { formatDate, formatNumber } from '@/utils/format'
import type { QuickFilter } from '../composables/useCompletedOrders'

defineProps<{
  orders: PurchaseOrder[]
  loading: boolean
  fetching?: boolean
  total: number
  currentPage: number
  totalPages: number
  filters: Record<string, string>
  quickFilters: QuickFilter[]
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

// 状态映射：圆角徽章风格（与审核订单一致）
const statusMap: Record<string, { label: string; cls: string }> = {
  completed: { label: '已完成', cls: 'coq-badge-success' },
  partial: { label: '部分', cls: 'coq-badge-warning' },
  pending: { label: '待处理', cls: 'coq-badge-primary' },
  cancelled: { label: '已取消', cls: 'coq-badge-danger' },
}

function getStatusClass(status: string): string {
  return statusMap[status]?.cls || 'coq-badge-muted'
}

function getStatusLabel(status: string): string {
  return statusMap[status]?.label || status || '—'
}

// 多 SKU 拆行：若订单含 sku_items，每 SKU 独立成行；否则回退到 product_name/quantity 单行
function getSkuRows(o: PurchaseOrder): { product_name: string; quantity: number }[] {
  if (o.sku_items && o.sku_items.length > 0) {
    return o.sku_items.map(s => ({ product_name: s.product_name || '', quantity: s.quantity || 0 }))
  }
  return [{ product_name: o.product_name || '', quantity: o.quantity || 0 }]
}
</script>

<style scoped>
/* ============ 设计令牌（Data-Dense Enterprise） ============ */
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
}

/* ============ 工具栏 ============ */
.coq-toolbar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 16px 24px 12px;
}

.coq-toolbar-left {
  display: flex;
  align-items: baseline;
  gap: 10px;
}

.coq-title {
  margin: 0;
  font-size: 16px;
  font-weight: 700;
  color: var(--coq-text);
  letter-spacing: -0.01em;
}

.coq-count {
  font-size: 13px;
  font-weight: 600;
  color: var(--coq-slate);
  font-variant-numeric: tabular-nums;
}

.coq-count::before {
  content: '·';
  margin-right: 6px;
  color: var(--coq-border);
}

.coq-toolbar-right {
  display: flex;
  gap: 8px;
  align-items: center;
}

/* ============ 按钮 ============ */
.coq-btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 6px 12px;
  border: 1px solid var(--coq-border);
  border-radius: 6px;
  font-size: 13px;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.15s ease;
  background: var(--coq-bg);
  color: var(--coq-text-secondary);
  white-space: nowrap;
  font-family: inherit;
  line-height: 1.4;
}

.coq-btn i {
  font-size: 11px;
}

.coq-btn:hover {
  border-color: var(--coq-blue);
  color: var(--coq-navy);
  background: var(--coq-blue-light);
}

.coq-btn-ghost {
  border-color: transparent;
  background: transparent;
}

.coq-btn-ghost:hover {
  border-color: var(--coq-border);
  background: var(--coq-bg-soft);
}

.coq-btn-primary {
  background: var(--coq-navy);
  border-color: var(--coq-navy);
  color: #fff;
}

.coq-btn-primary:hover {
  background: var(--coq-navy-deep);
  border-color: var(--coq-navy-deep);
  color: #fff;
}

/* ============ 快速筛选 ============ */
.coq-quick {
  display: flex;
  gap: 4px;
  padding: 0 24px 12px;
  flex-wrap: wrap;
}

.coq-quick-btn {
  padding: 4px 12px;
  border: 1px solid var(--coq-border);
  border-radius: 4px;
  font-size: 12px;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.15s ease;
  background: var(--coq-bg);
  color: var(--coq-slate);
  font-family: inherit;
}

.coq-quick-btn:hover {
  border-color: var(--coq-blue);
  color: var(--coq-navy);
}

.coq-quick-active {
  background: var(--coq-navy) !important;
  border-color: var(--coq-navy) !important;
  color: #fff !important;
}

/* ============ 搜索栏（内联，无边框框） ============ */
.coq-search {
  padding: 0 24px 12px;
  border-bottom: 1px solid var(--coq-border);
}

.coq-search-grid {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.coq-search-cell {
  position: relative;
  min-width: 150px;
}

.coq-search-date {
  min-width: 140px;
}

.coq-search-icon {
  position: absolute;
  left: 10px;
  top: 50%;
  transform: translateY(-50%);
  color: var(--coq-text-muted);
  font-size: 11px;
  pointer-events: none;
  z-index: 1;
}

.coq-search-input {
  width: 100%;
  padding: 7px 12px 7px 30px;
  border: 1px solid var(--coq-border);
  border-radius: 6px;
  font-size: 13px;
  outline: none;
  transition: border-color 0.15s ease, box-shadow 0.15s ease;
  background: var(--coq-bg);
  font-family: inherit;
  color: var(--coq-text);
  box-sizing: border-box;
}

.coq-search-input::placeholder {
  color: var(--coq-text-muted);
}

.coq-search-input:focus {
  border-color: var(--coq-blue);
  box-shadow: 0 0 0 3px rgba(91, 141, 239, 0.12);
}

.coq-search-sep {
  color: var(--coq-text-muted);
  font-size: 13px;
  padding: 0 2px;
}

.coq-search-go {
  margin-left: auto;
}

/* ============ 高级筛选 ============ */
.coq-advanced {
  padding: 12px 24px;
  background: var(--coq-bg-soft);
  border-bottom: 1px solid var(--coq-border);
}

.coq-advanced-row {
  display: flex;
  align-items: flex-end;
  gap: 12px;
  flex-wrap: wrap;
}

.coq-advanced-cell {
  display: flex;
  flex-direction: column;
  gap: 4px;
  min-width: 160px;
  flex: 1;
}

.coq-advanced-label {
  font-size: 11px;
  font-weight: 600;
  color: var(--coq-slate);
  letter-spacing: 0.02em;
}

.coq-advanced-input {
  width: 100%;
  padding: 6px 10px;
  border: 1px solid var(--coq-border);
  border-radius: 6px;
  font-size: 13px;
  outline: none;
  transition: border-color 0.15s ease, box-shadow 0.15s ease;
  background: var(--coq-bg);
  font-family: inherit;
  color: var(--coq-text);
  box-sizing: border-box;
}

.coq-advanced-input::placeholder {
  color: var(--coq-text-muted);
}

.coq-advanced-input:focus {
  border-color: var(--coq-blue);
  box-shadow: 0 0 0 3px rgba(91, 141, 239, 0.12);
}

.coq-advanced-reset {
  flex: 0 0 auto;
}

/* 折叠动画 */
.coq-slide-enter-active,
.coq-slide-leave-active {
  transition: all 0.2s ease;
  overflow: hidden;
  max-height: 200px;
}

.coq-slide-enter-from,
.coq-slide-leave-to {
  opacity: 0;
  max-height: 0;
  padding-top: 0;
  padding-bottom: 0;
}

/* ============ 结果区 ============ */
.coq-body {
  min-height: 200px;
}

/* ============ 表格（与审核订单 PendingOrdersPanel 视觉一致） ============ */
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
  background: var(--color-surface, #f8fafc);
  font-weight: 600;
  color: var(--color-text-secondary);
  font-size: 12px;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  border-bottom: 2px solid var(--color-border-light, #e2e8f0);
  white-space: nowrap;
  text-align: left;
  position: sticky;
  top: 0;
  z-index: 1;
}

.coq-w-date { width: 120px; min-width: 120px; white-space: nowrap; }
.coq-w-customer { width: 18%; min-width: 140px; }
.coq-w-product { width: auto; min-width: 200px; }
.coq-w-num { width: 100px; min-width: 100px; white-space: nowrap; }
.coq-w-status { width: 90px; min-width: 90px; white-space: nowrap; text-align: center; }

/* 数量列标题强制右对齐，与数据列对齐 */
.coq-table thead th.coq-th-num,
.coq-th-num {
  text-align: right !important;
  letter-spacing: 0;
}

/* 表头标题间距重新分配 */
.coq-table thead th.coq-w-date { padding-left: 16px; padding-right: 12px; }
.coq-table thead th.coq-w-customer { padding-left: 12px; padding-right: 12px; }
.coq-table thead th.coq-w-product { padding-left: 12px; padding-right: 16px; }
.coq-table thead th.coq-w-num { padding-left: 16px; padding-right: 116px; }
.coq-table thead th.coq-w-status { padding-left: 8px; padding-right: 8px; }

.coq-td-num { padding-right: 116px !important; }

.coq-row {
  cursor: pointer;
  transition: background 0.15s ease;
}

.coq-table tbody td {
  padding: 10px 14px;
  border-bottom: 1px solid var(--color-border-light, #f1f5f9);
  color: var(--color-text);
  vertical-align: middle;
}

.coq-table tbody tr:last-child td {
  border-bottom: 1px solid var(--color-border, #e2e8f0);
}

/* 表格末尾分组不显示多余分隔线 */
.coq-table tbody:last-child tr:last-child td {
  border-bottom: none;
}

.coq-po-group {
  cursor: pointer;
  transition: background 0.15s ease;
}

/* 分组 hover：同 PO 的所有行（含 rowspan 合并单元格）同步高亮 */
.coq-po-group:hover td,
.coq-po-group:hover tr {
  background: var(--color-primary-50);
}

.coq-td-muted {
  color: var(--color-text-secondary);
  font-size: 12px;
}

.coq-td-product {
  max-width: 360px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  text-align: left;
}

.coq-td-num {
  text-align: right;
  font-weight: 600;
  font-size: 13px;
}

/* ============ 状态徽章（圆角 pill，与审核订单一致） ============ */
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
.coq-badge-muted { background: #f1f5f9; color: var(--coq-slate, #64748b); }

/* ============ 分页 ============ */
.coq-pagination {
  padding: 12px 24px;
  border-top: 1px solid var(--coq-border-light);
}

/* ============ 骨架屏 ============ */
.coq-skeleton {
  padding: 0 24px;
}

.coq-skeleton-row {
  height: 42px;
  border-bottom: 1px solid var(--coq-border-light);
  background: linear-gradient(90deg, var(--coq-bg-soft) 0%, #eef2f7 50%, var(--coq-bg-soft) 100%);
  background-size: 200% 100%;
  animation: coq-shimmer 1.5s ease-in-out infinite;
}

.coq-skeleton-row:nth-child(1) { animation-delay: 0s; }
.coq-skeleton-row:nth-child(2) { animation-delay: 0.1s; }
.coq-skeleton-row:nth-child(3) { animation-delay: 0.2s; }
.coq-skeleton-row:nth-child(4) { animation-delay: 0.3s; }
.coq-skeleton-row:nth-child(5) { animation-delay: 0.4s; }
.coq-skeleton-row:nth-child(6) { animation-delay: 0.5s; }
.coq-skeleton-row:nth-child(7) { animation-delay: 0.6s; }
.coq-skeleton-row:nth-child(8) { animation-delay: 0.7s; }

@keyframes coq-shimmer {
  0% { background-position: 200% 0; }
  100% { background-position: -200% 0; }
}

/* ============ 空状态 ============ */
.coq-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 4px;
  padding: 56px 20px;
}

.coq-empty i {
  font-size: 32px;
  color: var(--coq-border);
  margin-bottom: 8px;
}

.coq-empty-text {
  margin: 0;
  font-size: 14px;
  font-weight: 600;
  color: var(--coq-text-secondary);
}

.coq-empty-hint {
  margin: 0;
  font-size: 12px;
  color: var(--coq-text-muted);
}

/* ============ 刷新进度条 ============ */
.coq-fetching {
  height: 2px;
  background: var(--coq-border-light);
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

/* ============ 响应式 ============ */
@media (max-width: 1024px) {
  .coq-advanced-row {
    flex-direction: column;
    align-items: stretch;
  }

  .coq-advanced-reset {
    align-self: flex-start;
  }
}

@media (max-width: 768px) {
  .coq-search-grid {
    flex-direction: column;
    align-items: stretch;
  }

  .coq-search-cell {
    min-width: unset;
  }

  .coq-search-sep {
    display: none;
  }

  .coq-search-go {
    margin-left: 0;
  }
}
</style>
