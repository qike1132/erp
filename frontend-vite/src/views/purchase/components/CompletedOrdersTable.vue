<template>
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
            v-for="row in flatRows"
            :key="row.o.id"
            class="coq-po-group"
            @click="$emit('viewDetail', row.o.id)"
          >
            <tr
              v-for="(sku, idx) in row.skus"
              :key="row.o.id + '-' + idx"
              class="coq-row"
            >
              <td v-if="idx === 0" class="coq-td coq-td-muted" :rowspan="row.skuCount">
                {{ formatDate(row.o.completed_at) || '—' }}
              </td>
              <td v-if="idx === 0" class="coq-td" :rowspan="row.skuCount">
                {{ row.o.customer_name || '—' }}
              </td>
              <td class="coq-td coq-td-product" :title="sku.product_name">{{ sku.product_name || '—' }}</td>
              <td class="coq-td coq-td-num">{{ formatNumber(sku.quantity) }}</td>
              <td v-if="idx === 0" class="coq-td" :rowspan="row.skuCount">
                <span :class="['coq-badge', getStatusClass(row.o.status)]">
                  {{ getStatusLabel(row.o.status) }}
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
</template>

<script setup lang="ts">
import { computed } from 'vue'
import UiPagination from '@/components/ui/UiPagination.vue'
import type { PurchaseOrder } from '@/types'
import { formatDate, formatNumber } from '@/utils/format'

const props = defineProps<{
  orders: PurchaseOrder[]
  loading: boolean
  fetching?: boolean
  total: number
  currentPage: number
  totalPages: number
}>()

defineEmits<{
  viewDetail: [id: number]
  'update:currentPage': [page: number]
}>()

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

function getSkuRows(o: PurchaseOrder): { product_name: string; quantity: number }[] {
  if (o.sku_items && o.sku_items.length > 0) {
    return o.sku_items.map(s => ({ product_name: s.product_name || '', quantity: s.quantity || 0 }))
  }
  return [{ product_name: o.product_name || '', quantity: o.quantity || 0 }]
}

// P1-6: 预计算 flatRows，避免模板内每行多次调用 getSkuRows(o)
const flatRows = computed(() =>
  props.orders.map((o) => {
    const skus = getSkuRows(o)
    return { o, skus, skuCount: skus.length }
  }),
)
</script>

<style scoped>
.coq-body {
  min-height: 200px;
}

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

.coq-table thead th.coq-th-num,
.coq-th-num {
  text-align: right !important;
  letter-spacing: 0;
}

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

.coq-table tbody:last-child tr:last-child td {
  border-bottom: none;
}

.coq-po-group {
  cursor: pointer;
  transition: background 0.15s ease;
}

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

.coq-pagination {
  padding: 12px 24px;
  border-top: 1px solid var(--coq-border-light);
}

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
</style>