<template>
  <div class="pc-section">
    <div class="pc-section-header">
      <div class="pc-section-title">
        <FontAwesomeIcon icon="inbox" aria-hidden="true" /> 待审核订单
      </div>
      <div class="pc-section-actions">
        <button
          class="pc-btn pc-btn-success"
          :disabled="validSelectedCount === 0 || submitting"
          @click="$emit('oneClickGenerate')"
        >
          <UiLoadingIcon :loading="submitting" icon="magic" /> 一键审核订单 ({{ validSelectedCount }})
        </button>
      </div>
    </div>

    <!-- Loading (initial only) -->
    <div v-if="loading && orders.length === 0" class="pc-loading-state">
      <UiSpinner />
    </div>

    <!-- Empty -->
    <div v-else-if="orders.length === 0" class="pc-empty-state">
      <FontAwesomeIcon icon="inbox" aria-hidden="true" />
      <span>暂无未处理订单</span>
    </div>

    <!-- Table -->
    <template v-else>
      <div class="pc-section-body">
        <div v-if="fetching" class="pc-fetching-bar"><div class="pc-fetching-progress" /></div>
        <div class="pc-table-wrap">
          <table>
          <thead>
            <tr>
              <th style="width:60px">
                <div class="pc-th-check">
                  <UiCheckbox :checked="allSelected" @update:checked="$emit('toggleAll', $event)" />
                  <span>全选</span>
                </div>
              </th>
              <th style="width:1%;white-space:nowrap;text-align:left">下单时间</th>
              <th class="pc-customer-th" style="text-align:left">客户名称</th>
              <th style="text-align:left">条码</th>
              <th style="text-align:left">产品名称</th>
              <th style="text-align:right">数量</th>
              <th style="text-align:center">操作</th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="o in orders"
              :key="o.composite_id"
              :class="{ 'pc-row-selected': selectedSet.has(o.composite_id), 'pc-row-multi-sku': (o.sku_count || 1) > 1 }"
              @click="$emit('toggleSelection', o.composite_id)"
            >
              <td class="pc-td-center" @click.stop>
                <UiCheckbox :checked="selectedSet.has(o.composite_id)" @update:checked="$emit('toggleSelection', o.composite_id)" />
              </td>
              <td class="pc-td-nowrap">
                <div class="pc-order-meta-cell">
                  <div class="pc-order-badges">
                    <span v-if="(o.sku_count || 1) > 1" class="pc-sku-badge" :title="`${o.sku_count} 个 SKU`">{{ o.sku_count }} SKU</span>
                    <span v-if="o.record_type === 'stockin'" class="pc-type-badge pc-type-badge--stockin">备货</span>
                    <span v-else class="pc-type-badge pc-type-badge--order">订单</span>
                  </div>
                  <span class="pc-order-date">{{ formatDate(o.create_time || o.order_date) }}</span>
                </div>
              </td>
              <td class="pc-td-truncate pc-customer-cell" style="max-width:120px">{{ o.customer || '-' }}</td>
              <td class="pc-barcode-cell">
                <template v-if="o.items && o.items.length > 0">
                  <div v-for="item in o.items" :key="item.id" class="pc-barcode-line">
                    <span class="pc-barcode-text">{{ item.product_barcode || '-' }}</span>
                  </div>
                </template>
                <template v-else><span class="pc-barcode-text">{{ o.barcode || '-' }}</span></template>
              </td>
              <td class="pc-sku-cell">
                <template v-if="o.items && o.items.length > 0">
                  <div
                    v-for="item in o.items"
                    :key="item.id"
                    class="pc-sku-line"
                  >
                    <span class="pc-sku-name" :title="item.has_bom === false ? `产品名称（该产品未配置 BOM）` : `产品名称`">{{ item.product_name || '-' }}</span>
                    <span v-if="item.order_type === 'custom'" class="pc-sku-tag pc-sku-tag--custom">定制</span>
                    <span v-if="item.country" class="pc-sku-tag">{{ item.country }}</span>
                  </div>
                </template>
                <span v-else>{{ o.product_name || '-' }}</span>
              </td>
              <td class="pc-td-right pc-sku-qty-cell">
                <template v-if="o.items && o.items.length > 0">
                  <div v-for="item in o.items" :key="item.id" class="pc-sku-qty">
                    {{ formatNumber(item.quantity) }}
                    <span v-if="item.deduct_quantity" class="pc-sku-deduct" :title="`抵扣备货 ${item.deduct_quantity}`">−{{ item.deduct_quantity }}</span>
                  </div>
                </template>
                <template v-else>{{ formatNumber(o.quantity) }}</template>
              </td>
              <td class="pc-td-center" @click.stop>
                <button
                  v-if="o.has_bom"
                  class="pc-btn pc-btn-success pc-btn-sm"
                  :disabled="submitting"
                  @click="$emit('quickGenerate', o.composite_id)"
                >
                  <UiLoadingIcon :loading="submitting" icon="magic" /> 审核
                </button>
                <button
                  v-else
                  class="pc-btn pc-btn-danger pc-btn-sm"
                  @click="$emit('noBomError', o)"
                >
                  <FontAwesomeIcon icon="exclamation-circle" aria-hidden="true" /> 未配置BOM
                </button>
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <!-- Pagination -->
      <UiPagination v-if="totalPages > 1" :current-page="currentPage" :total-pages="totalPages" :total-items="total" @update:current-page="$emit('changePage', $event)" />
      </div>
    </template>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import UiCheckbox from '@/components/ui/UiCheckbox.vue'
