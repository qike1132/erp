<template>
  <div class="pc-section">
    <!-- 一键审核按钮已移至 PurchaseView 顶部 TAB 行（右上角） -->

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

const props = withDefaults(defineProps<{
  orders: UnprocessedOrder[]
  loading: boolean
  fetching?: boolean
  total: number
  currentPage: number
  totalPages: number
  selectedCompositeIds: string[]
  selectedCount: number
  allSelected: boolean
  submitting?: boolean
}>(), {
  submitting: false,
})

// P2-12: 已评估——computed(() => new Set(...)) 是最优实现。
// Set.has() O(1) vs Array.includes() O(n)；每次选中变更仅重建 ~15-20 元素的 Set（<0.01ms），
// 远小于模板 diff 开销。无需进一步优化。
const selectedSet = computed(() => new Set(props.selectedCompositeIds))

defineEmits<{
  toggleAll: [checked: boolean]
  toggleSelection: [compositeId: string]
  quickGenerate: [compositeId: string]
  noBomError: [order: UnprocessedOrder]
  changePage: [page: number]
}>()
</script>

<style scoped lang="scss">
@use './order-panels.scss' as *;

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

.pc-order-badges .pc-type-badge,
.pc-order-badges .pc-sku-badge {
  margin: 0;
  flex-shrink: 0;
}

.pc-sku-warn {
  color: var(--color-danger-500, #ef4444);
  font-size: 11px;
  flex-shrink: 0;
}

.pc-sku-deduct {
  font-size: 11px;
  font-weight: 500;
  color: var(--color-warning-600, #e88e2e);
}
</style>
