<template>
  <div class="bo-inventory">
    <!-- 筛选栏 -->
    <div class="bo-filter-bar">
      <div class="bo-filter-field">
        <label class="bo-filter-label">订单号</label>
        <input
          v-model="filters.orderNo"
          class="bo-filter-input"
          placeholder="输入订单号（当前页筛选）"
          @keyup.enter="handleSearch()"
        />
      </div>
      <div class="bo-filter-field">
        <label class="bo-filter-label">客户</label>
        <input
          v-model="filters.customer"
          class="bo-filter-input"
          placeholder="输入客户名"
          @keyup.enter="handleSearch()"
        />
      </div>
      <div class="bo-filter-actions">
        <button class="bo-action-btn bo-action-primary" @click="handleSearch()">
          <i class="fas fa-search" style="margin-right: 4px" aria-hidden="true" />查询
        </button>
        <button class="bo-action-btn" @click="handleReset()" aria-label="重置">
          <i class="fas fa-redo" aria-hidden="true" />
        </button>
      </div>
    </div>

    <!-- 表格区 -->
    <div class="bo-card-main">
      <div v-if="isLoading && orders.length === 0" class="bo-empty">
        <UiSpinner />
      </div>
      <div v-else-if="orders.length === 0" class="bo-empty">
        <i class="fas fa-clipboard-list" aria-hidden="true" />
        <span>暂无湖北订单</span>
      </div>
      <template v-else>
        <div v-if="isFetching" class="bo-fetching-bar"><div class="bo-fetching-progress" /></div>
        <table class="bo-table">
          <thead>
            <tr>
              <th class="bo-th-left" style="white-space:nowrap">下单时间</th>
              <th class="bo-th-left">客户名称</th>
              <th class="bo-th-left">工厂</th>
              <th class="bo-th-left">条码</th>
              <th class="bo-th-left">产品名称</th>
              <th class="bo-th-right">数量</th>
              <th class="bo-th-left">备注</th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="item in displayOrders"
              :key="item.id"
              :class="{ 'bo-row-highlight': highlightId !== null && String(item.id) === highlightId, 'bo-row-multi-sku': (item.items?.length || 1) > 1 }"
            >
              <td class="bo-td-left bo-td-nowrap">
                <div class="bo-order-meta-cell">
                  <div class="bo-order-badges">
                    <span v-if="(item.items?.length || 1) > 1" class="bo-sku-badge" :title="`${item.items.length} 个 SKU`">{{ item.items.length }} SKU</span>
                    <span v-if="item.record_type === 'stockin'" class="bo-type-badge bo-type-badge--stockin">备货</span>
                    <span v-else class="bo-type-badge bo-type-badge--order">订单</span>
                  </div>
                  <span class="bo-order-date">{{ item.order_date || '-' }}</span>
                </div>
              </td>
              <td class="bo-td-left bo-td-middle bo-customer-cell" style="max-width:120px">{{ item.customer || '-' }}</td>
              <td class="bo-td-left bo-td-middle"><span class="bo-cell-main">{{ item.factories?.join(', ') || '湖北' }}</span></td>
              <td class="bo-td-left">
                <template v-if="item.items && item.items.length > 0">
                  <div v-for="sku in item.items" :key="sku.id" class="bo-sku-line">
                    <span class="bo-barcode-text">{{ sku.product_barcode || item.product?.barcode || '-' }}</span>
                  </div>
                </template>
                <span v-else class="bo-barcode-text">{{ item.barcode || item.product?.barcode || '-' }}</span>
              </td>
              <td class="bo-td-left">
                <template v-if="item.items && item.items.length > 0">
                  <div v-for="sku in item.items" :key="sku.id" class="bo-sku-line">
                    <span class="bo-sku-name">{{ sku.product_name || '-' }}</span>
                  </div>
                </template>
                <span v-else class="bo-sku-name">{{ item.product_name || '-' }}</span>
              </td>
              <td class="bo-td-right">
                <template v-if="item.items && item.items.length > 0">
                  <div v-for="sku in item.items" :key="sku.id" class="bo-sku-line">
                    <strong>{{ sku.quantity }}</strong>
                  </div>
                </template>
                <template v-else><strong>{{ item.quantity }}</strong></template>
              </td>
              <td class="bo-td-left">
                <template v-if="item.items && item.items.length > 0">
                  <div v-for="sku in item.items" :key="sku.id" class="bo-sku-line">
                    <span v-if="sku.note" class="bo-sku-note" :title="sku.note">{{ sku.note }}</span>
                  </div>
                </template>
                <span v-if="item.note" class="bo-sku-note">{{ item.note }}</span>
              </td>
            </tr>
          </tbody>
        </table>

        <div v-if="displayOrders.length === 0" class="bo-empty bo-empty-inline">
          <i class="fas fa-search-minus" aria-hidden="true" />
          <span>当前页未匹配到该订单号</span>
        </div>

        <UiPagination
          v-if="totalPages > 1"
          :current-page="currentPage"
          :total-pages="totalPages"
          :total-items="totalItems"
          @update:current-page="goPage"
        />
      </template>
    </div>
  </div>
