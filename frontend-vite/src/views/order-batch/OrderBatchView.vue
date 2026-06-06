<template>
  <div class="ob-container">
    <div class="ob-card ob-card-main">
      <!-- Card Header -->
      <div class="ob-card-header">
        <div class="ob-header-left">
          <div class="ob-card-title-group">
            <div class="ob-icon-box ob-icon-blue">
              <i class="fas fa-layer-group" aria-hidden="true"></i>
            </div>
            <div>
              <h3 class="ob-card-title">订单批次号管理</h3>
              <small class="ob-card-subtitle">按客户产品分组管理批次号</small>
            </div>
          </div>
        </div>
        <div class="ob-header-right">
          <div class="ob-tab-group" role="tablist">
            <button
              v-for="tab in tabs" :key="tab.key"
              role="tab"
              :aria-selected="activeTab === tab.key"
              :class="['ob-tab', { 'ob-tab--active': activeTab === tab.key }]"
              @click="activeTab = tab.key"
            >{{ tab.label }}</button>
          </div>
          <button class="ob-action-btn" @click="showHistory = true">
            <i class="fas fa-history" aria-hidden="true"></i> 历史记录
          </button>
        </div>
      </div>

      <!-- Search -->
      <div class="ob-filterbar">
        <div class="ob-search-wrap">
          <i class="fas fa-search ob-search-icon" aria-hidden="true"></i>
          <input
            v-model="keywordSearch"
            class="ob-search-input"
            placeholder="搜索产品名"
            @input="page = 1"
          />
        </div>
      </div>

      <!-- Body -->
      <div class="ob-body">
        <div v-if="isLoading" class="ob-empty-state">
          <i class="fas fa-spinner fa-spin" aria-hidden="true"></i>
          <span>加载中…</span>
        </div>
        <div v-else-if="orders.length === 0" class="ob-empty-state">
          <i class="fas fa-inbox" aria-hidden="true"></i>
          <span>暂无订单数据</span>
        </div>

        <template v-else>
          <div class="ob-toolbar">
            <span class="ob-toolbar-count">共 {{ groupedOrders.length }} 组 / {{ total }} 条订单</span>
          </div>

          <div class="ob-table-wrap">
            <table class="ob-table">
              <thead>
                <tr>
                  <th>客户名称</th>
                  <th>产品名称</th>
                  <th>
                    <div class="ob-detail-header">
                      <span class="ob-detail-hcell ob-detail-hcell--date">时间</span>
                      <span class="ob-detail-hcell ob-detail-hcell--batch">批次号</span>
                      <span class="ob-detail-hcell ob-detail-hcell--qty">数量</span>
                    </div>
                  </th>
                </tr>
              </thead>
              <tbody>
                <template v-for="group in groupedOrders" :key="group.key">
                  <tr>
                    <td class="ob-td-customer">{{ group.customer }}</td>
                    <td class="ob-td-product">{{ group.productName || '-' }}</td>
                    <td class="ob-td-details">
                      <div v-for="item in group.items" :key="item.id" class="ob-detail-row">
                        <span class="ob-detail-date">{{ formatDate(item.order_date) }}</span>
                        <input
                          class="ob-batch-input"
                          :value="item.batch_no || ''"
                          placeholder="输入批次号"
                          name="batch-no"
                          autocomplete="off"
                          @blur="saveBatchNo(item.id, ($event.target as HTMLInputElement).value)"
                          @keydown.enter="saveBatchNo(item.id, ($event.target as HTMLInputElement).value); ($event.target as HTMLInputElement).blur()"
                        />
                        <span class="ob-detail-qty">{{ item.quantity }}</span>
                      </div>
                    </td>
                  </tr>
                </template>
              </tbody>
            </table>
          </div>

          <div class="ob-pager">
            <button class="ob-action-btn" :disabled="page <= 1" @click="handlePageChange(page - 1)" aria-label="上一页">
              <i class="fas fa-chevron-left" aria-hidden="true"></i>
            </button>
            <span class="ob-pager-info">{{ page }} / {{ totalPages }}</span>
            <button class="ob-action-btn" :disabled="page >= totalPages" @click="handlePageChange(page + 1)">
              <i class="fas fa-chevron-right" aria-hidden="true"></i>
            </button>
            <span class="ob-pager-total">共 {{ total }} 条</span>
          </div>
        </template>
      </div>
    </div>

    <OrderBatchHistoryView v-if="showHistory" @close="showHistory = false" />
  </div>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useOrderBatch } from './composables/useOrderBatch'
