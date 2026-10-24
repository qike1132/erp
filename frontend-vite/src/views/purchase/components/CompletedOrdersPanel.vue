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

<style scoped src="./CompletedOrdersPanel.css"></style>
