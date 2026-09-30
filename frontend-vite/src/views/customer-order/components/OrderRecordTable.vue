<template>
  <div class="co-records-body">
    <template v-if="isFetchingRecords && orderRecords.length > 0">
      <div class="co-fetching-bar"><div class="co-fetching-progress" /></div>
    </template>
    <!-- 错误态：与空态在视觉和语义上都分开，避免把「请求失败」呈现成「没有数据」 -->
    <div v-if="errorMessage" class="co-state-placeholder co-state-error" role="alert">
      <div class="co-empty-illustration co-error-icon">
        <FontAwesomeIcon icon="triangle-exclamation" aria-hidden="true" />
      </div>
      <p class="co-state-text">{{ errorMessage }}</p>
      <UiButton variant="outline" size="sm" @click="emit('retry')">
        <FontAwesomeIcon icon="undo" style="margin-right: 4px" aria-hidden="true" />重试
      </UiButton>
    </div>
    <UiDataTable
      v-else
      :data="orderRecords"
      :columns="orderColumns"
      :loading="isLoadingRecords && orderRecords.length === 0"
      :paginator="totalPages > 1"
      :rows="perPage"
      :total-records="totalRecords"
      row-key="id"
      @page="onPageChange"
    >
      <template #empty>
        <div class="co-state-placeholder co-state-empty">
          <div class="co-empty-illustration"><FontAwesomeIcon icon="clipboard-list" aria-hidden="true" /></div>
          <p class="co-state-text">暂无记录</p>
        </div>
      </template>
      <template #column-body-order_date="{ row }">
        <span class="co-cell-muted">{{ (row as OrderRecord).order_date }}</span>
      </template>
      <template #column-body-order_no="{ row }">
        <span :class="['co-type-badge', (row as OrderRecord).record_type === 'stockin' ? 'stockin' : 'order']">
          {{ (row as OrderRecord).record_type === 'stockin' ? '备货' : '订单' }}
        </span>
        <span class="co-cell-muted" style="margin-left: 4px;">{{ (row as OrderRecord).order_no }}</span>
      </template>
      <template #column-body-customer="{ row }">
        <span class="co-cell-main">{{ (row as OrderRecord).customer }}</span>
      </template>
      <template #column-body-product="{ row }">
        <!-- 多 SKU：把该订单的全部 SKU 名与各自数量堆叠出来，列表里可直接核对（不必点进详情） -->
        <div v-if="hasMultipleSkus(row as OrderRecord)" class="co-sku-stack">
          <div v-for="(sku, idx) in (row as OrderRecord).items" :key="sku.id ?? idx" class="co-sku-line">
            <span class="co-sku-name">{{ sku.product_name || '-' }}</span>
            <span class="co-sku-qty">{{ sku.quantity }}</span>
          </div>
        </div>
        <template v-else>
          <span class="co-cell-main">{{ (row as OrderRecord).product?.name || '-' }}</span>
          <span v-if="(row as OrderRecord).product?.barcode" class="co-cell-muted" style="display: block; font-size: 11px;">{{ (row as OrderRecord).product?.barcode }}</span>
        </template>
      </template>
      <template #column-body-quantity="{ row }">
        <strong>{{ (row as OrderRecord).quantity }}</strong>
      </template>
      <template #column-body-actions="{ row }">
        <!-- 备货行不给详情入口：后端不存在备货详情端点，而 openDetail 一律按订单 id 查
             （备货行 id 来自 StockIn 表，与订单 id 是两套序列，查订单表必然查无此单） -->
        <div v-if="(row as OrderRecord).record_type === 'order'" class="co-action-group">
          <button
            class="co-btn-icon co-btn-info"
            :aria-label="`查看 ${(row as OrderRecord).order_no || ''} 的详情`"
            @click="emit('view-detail', row as OrderRecord)"
          >
            <FontAwesomeIcon icon="eye" aria-hidden="true" />
          </button>
          <button
            v-if="canDelete"
            class="co-btn-icon co-btn-danger"
            :aria-label="`删除订单 ${(row as OrderRecord).order_no || ''}`"
            @click="emit('delete-record', row as OrderRecord)"
          >
            <FontAwesomeIcon icon="trash-alt" aria-hidden="true" />
          </button>
        </div>
        <span v-else class="co-cell-muted" aria-hidden="true">—</span>
      </template>
    </UiDataTable>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import UiDataTable from '@/components/ui/UiDataTable.vue'
import UiButton from '@/components/ui/UiButton.vue'
import type { TableColumn } from '@/components/ui/UiDataTable.vue'
import type { OrderRecord } from '../composables/types'

const props = defineProps<{
  orderRecords: OrderRecord[]
  isLoadingRecords: boolean
  isFetchingRecords: boolean
  errorMessage: string
  totalPages: number
  totalRecords: number
  perPage: number
  canDelete: boolean
  fetchOrders: () => void
}>()

const emit = defineEmits<{
  'view-detail': [record: OrderRecord]
  'delete-record': [record: OrderRecord]
  'update:perPage': [value: number]
  'change-page': [page: number]
  retry: []
}>()