import UiPagination from '@/components/ui/UiPagination.vue'
import type { UnprocessedOrder } from '@/types'
import { formatDate, formatNumber } from '@/utils/format'

const props = defineProps<{
  orders: UnprocessedOrder[]
  loading: boolean
  fetching?: boolean
  total: number
  currentPage: number
  totalPages: number
  selectedCompositeIds: string[]
  selectedCount: number
  validSelectedCount: number
  allSelected: boolean
  submitting: boolean
}>()

const selectedSet = computed(() => new Set(props.selectedCompositeIds))

defineEmits<{
  toggleAll: [checked: boolean]
  toggleSelection: [compositeId: string]
  oneClickGenerate: []
  quickGenerate: [compositeId: string]
  noBomError: [order: any]
  changePage: [page: number]
}>()
</script>

<style scoped>
.pc-section {
  border-bottom: 1px solid var(--color-border-light, #e2e8f0);
}

.pc-section-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 8px 24px 10px;
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
  transition: border-color 0.3s ease, color 0.3s ease, background 0.3s ease;
  background: white;
}

.pc-btn:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}

.pc-btn-sm {
  padding: 5px 10px;
  font-size: 11px;
}

.pc-btn-success {
  color: var(--color-success-600);
  border-color: var(--color-success-200);
  background: var(--color-success-50);
}

.pc-btn-success:hover:not(:disabled) {
  background: var(--color-success-500);
  color: white;
  border-color: transparent;
}