</template>

<script setup lang="ts">
/**
 * BeileOrderTab.vue — 湖北订单列表子组件
 *
 * 职责：以表格展示 factory=湖北 的订单，支持订单号/客户筛选与分页。
 * 数据获取复用 orderApi.beileList，锁定 factory=湖北。
 */
import { reactive, computed, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { useQuery, keepPreviousData } from '@tanstack/vue-query'
import { orderApi } from '@/api'
import type { OrderItem } from '@/types'
import UiPagination from '@/components/ui/UiPagination.vue'
import { useDebouncedRef } from '@/composables/useDebouncedRef'

/** 每页记录数 */
const PER_PAGE = 20

/** 湖北订单行：OrderItem 在后端实际响应中还包含 order_no / customer / product（未在 OrderItem 类型中声明） */
type BeileOrderRow = OrderItem & {
  order_no?: string
  customer?: string
  record_type?: 'order' | 'stockin'
  factories?: string[]
  product?: { id: number; name: string; barcode: string; image: string }
}

const filters = reactive({ orderNo: '', customer: '' })
const debouncedCustomer = useDebouncedRef(computed(() => filters.customer), 300)
const debouncedOrderNo = useDebouncedRef(computed(() => filters.orderNo), 250)
const page = ref(1)

const currentPage = computed(() => page.value)
const totalItems = computed(() => ordersData.value?.total ?? 0)
const totalPages = computed(() => Math.max(1, Math.ceil(totalItems.value / PER_PAGE)))

const {
  data: ordersData,
  isLoading,
  isFetching,
  refetch,
} = useQuery({
  queryKey: ['beile-orders', debouncedCustomer, () => page.value],
  queryFn: () =>
    orderApi.beileList({
      customer: debouncedCustomer.value || undefined,
      page: page.value,
      per_page: PER_PAGE,
    }),
  staleTime: 30_000,
  gcTime: 60_000,
  placeholderData: keepPreviousData,
})

/** 服务端返回的订单列表（已应用 customer/status 筛选与分页） */
const orders = computed<BeileOrderRow[]>(() => (ordersData.value?.data ?? []) as BeileOrderRow[])

/** 订单号在当前页客户端过滤（后端 /orders/list 暂不支持 order_no 服务端筛选） */
const displayOrders = computed<BeileOrderRow[]>(() => {
  const kw = debouncedOrderNo.value.trim().toLowerCase()
  if (!kw) return orders.value
  return orders.value.filter((o) => (o.order_no || '').toLowerCase().includes(kw))
})

/** URL order_id 参数：高亮对应订单行（通知点击跳转场景） */
const route = useRoute()
const highlightId = computed<string | null>(() => {
  const oid = route.query.order_id
  return oid ? String(oid) : null
})

function handleSearch() {
  refetch()
}
function handleReset() {
  filters.orderNo = ''
  filters.customer = ''
  page.value = 1
  refetch()
}
function goPage(p: number) {
  page.value = p
}

// 服务端筛选变化时回到首页
watch(() => debouncedCustomer.value, () => {
  page.value = 1
})
</script>

<style scoped>
.bo-inventory {
  display: flex;
  flex-direction: column;
  min-height: 0;
}

/* ===== 筛选栏 ===== */
.bo-filter-bar {
  display: flex;
  gap: 12px;
  flex-wrap: wrap;
  align-items: flex-end;
  padding: 12px 24px;
  border-bottom: 1px solid var(--color-border-light, #f1f5f9);
}
.bo-filter-field {
  flex-shrink: 0;
}
.bo-filter-label {
  display: block;
  font-size: 12px;
  font-weight: 600;
  color: var(--color-text-secondary);
  margin-bottom: 4px;
}
.bo-filter-input {
  width: 220px;
  padding: 8px 12px;
  border: 2px solid var(--color-border-light, #e2e8f0);
  border-radius: 9px;
  font-size: 13px;
  outline: none;
  transition: border-color 0.3s ease, box-shadow 0.3s ease;
  font-family: inherit;
  color: var(--color-text);
  background: white;
}
.bo-filter-input:focus-visible {
  outline: 2px solid var(--color-primary-500);
  outline-offset: 2px;
}
.bo-filter-input:focus {
  border-color: var(--color-primary-400);
  box-shadow: 0 0 0 4px rgba(0, 148, 191, 0.1);
}
.bo-filter-actions {
  display: flex;
  gap: 8px;
  align-items: flex-end;
}
.bo-action-btn {
  padding: 7px 14px;
  border: 2px solid var(--color-border-light, #e2e8f0);
  border-radius: 9px;
  background: white;
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
  transition: background 0.3s ease, border-color 0.3s ease, transform 0.3s ease;
  color: var(--color-text-secondary);
  display: inline-flex;
  align-items: center;
  font-family: inherit;
  line-height: inherit;
}
.bo-action-primary {
  color: var(--color-primary-600);
}
.bo-action-primary:hover {
  background: var(--color-primary-50);
  border-color: var(--color-primary-300);
  transform: translateY(-1px);
}
.bo-action-btn:hover {
  border-color: var(--color-primary-300);
  color: var(--color-primary-600);
  transform: translateY(-1px);
}

/* ===== 表格区 ===== */
.bo-card-main {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-height: 0;
  overflow: hidden;
}
.bo-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 13px;
}
.bo-table thead {
  background: var(--color-surface, #f8fafc);
  position: sticky;
  top: 0;
  z-index: 1;
}
.bo-table thead th {
  padding: 10px 14px;
  font-size: 12px;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  border-bottom: 2px solid var(--color-border-light, #e2e8f0);
  color: var(--color-text-secondary);
  text-align: center;
  white-space: nowrap;
}
.bo-th-left {
  text-align: left !important;
}
.bo-th-right {
  text-align: right !important;
}
.bo-table tbody td {
  padding: 10px 14px;
  font-size: 13px;
  border-bottom: 1px solid var(--color-border-light, #f1f5f9);
  text-align: center;
  vertical-align: middle;
  transition: background 0.2s ease;
  color: var(--color-text);
}
.bo-td-left {
  text-align: left !important;
}
.bo-table tbody tr:hover {
  background: var(--color-primary-50);
}
/* 通知跳转高亮行 */
.bo-row-highlight {
  background: var(--color-warning-50) !important;
  box-shadow: inset 3px 0 0 var(--color-warning-500);
}
.bo-customer-cell {
  font-weight: 600;
  white-space: nowrap;
}
.bo-cell-main {
  font-weight: 600;
  color: var(--color-text);
}
.bo-cell-muted {
  color: var(--color-text-muted);
  font-size: 12px;
}

/* ===== 多 SKU 分行显示（对齐 purchase 页面风格） ===== */
.bo-table tbody tr td {
  vertical-align: top;
}
.bo-td-middle {
  vertical-align: middle !important;
}
.bo-td-nowrap {
  white-space: nowrap;
}
.bo-td-right {
  text-align: right;
}
.bo-td-right .bo-sku-line {
  text-align: right;
}
.bo-row-multi-sku td {
  vertical-align: top;
}

/* ===== 下单时间列：标签 + 日期（对齐 purchase） ===== */
.bo-order-meta-cell {
  display: flex;
  align-items: center;
  gap: 8px;
}
.bo-order-badges {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 4px;
}
.bo-order-date {
  flex-shrink: 0;
}
.bo-type-badge {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  padding: 1px 6px;
  font-size: 10px;
  font-weight: 700;
  border-radius: 4px;
  line-height: 1.5;
}
.bo-type-badge--order {
  background: var(--color-success-50, #e8f9ef);
  color: var(--color-success-600, #1e9e55);
}
.bo-type-badge--stockin {
  background: var(--color-primary-50, #eff6ff);
  color: var(--color-primary-600, #2563eb);
}
.bo-sku-badge {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  padding: 1px 6px;
  font-size: 10px;
  font-weight: 700;
  border-radius: 4px;
  background: var(--color-primary-50, #eff3fb);
  color: var(--color-primary-600, #5b8def);
}

.bo-sku-line {
  padding: 2px 0;
  font-size: 13px;
  line-height: 1.4;
  border-bottom: 1px dashed var(--color-border-light, #f1f5f9);
}
.bo-sku-line:last-child {
  border-bottom: none;
}
.bo-sku-name {
  font-weight: 500;
  color: var(--color-text);
  display: inline-block;
}
.bo-barcode-text {
  font-family: 'SF Mono', 'Fira Code', 'Consolas', monospace;
  font-size: 12px;
  color: var(--color-text-muted, #94a3b8);
  display: inline-block;
}

/* ===== 备注（对齐 customer-order 详情 SKU 备注样式） ===== */
.bo-sku-note {
  display: inline-block;
  max-width: 160px;
  color: var(--color-text-secondary);
  font-size: 12px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  vertical-align: middle;
}

/* ===== 状态徽章（配色对齐 customer-order co-status-*） ===== */
.bo-status-badge {
  display: inline-block;
  padding: 3px 10px;
  border-radius: 8px;
  font-size: 12px;
  font-weight: 600;
  white-space: nowrap;
}
.bo-status-pending {
  background: var(--color-warning-50);
  color: var(--color-warning-600);
}
.bo-status-stocked {
  background: var(--color-success-100);
  color: var(--color-success-600);
}
.bo-status-partial {
  background: var(--color-primary-50);
  color: var(--color-primary-600);
}
.bo-status-shipping {
  background: #e0e7ff;
  color: #4338ca;
}
.bo-status-shipped {
  background: var(--color-success-50);
  color: var(--color-success-700);
}
.bo-status-cancelled {
  background: var(--color-danger-50);
  color: var(--color-danger-500);
}
.bo-status-completed {
  background: var(--color-primary-50);
  color: var(--color-primary-700);
}

/* ===== 空/加载态 ===== */
.bo-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 10px;
  padding: 40px 20px;
  color: var(--color-text-muted);
}
.bo-empty i {
  font-size: 28px;
  opacity: 0.5;
}
.bo-empty span {
  font-size: 14px;
}
.bo-empty-inline {
  padding: 24px 20px;
}

/* Fetching progress bar */
.bo-fetching-bar {
  height: 2px;
  background: var(--color-primary-100, #e0f2fe);
  overflow: hidden;
  border-radius: 1px;
}
.bo-fetching-progress {
  height: 100%;
  width: 30%;
  background: var(--color-primary-500, #3b82f6);
  border-radius: 1px;
  animation: bo-progress-slide 1s ease-in-out infinite;
}
@keyframes bo-progress-slide {
  0% { transform: translateX(-100%); }
  100% { transform: translateX(400%); }
}

@media (max-width: 900px) {
  .bo-filter-input { width: 160px; }
  .bo-filter-select { width: 140px; }
  .bo-table { font-size: 12px; }
  .bo-table thead th,
  .bo-table tbody td { padding: 8px 8px; }
}
</style>