import { useBatchActions } from './composables/useBatchActions'
import { useOrderBatchWs } from './composables/useOrderBatchWs'
import OrderBatchHistoryView from './OrderBatchHistoryView.vue'
import type { OrderBatchItem } from '@/types'
import { formatDate } from '@/utils/format'

const {
  page, perPage, customerFilter, keywordSearch,
  orders, total, isLoading,
  handlePageChange,
} = useOrderBatch()

const actions = useBatchActions()
useOrderBatchWs(ref(true))

const showHistory = ref(false)

// TAB 配置
const tabs = [
  { key: 'MINISO国际', label: 'MINISO国际' },
  { key: 'MINISO电商', label: 'MINISO电商' },
  { key: 'MINISO国内', label: 'MINISO国内' },
  { key: 'MINISO小程序', label: 'MINISO小程序' },
]
const activeTab = ref(tabs[0].key)

watch(activeTab, (val) => {
  customerFilter.value = val
  page.value = 1
}, { immediate: true })

const totalPages = computed(() => Math.max(1, Math.ceil(total.value / perPage.value)))

interface OrderGroup {
  key: string
  customer: string
  productName: string | null
  items: OrderBatchItem[]
}

const groupedOrders = computed<OrderGroup[]>(() => {
  const map = new Map<string, OrderGroup>()
  for (const o of orders.value) {
    const key = `${o.customer}||${o.product_name ?? ''}`
    if (!map.has(key)) {
      map.set(key, { key, customer: o.customer, productName: o.product_name, items: [] })
    }
    map.get(key)!.items.push(o)
  }
  return Array.from(map.values())
})



async function saveBatchNo(orderId: number, value: string) {
  const trimmed = value.trim()
  await actions.updateBatchNo(orderId, { batch_no: trimmed || null })
}
</script>

<style scoped>
/* Container - 沉浸式全屏，禁止 100vh */
.ob-container {
  padding: 8px;
  margin: 0 auto;
  height: 100%;
  display: flex;
  flex-direction: column;
  box-sizing: border-box;
}

/* Card */
.ob-card {
  background: white;
  border-radius: 18px;
  border: 1px solid var(--color-border-light, #e2e8f0);
  box-shadow: 0 1px 3px rgba(0,0,0,0.04), 0 4px 12px rgba(0,0,0,0.06);
  transition: box-shadow 0.4s cubic-bezier(0.4, 0, 0.2, 1);
}
.ob-card:hover {
  box-shadow: 0 8px 24px rgba(0,0,0,0.06), 0 24px 80px rgba(0,0,0,0.08);
}
.ob-card-main {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-height: 0;
  overflow: hidden;
}

/* Card Header */
.ob-card-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  flex-wrap: wrap;
  padding: 14px 24px 10px;
  background: transparent;
  gap: 12px;
}
.ob-header-left {
  flex: 1;
  display: flex;
  align-items: center;
}
.ob-header-right {
  display: flex;
  align-items: flex-start;
  justify-content: flex-end;
  gap: 8px;
}

