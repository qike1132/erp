<template>
  <div class="pc-section">
    <!-- 汇总下单/批量确认按钮已移至 PurchaseView 顶部 TAB 行（右上角） -->

    <!-- Loading (initial only) -->
    <div v-if="loading && orders.length === 0" class="pc-loading-state">
      <UiSpinner />
    </div>

    <!-- Error (可重试) -->
    <div v-else-if="error && orders.length === 0" class="pc-error-state">
      <FontAwesomeIcon icon="exclamation-circle" aria-hidden="true" />
      <span>加载失败，请检查网络后重试</span>
      <button class="pc-btn pc-btn-primary pc-btn-sm" @click="$emit('retry')">重试</button>
    </div>

    <!-- Empty -->
    <div v-else-if="orders.length === 0" class="pc-empty-state">
      <FontAwesomeIcon icon="inbox" aria-hidden="true" />
      <span>暂无采购订单</span>
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
                :key="o.id"
                :class="{ 'pc-row-selected': selectedSet.has(o.id), 'pc-row-multi-sku': (o.sku_items?.length || 0) > 1 }"
                @click="$emit('toggleSelection', o.id)"
              >
                <td class="pc-td-center" @click.stop>
                  <UiCheckbox :checked="selectedSet.has(o.id)" @update:checked="$emit('toggleSelection', o.id)" />
                </td>
                <td class="pc-td-nowrap">
                  <div class="pc-order-meta-cell">
                    <span class="pc-order-date">{{ formatDate(o.create_time || o.order_date) }}</span>
                  </div>
                </td>
                <td class="pc-td-truncate pc-customer-cell" style="max-width:120px">{{ o.customer_name || '-' }}</td>
                <td class="pc-barcode-cell">
                  <template v-if="o.sku_items && o.sku_items.length > 0">
                    <div v-for="(item, idx) in o.sku_items" :key="(item.barcode || '') + '-' + idx" class="pc-barcode-line">
                      <span class="pc-barcode-text">{{ item.barcode || '-' }}</span>
                    </div>
                  </template>
                  <template v-else><span class="pc-barcode-text">-</span></template>
                </td>
                <td class="pc-sku-cell">
                  <template v-if="o.sku_items && o.sku_items.length > 0">
                    <div
                      v-for="(item, idx) in o.sku_items"
                      :key="(item.barcode || '') + '-' + idx"
                      class="pc-sku-line"
                    >
                      <span class="pc-sku-name">{{ item.product_name || '-' }}</span>
                    </div>
                  </template>
                  <span v-else>{{ o.product_name || '-' }}</span>
                </td>
                <td class="pc-td-right pc-sku-qty-cell">
                  <template v-if="o.sku_items && o.sku_items.length > 0">
                    <div v-for="(item, idx) in o.sku_items" :key="(item.barcode || '') + '-' + idx" class="pc-sku-qty">
                      {{ formatNumber(item.quantity) }}
                    </div>
                  </template>
                  <template v-else>{{ o.quantity != null ? formatNumber(o.quantity) : '-' }}</template>
                </td>
                <td class="pc-td-center" @click.stop>
                  <button
                    class="pc-btn pc-btn-success pc-btn-sm"
                    @click="$emit('completeOrder', o.id)"
                  >
                    <FontAwesomeIcon icon="check" aria-hidden="true" /> 下单完成
                  </button>
                </td>
              </tr>
            </tbody>
          </table>
        </div>

        <!-- Pagination -->
        <UiPagination v-if="totalPages > 1" :current-page="currentPage" :total-pages="totalPages" :total-items="total" @update:current-page="$emit('update:currentPage', $event)" />
      </div>
    </template>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import UiCheckbox from '@/components/ui/UiCheckbox.vue'
import UiPagination from '@/components/ui/UiPagination.vue'
import type { PurchaseOrder } from '@/types'
import { formatDate, formatNumber } from '@/utils/format'

const props = defineProps<{
  orders: PurchaseOrder[]
  loading: boolean
  fetching?: boolean
  error?: boolean
  total: number
  currentPage: number
  totalPages: number
  selectedIds: number[]
  allSelected: boolean
}>()

// P2-12: 已评估——computed(() => new Set(...)) 是最优实现。
// Set.has() O(1) vs Array.includes() O(n)；每次选中变更仅重建 ~15-20 元素的 Set（<0.01ms），
// 远小于模板 diff 开销。无需进一步优化。
const selectedSet = computed(() => new Set(props.selectedIds))

defineEmits<{
  toggleAll: [checked: boolean]
  toggleSelection: [id: number]
  completeOrder: [id: number]
  'update:currentPage': [page: number]
  retry: []
}>()

</script>

<style scoped lang="scss">
@use './order-panels.scss' as *;
</style>