.pc-btn-danger {
  color: var(--color-danger-600, #dc2626);
  border-color: var(--color-danger-200, #fecaca);
  background: var(--color-danger-50, #fef2f2);
}

.pc-btn-danger:hover {
  background: var(--color-danger-500, #ef4444);
  color: white;
  border-color: transparent;
}

.pc-btn-disabled {
  opacity: 0.4;
  cursor: not-allowed;
}

/* Section body - consistent padding with header */
.pc-section-body {
  padding: 0 24px;
}

/* Table */
.pc-table-wrap {
  padding: 0 0 16px;
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
  text-align: left;
}

.pc-th-check {
  display: inline-flex;
  align-items: center;
  gap: 4px;
}

.pc-th-check span {
  font-size: 12px;
  font-weight: 600;
  color: var(--color-text-secondary);
}

.pc-table-wrap tbody td {
  padding: 10px 14px;
  border-bottom: 1px solid var(--color-border-light, #f1f5f9);
  color: var(--color-text);
  vertical-align: middle;
  cursor: pointer;
  transition: background 0.15s ease;
}

.pc-table-wrap tbody tr:hover td {
  background: var(--color-primary-50);
}

.pc-table-wrap tbody tr:last-child td {
  border-bottom: none;
}

.pc-row-selected td {
  background: rgba(0, 148, 191, 0.06);
}

.pc-td-center { text-align: center; }
.pc-td-right { text-align: right; }
.pc-td-nowrap { white-space: nowrap; }
.pc-td-truncate { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }

.pc-customer-cell {
  padding-left: 44px !important;
}

.pc-customer-th {
  padding-left: 44px !important;
}

.pc-order-meta-cell {
  display: flex;
  align-items: center;
  gap: 8px;
  width: 100%;
  min-height: 100%;
  margin-left: -30px;
}

.pc-order-badges {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 4px;
}

.pc-order-badges .pc-type-badge,
.pc-order-badges .pc-sku-badge {
  margin: 0;
  flex-shrink: 0;
}

.pc-order-date {
  flex-shrink: 0;
}

.pc-type-badge {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  padding: 1px 6px;
  margin-right: 6px;
  font-size: 10px;
  font-weight: 700;
  border-radius: 4px;
  line-height: 1.2;
  vertical-align: middle;
  height: 18px;
  min-width: 48px;
  box-sizing: border-box;
}

.pc-type-badge--order {
  background: var(--color-success-50, #e8f9ef);
  color: var(--color-success-600, #1e9e55);
}

.pc-type-badge--stockin {
  background: var(--color-warning-50, #fff3e6);
  color: var(--color-warning-600, #e88e2e);
}

/* === Multi-SKU display === */
.pc-sku-badge {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  padding: 1px 6px;
  margin-left: 4px;
  font-size: 10px;
  font-weight: 700;
  border-radius: 4px;
  background: var(--color-primary-100, #dbeafe);
  color: var(--color-primary-700, #1d4ed8);
  vertical-align: middle;
  letter-spacing: 0.02em;
  height: 18px;
  min-width: 48px;
  box-sizing: border-box;
}

.pc-row-multi-sku td {
  vertical-align: top;
}

.pc-sku-cell {
  padding: 8px 14px !important;
  max-width: 360px;
}

.pc-sku-line {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 2px 0;
  font-size: 13px;
  line-height: 1.4;
  border-bottom: 1px dashed var(--color-border-light, #f1f5f9);
}

.pc-sku-line:last-child {
  border-bottom: none;
}

.pc-sku-name {
  font-weight: 500;
  color: var(--color-text);
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.pc-barcode-text {
  font-family: 'SF Mono', 'Fira Code', 'Consolas', monospace;
  font-size: 12px;
  color: var(--color-text-muted, #94a3b8);
  letter-spacing: 0.04em;
  flex-shrink: 0;
}

.pc-sku-tag {
  display: inline-flex;
  align-items: center;
  padding: 1px 6px;
  font-size: 10px;
  font-weight: 600;
  border-radius: 4px;
  background: var(--color-surface, #f1f5f9);
  color: var(--color-text-secondary, #64748b);
  flex-shrink: 0;
}

.pc-sku-tag--custom {
  background: var(--color-warning-50, #fff3e6);
  color: var(--color-warning-600, #e88e2e);
}

.pc-sku-warn {
  color: var(--color-danger-500, #ef4444);
  font-size: 11px;
  flex-shrink: 0;
}

.pc-barcode-cell {
  padding: 8px 14px !important;
  max-width: 160px;
  text-align: left;
}

.pc-barcode-line {
  display: flex;
  align-items: center;
  padding: 2px 0;
  font-size: 13px;
  line-height: 1.4;
  border-bottom: 1px dashed var(--color-border-light, #f1f5f9);
}

.pc-barcode-line:last-child {
  border-bottom: none;
}

.pc-sku-qty-cell {
  padding: 8px 14px !important;
}

.pc-sku-qty {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 4px;
  padding: 2px 0;
  font-size: 13px;
  font-weight: 600;
  line-height: 1.4;
  border-bottom: 1px dashed var(--color-border-light, #f1f5f9);
  color: var(--color-text);
}

.pc-sku-qty:last-child {
  border-bottom: none;
}

.pc-sku-deduct {
  font-size: 11px;
  font-weight: 500;
  color: var(--color-warning-600, #e88e2e);
}

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