/* Title Group */
.ob-card-title-group {
  display: flex;
  align-items: center;
  gap: 12px;
}
.ob-icon-box {
  width: 46px; height: 46px; border-radius: 13px;
  display: flex; align-items: center; justify-content: center;
  flex-shrink: 0;
}
.ob-icon-box i { font-size: 19px; }
.ob-icon-blue {
  background: linear-gradient(135deg, var(--color-primary-100, #dbeafe), var(--color-primary-200, #bfdbfe));
}
.ob-icon-blue i { color: var(--color-primary-500, #3b82f6); }
.ob-card-title {
  font-size: 14px; font-weight: 700; color: var(--color-heading, #1e293b);
  margin: 0; line-height: 1.3;
}
.ob-card-subtitle {
  font-size: 12px; color: var(--color-text-muted, #94a3b8); font-weight: 400;
}

/* TAB Group - 侧边栏风格白色圆角容器 */
.ob-tab-group {
  display: inline-flex;
  gap: 4px;
  padding: 4px;
  border-radius: 12px;
  background: white;
  border: 1px solid var(--color-border-light, #e2e8f0);
  box-shadow: 0 1px 3px rgba(0,0,0,0.04), 0 4px 12px rgba(0,0,0,0.06);
}
.ob-tab {
  padding: 8px 14px;
  border: none;
  border-radius: 9px;
  background: transparent;
  font-size: 13px;
  font-weight: 600;
  color: var(--color-text-secondary, #64748b);
  cursor: pointer;
  transition: background 0.3s ease, color 0.3s ease, box-shadow 0.3s ease, transform 0.3s ease;
  white-space: nowrap;
}
.ob-tab:hover {
  background: var(--color-primary-50, #eff6ff);
  color: var(--color-primary-600, #2563eb);
  box-shadow: 0 4px 12px rgba(0,0,0,0.08);
  transform: translateY(-1px);
}
.ob-tab--active {
  background: linear-gradient(135deg, var(--color-primary-50, #eff6ff), var(--color-primary-100, #dbeafe));
  color: var(--color-primary-700, #1d4ed8);
  box-shadow: 0 4px 12px rgba(0,0,0,0.08), 0 2px 8px rgba(91, 141, 239, 0.2);
  transform: translateY(-1px);
}

/* Action Button */
.ob-action-btn {
  padding: 7px 14px;
  border-radius: 9px;
  border: 2px solid var(--color-border-light, #e2e8f0);
  background: white;
  font-size: 12px;
  font-weight: 600;
  color: var(--color-primary-600, #2563eb);
  cursor: pointer;
  transition: background 0.3s ease, border-color 0.3s ease, transform 0.3s ease;
  display: inline-flex;
  align-items: center;
  gap: 6px;
}
.ob-action-btn:hover:not(:disabled) {
  background: var(--color-primary-50, #eff6ff);
  border-color: var(--color-primary-300, #93c5fd);
  transform: translateY(-1px);
}
.ob-action-btn:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}

/* Filter Bar */
.ob-filterbar {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 0 24px 14px;
  flex-wrap: wrap;
}
/* Search */
.ob-search-wrap {
  position: relative;
  margin-left: auto;
  min-width: 200px;
}
.ob-search-icon {
  position: absolute;
  left: 14px;
  top: 50%;
  transform: translateY(-50%);
  font-size: 13px;
  color: var(--color-text-muted, #94a3b8);
  pointer-events: none;
}
.ob-search-input {
  width: 100%;
  padding: 12px 16px 12px 42px;
  font-size: 0.9375rem;
  line-height: 1.5;
  color: var(--color-heading, #1e293b);
  background: white;
  border: 2px solid var(--color-border-light, #e2e8f0);
  border-radius: var(--radius-input, 12px);
  transition: border-color 0.3s ease, box-shadow 0.3s ease;
  outline: none;
  min-height: 44px;
  box-sizing: border-box;
  font-family: inherit;
}
.ob-search-input:focus-visible { outline: 2px solid var(--color-primary-500); outline-offset: 2px; }
.ob-search-input:focus {
  background: white;
  border-color: var(--color-primary-400, #60a5fa);
  box-shadow: 0 0 0 4px rgba(0, 148, 191, 0.1);
}
.ob-search-input::placeholder {
  color: var(--color-text-muted, #94a3b8);
  font-size: 14px;
  font-weight: 400;
  opacity: 1;
}

/* Body */
.ob-body {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-height: 0;
  overflow: hidden;
  padding: 0 24px 24px;
}

/* Empty / Loading */
.ob-empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 10px;
  padding: 40px 20px;
  color: var(--color-text-muted, #94a3b8);
  font-size: 14px;
}
.ob-empty-state i {
  font-size: 28px;
  opacity: 0.5;
}

/* Toolbar */
.ob-toolbar {
  display: flex;
  align-items: center;
  margin-bottom: 12px;
  flex-shrink: 0;
}
.ob-toolbar-count {
  font-size: 13px;
  color: var(--color-text-secondary, #64748b);
  font-weight: 500;
}

/* Table */
.ob-table-wrap {
  flex: 1;
  overflow: auto;
  border-radius: 10px;
  border: 1px solid var(--color-border-light, #e2e8f0);
  min-height: 0;
}
.ob-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 13px;
}
.ob-table th {
  text-align: left;
  padding: 10px 14px;
  font-size: 12px;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  background: var(--color-surface, #f8fafc);
  border-bottom: 2px solid var(--color-border-light, #e2e8f0);
  color: var(--color-text-secondary, #64748b);
  white-space: nowrap;
  position: sticky;
  top: 0;
  z-index: 1;
}
.ob-table td {
  padding: 10px 14px;
  font-size: 13px;
  color: var(--color-text, #334155);
  border-bottom: 1px solid var(--color-border-light, #f1f5f9);
  vertical-align: top;
  transition: background 0.2s ease;
}
.ob-table tbody tr:hover td {
  background: var(--color-primary-50, #eff6ff);
}

.ob-td-customer { font-weight: 600; min-width: 100px; color: var(--color-heading, #1e293b); }
.ob-td-product { min-width: 100px; }
.ob-td-details { padding: 6px 14px !important; }

/* Detail header */
.ob-detail-header { display: flex; gap: 8px; align-items: center; }
.ob-detail-hcell { font-weight: 600; font-size: 12px; color: var(--color-text-secondary, #64748b); text-transform: none; letter-spacing: 0; }
.ob-detail-hcell--date { min-width: 90px; }
.ob-detail-hcell--batch { min-width: 160px; }
.ob-detail-hcell--qty { min-width: 60px; text-align: right; }

/* Detail row */
.ob-detail-row {
  display: flex;
  gap: 8px;
  align-items: center;
  padding: 4px 0;
}
.ob-detail-row + .ob-detail-row {
  border-top: 1px solid var(--color-border-light, #f1f5f9);
}
.ob-detail-date {
  min-width: 90px;
  color: var(--color-text-muted, #94a3b8);
  font-size: 12px;
}
.ob-detail-qty {
  min-width: 60px;
  text-align: right;
  font-weight: 600;
  font-size: 13px;
  color: var(--color-heading, #1e293b);
}

/* Batch input - 设计规范统一输入框 */
.ob-batch-input {
  min-width: 160px;
  padding: 0.5rem 0.75rem;
  font-size: 0.9375rem;
  line-height: 1.5;
  color: var(--color-heading, #1e293b);
  background: white;
  border: 2px solid var(--color-border-light, #e2e8f0);
  border-radius: var(--radius-input, 12px);
  transition: border-color 0.3s ease, box-shadow 0.3s ease;
  outline: none;
  font-family: inherit;
  box-sizing: border-box;
}
.ob-batch-input:focus-visible { outline: 2px solid var(--color-primary-500); outline-offset: 2px; }
.ob-batch-input:focus {
  background: var(--color-surface-card, #f8fafc);
  border-color: var(--color-primary-400, #60a5fa);
  box-shadow: 0 0 0 0.2rem rgba(135, 206, 235, 0.25);
}
.ob-batch-input:hover:not(:focus) {
  border-color: var(--color-primary-300, #93c5fd);
}
.ob-batch-input::placeholder {
  color: var(--color-text-muted, #94a3b8);
  font-size: 14px;
  font-weight: 400;
  opacity: 1;
}

/* Pager */
.ob-pager {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 12px;
  padding: 16px 0 0;
  flex-shrink: 0;
}
.ob-pager-info {
  font-size: 14px;
  font-weight: 600;
  color: var(--color-text, #334155);
}
.ob-pager-total {
  font-size: 13px;
  color: var(--color-text-muted, #94a3b8);
  margin-left: 4px;
}

@media (max-width: 768px) {
  .ob-filterbar { flex-direction: column; align-items: stretch; }
  .ob-search-wrap { margin-left: 0; min-width: 0; }
  .ob-detail-header { display: none; }
  .ob-detail-row { flex-wrap: wrap; gap: 4px; }
  .ob-card-header { padding: 12px 16px 8px; }
  .ob-filterbar { padding: 0 16px 12px; }
  .ob-body { padding: 0 16px 16px; }
}
</style>
