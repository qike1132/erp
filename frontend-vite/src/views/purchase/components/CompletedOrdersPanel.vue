<template>
  <div class="coq-panel">
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
                <th class="coq-th coq-w-no">订单号</th>
                <th class="coq-th coq-w-customer">客户</th>
                <th class="coq-th coq-w-product">产品名称</th>
                <th class="coq-th coq-th-num coq-w-num">数量</th>
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
                <!-- 订单号（采购订单 PO…，2026-10-10 由 CG 统一为 PO）：订单级事实，整单 rowspan（2026-09-30 新增列） -->
                <td v-if="idx === 0" class="coq-td coq-w-no" :rowspan="row.skuCount">
                  {{ row.o.order_no || '—' }}
                </td>
                <td v-if="idx === 0" class="coq-td" :rowspan="row.skuCount">
                  {{ row.o.customer_name || '—' }}
                </td>
                <td class="coq-td coq-td-product" :title="sku.product_name">
                  {{ sku.product_name || '—' }}
                </td>
                <td class="coq-td coq-td-num">{{ formatNumber(sku.quantity) }}</td>
                <td v-if="idx === 0" class="coq-td coq-w-op" :rowspan="row.skuCount">
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
  /** 是否处于筛选状态 */
  hasFilter: boolean
  /** 已提交生效的筛选条件（胶囊据此渲染；草稿不参与，否则未点「查询」也会出现条件） */
  filters: CompletedOrderFilters
}>()

/** 筛选表单草稿由父组件持有，输入框也在父组件；本组件不再持有 draft */
const emit = defineEmits<{
  reset: []
  'remove-filter': [key: keyof CompletedOrderFilters]
  viewDetail: [id: number]
  'update:currentPage': [page: number]
  retry: []
}>()

const FILTER_LABELS: Record<keyof CompletedOrderFilters, string> = {
  product_name: '产品',
}

/** 已生效条件胶囊：从已提交条件推导，与导出使用的条件同源 */
const activePills = computed(() =>
  (Object.keys(FILTER_LABELS) as (keyof CompletedOrderFilters)[])
    .filter((key) => !!props.filters[key])
    .map((key) => ({ key, label: `${FILTER_LABELS[key]}：${props.filters[key]}` })),
)

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
  gap: 6px;
  height: 34px;
  padding: 0 14px;
  border: 1px solid var(--coq-border);
  border-radius: 9px;
  font-size: 12px;
  font-weight: 600;
  font-family: inherit;
  color: var(--coq-text-secondary);
  background: #fff;
  cursor: pointer;
  transition:
    border-color 0.15s ease,
    color 0.15s ease,
    background 0.15s ease;
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
  background: linear-gradient(135deg, var(--color-primary-500, #5b8def), var(--color-primary-600, #3a6bd6));
  border-color: transparent;
  box-shadow: 0 2px 6px rgba(58, 107, 214, 0.28);
}

.coq-btn-primary:hover:not(:disabled) {
  background: linear-gradient(135deg, var(--color-primary-600, #3a6bd6), var(--color-primary-700, #2d5ab8));
  border-color: transparent;
  box-shadow: 0 4px 12px rgba(58, 107, 214, 0.34);
  color: #fff;
}

/* === 表格 === */
.coq-table-scroll {
  overflow-x: auto;
}

.coq-table {
  width: 100%;
  /* 窄屏改为横向滚动，避免把「数量/操作」压扁 */
  min-width: 940px;
  /* 固定表格布局：列宽严格按下方比例分配，
     否则「产品名称」会独占剩余宽度，右侧两列被挤在一起 */
  table-layout: fixed;
  border-collapse: collapse;
  font-size: 13px;
  font-variant-numeric: tabular-nums;
}

/* 表格单元格统一 border-box，保证百分比列宽不会因内边距溢出 */
.coq-table th,
.coq-table td {
  box-sizing: border-box;
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

/*
 * 列宽比例：内容列按「够用」取宽，把「数量」尽量往左收；
 * 剩余宽度全部留给最后一列「操作」（该列有 padding-left: 214px，不能削），
 * 空白堆在表格最右端而不是中段。5 列 → 6 列（2026-09-30 加订单号）后重新配平，合计仍为 100%。
 */
.coq-w-date {
  width: 13%;
  white-space: nowrap;
}
.coq-w-no {
  width: 14%;
  white-space: nowrap;
}
.coq-w-customer {
  width: 11%;
}
.coq-w-product {
  width: 14%;
}
.coq-w-num {
  width: 8%;
  white-space: nowrap;
}
.coq-w-op {
  width: 40%;
  white-space: nowrap;
  text-align: left;
}

/* 操作列内容整体右移 200px（14px 默认内边距 + 200px），只挪这一列 */
.coq-table th.coq-w-op,
.coq-table td.coq-w-op {
  padding-left: 214px;
}

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
  white-space: nowrap;
}

.coq-td-product {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  text-align: left;
}

/* 行操作按钮：常驻显示 */
.coq-op {
  padding: 3px 10px;
  border: 1px solid var(--coq-border);
  border-radius: 6px;
  background: #fff;
  font-size: 12px;
  font-family: inherit;
  color: var(--coq-text-secondary);
  cursor: pointer;
  transition:
    border-color 0.15s ease,
    color 0.15s ease;
}

.coq-op:hover {
  border-color: var(--coq-blue);
  color: var(--coq-navy);
  background: var(--color-primary-50, #eff5ff);
}

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
  0% {
    background-position: 200% 0;
  }
  100% {
    background-position: -200% 0;
  }
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
  0% {
    transform: translateX(-100%);
  }
  100% {
    transform: translateX(400%);
  }
}

/* === 响应式 === */
@media (max-width: 900px) {
  .coq-pills {
    padding: 10px 14px;
  }
}
</style>