/** 列固定（订单/备货合并后结构一致）：时间 / 编号 / 客户 / 产品名称 / 数量 / 操作 */
const orderColumns = computed<TableColumn[]>(() => [
  { field: 'order_date', header: '时间', align: 'center' },
  { field: 'order_no', header: '编号', align: 'center' },
  { field: 'customer', header: '客户', align: 'center' },
  // 多 SKU 的块在单元格内缩到内容宽并整体居中（见 .co-sku-stack），故本列与其它列一样居中
  { field: 'product', header: '产品名称', align: 'center' },
  { field: 'quantity', header: '数量', align: 'center' },
  { field: 'actions', header: '操作', align: 'left' },
])

/** 多 SKU 行（一张订单可含多个 SKU；备货恒 1 个）——决定产品列是否堆叠展示 */
function hasMultipleSkus(row: OrderRecord): boolean {
  return (row.items?.length ?? 0) > 1
}

function onPageChange(event: { page: number; rows: number }) {
  if (event.rows !== props.perPage) {
    emit('update:perPage', event.rows)
    emit('change-page', 1)
  } else {
    emit('change-page', event.page + 1)
  }
  props.fetchOrders()
}
</script>

<style scoped>
.co-records-body {
  flex: 1;
  overflow-y: auto;
  padding: 0;
  min-height: 0;
}
.co-type-badge {
  font-size: 11px;
  padding: 2px 8px;
  border-radius: 6px;
  font-weight: 600;
}
.co-type-badge.order {
  background: var(--color-primary-50);
  color: var(--color-primary-600);
}
.co-type-badge.stockin {
  background: var(--color-success-100);
  color: var(--color-success-600);
}

.co-state-placeholder {
  text-align: center;
  padding: 60px 20px;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 12px;
}
.co-state-empty {
  color: var(--color-text-muted);
}
.co-state-error {
  color: var(--color-danger-500);
  gap: 14px;
}
.co-state-error .co-state-text {
  color: var(--color-danger-600, var(--color-danger-500));
}
.co-state-error .co-error-icon {
  opacity: 1;
  color: var(--color-danger-500);
}
.co-state-text {
  font-size: 14px;
  color: var(--color-text-secondary);
  margin: 0;
}
.co-empty-illustration {
  font-size: 36px;
  opacity: 0.4;
  color: var(--color-text-muted);
}

.co-fetching-bar {
  height: 3px;
  background: var(--color-border-light);
  overflow: hidden;
}
.co-fetching-progress {
  height: 100%;
  width: 30%;
  background: var(--color-primary-500);
  animation: co-fetch-slide 1.2s ease-in-out infinite;
}
@keyframes co-fetch-slide {
  0% { transform: translateX(-100%); }
  100% { transform: translateX(400%); }
}

.co-cell-main {
  font-weight: 500;
  color: var(--color-text);
}
.co-cell-muted {
  color: var(--color-text-muted);
  font-size: 12px;
}

/* 产品名称列・多 SKU 堆叠：每行一个 SKU（名字 + 各自数量）。
   左侧 2px 导引线 + 缩进把整块标成「挂在同一张订单下」的子块；SKU 之间用 1px 细线分隔
   （线色与全表行线同为 --color-border，看着是一套网格），末条不画线以免与行线叠成双线。
   2026-09-30 修订一：原实现只有 3px 行距、无任何分隔，表变高后三条 SKU 飘在空白里。
   2026-09-30 修订二：改 inline-flex 让整块缩到内容宽，再由单元格的 text-align:center 把它
   居中（块左/右留白相等）——之前整块拉满整列时，短名字与它的数量之间会空出一千多像素。
   块内仍 text-align:left + 数量右对齐，故各 SKU 数量之间互相成一条竖线可比大小；
   max-width 兜底，防止超长 SKU 名把块撑出单元格。 */
.co-sku-stack {
  display: inline-flex;
  flex-direction: column;
  text-align: left;
  max-width: 100%;
  padding-left: 10px;
  border-left: 2px solid var(--color-border-light);
}
.co-sku-line {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 12px;
  padding: 3px 0;
  border-bottom: 1px solid var(--color-border);
}
.co-sku-line:last-child {
  border-bottom: none;
}
.co-sku-name {
  font-weight: 500;
  color: var(--color-text);
}
.co-sku-qty {
  color: var(--color-text-muted);
  font-size: 12px;
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
}

/* 操作列：左对齐固定起点，让「查看」按钮在单/双按钮行都钉在同一横坐标（居中会左右跳） */
.co-action-group {
  display: flex;
  gap: 4px;
  justify-content: flex-start;
  padding-left: 8px;
}
.co-btn-icon {
  width: 36px;
  height: 36px;
  border: none;
  border-radius: 9px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 14px;
  cursor: pointer;
  transition: background 0.2s ease, transform 0.2s ease;
}
.co-btn-info {
  background: var(--color-primary-50);
  color: var(--color-primary-600);
}
.co-btn-info:hover {
  background: var(--color-primary-100);
  transform: translateY(-1px);
}
.co-btn-danger {
  background: var(--color-danger-50);
  color: var(--color-danger-600);
}
.co-btn-danger:hover {
  background: var(--color-danger-100);
}
</style>
