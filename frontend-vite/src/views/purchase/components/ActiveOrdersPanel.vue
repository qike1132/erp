<template>
  <div class="pc-section">
    <!-- 汇总下单/批量确认按钮已移至 PurchaseView 顶部 TAB 行（右上角） -->

    <!-- Loading (initial only) -->
    <div v-if="loading && orders.length === 0 && unprocessedOrders.length === 0" class="pc-loading-state">
      <UiSpinner />
    </div>

    <!-- Error (可重试) -->
    <div v-else-if="error && orders.length === 0 && unprocessedOrders.length === 0" class="pc-error-state">
      <FontAwesomeIcon icon="exclamation-circle" aria-hidden="true" />
      <span>加载失败，请检查网络后重试</span>
      <button class="pc-btn pc-btn-primary pc-btn-sm" @click="$emit('retry')">重试</button>
    </div>

    <!-- Empty -->
    <div v-else-if="orders.length === 0 && unprocessedOrders.length === 0" class="pc-empty-state">
      <FontAwesomeIcon icon="inbox" aria-hidden="true" />
      <span>暂无采购订单</span>
    </div>

    <!-- Table：待生成行（上）+ 待生产行（下）同表同列，无颜色区分 -->
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
                <th style="width:1%;white-space:nowrap;text-align:center">类型</th>
                <th style="width:1%;white-space:nowrap;text-align:left">下单时间</th>
                <th style="width:1%;white-space:nowrap;text-align:left">订单号</th>
                <th class="pc-customer-th" style="text-align:left">客户名称</th>
                <th style="text-align:left">条码</th>
                <th style="text-align:left">产品名称</th>
                <th style="text-align:right">数量</th>
                <th style="text-align:center">操作</th>
              </tr>
            </thead>
            <tbody>
              <!-- 待生成行：尚未生成采购单的客户订单/备货记录（不可勾选；缺 BOM 提示无法下单） -->
              <tr
                v-for="u in unprocessedOrders"
                :key="u.composite_id"
                :class="{ 'pc-row-multi-sku': (u.sku_count || 1) > 1 }"
              >
                <td class="pc-td-center" />
                <td class="pc-td-center">
                  <span v-if="u.record_type === 'stockin'" class="pc-type-badge pc-type-badge--stockin">备货</span>
                  <span v-else class="pc-type-badge pc-type-badge--order">订单</span>
                </td>
                <td class="pc-td-nowrap">
                  <div class="pc-order-meta-cell">
                    <span class="pc-order-date">{{ formatDate(u.create_time || u.order_date) }}</span>
                  </div>
                </td>
                <td class="pc-td-nowrap"><span class="pc-order-no">{{ u.order_no || '-' }}</span></td>
                <td class="pc-td-truncate pc-customer-cell" style="max-width:120px">{{ u.customer || '-' }}</td>
                <td class="pc-barcode-cell">
                  <template v-if="u.items && u.items.length > 0">
                    <div v-for="(item, idx) in u.items" :key="item.id ?? idx" class="pc-barcode-line">
                      <span class="pc-barcode-text">{{ item.product_barcode || '-' }}</span>
                    </div>
                  </template>
                  <template v-else><span class="pc-barcode-text">-</span></template>
                </td>
                <td class="pc-sku-cell">
                  <template v-if="u.items && u.items.length > 0">
                    <div v-for="(item, idx) in u.items" :key="item.id ?? idx" class="pc-sku-line">
                      <span class="pc-sku-name">{{ item.product_name || '-' }}</span>
                    </div>
                  </template>
                  <span v-else>{{ u.product_name || '-' }}</span>
                </td>
                <td class="pc-td-right pc-sku-qty-cell">
                  <template v-if="u.items && u.items.length > 0">
                    <div v-for="(item, idx) in u.items" :key="item.id ?? idx" class="pc-sku-qty">
                      {{ formatNumber(item.quantity) }}
                      <span v-if="item.deduct_quantity" class="pc-sku-deduct" :title="`抵扣备货 ${item.deduct_quantity}`">−{{ item.deduct_quantity }}</span>
                    </div>
                  </template>
                  <template v-else>{{ formatNumber(u.quantity) }}</template>
                </td>
                <td class="pc-td-center">
                  <span v-if="u.has_bom" class="pc-gen-tag">生成中…</span>
                  <span v-else class="pc-gen-tag pc-gen-tag--nobom">未配置BOM，无法下单</span>
                </td>
              </tr>

              <!-- 待生产行：已生成的采购单 -->
              <tr
                v-for="o in orders"
                :key="o.id"
                :class="{ 'pc-row-selected': selectedSet.has(o.id), 'pc-row-multi-sku': (o.sku_items?.length || 0) > 1 }"
                @click="$emit('toggleSelection', o.id)"
              >
                <td class="pc-td-center" @click.stop>
                  <UiCheckbox :checked="selectedSet.has(o.id)" @update:checked="$emit('toggleSelection', o.id)" />
                </td>
                <td class="pc-td-center">
                  <!-- 待生产行按**来源**显示 订单/备货：source_order_no 只映射客户订单，
                       备货来源的采购单该字段为空（见后端 _build_po_source_no_map）。 -->
                  <span
                    v-if="o.source_order_no"
                    class="pc-type-badge pc-type-badge--order"
                    :title="`来源客户订单：${o.source_order_no}`"
                  >订单</span>
                  <span v-else class="pc-type-badge pc-type-badge--stockin" title="来源：备货记录">备货</span>
                </td>
                <td class="pc-td-nowrap">
                  <div class="pc-order-meta-cell">
                    <span class="pc-order-date">{{ formatDate(o.create_time || o.order_date) }}</span>
                  </div>
                </td>
                <!-- 订单号（采购订单 CG…）：2026-09-30 新增列 -->
                <td class="pc-td-nowrap"><span class="pc-order-no">{{ o.order_no || '-' }}</span></td>
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

        <!-- Pagination（待生产行分页；待生成行取当前页，通常很少） -->
        <UiPagination v-if="totalPages > 1" :current-page="currentPage" :total-pages="totalPages" :total-items="total" @update:current-page="$emit('update:currentPage', $event)" />
      </div>
    </template>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import UiCheckbox from '@/components/ui/UiCheckbox.vue'
import UiPagination from '@/components/ui/UiPagination.vue'
import type { PurchaseOrder, UnprocessedOrder } from '@/types'
import { formatDate, formatNumber } from '@/utils/format'

const props = withDefaults(defineProps<{
  orders: PurchaseOrder[]
  loading: boolean
  fetching?: boolean
  error?: boolean
  total: number
  currentPage: number
  totalPages: number
  selectedIds: number[]
  allSelected: boolean
  /** 待生成行（尚未生成采购单；同表并列在待生产行之上，无颜色区分） */
  unprocessedOrders?: UnprocessedOrder[]
}>(), {
  unprocessedOrders: () => [],
})

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

.pc-type-badge {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  padding: 1px 6px;
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

/* 待生成行的操作列提示（缺 BOM 红字；排队中灰字） */
.pc-gen-tag {
  font-size: 12px;
  font-weight: 600;
  white-space: nowrap;
}

.pc-gen-tag--nobom {
  color: var(--color-danger-600, #dc2626);
}

.pc-sku-deduct {
  font-size: 11px;
  font-weight: 500;
  color: var(--color-warning-600, #e88e2e);
}
</style>
