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
      :data="recordRows"
      :columns="orderColumns"
      :loading="isLoadingRecords && orderRecords.length === 0"
      :paginator="totalPages > 1"
      :rows="perPage"
      :total-records="totalRecords"
      row-key="_rowKey"
      row-group-mode="rowspan"
      :group-rows-by="GROUP_FIELDS"
      @page="onPageChange"
    >
      <template #empty>
        <div class="co-state-placeholder co-state-empty">
          <div class="co-empty-illustration"><FontAwesomeIcon icon="clipboard-list" aria-hidden="true" /></div>
          <p class="co-state-text">暂无记录</p>
        </div>
      </template>

      <!-- 时间 / 编号 / 客户：订单级字段，同一订单内跨 SKU 行合并成一个格 -->
      <template #column-body-_g_date="{ row }">
        <span class="co-cell-muted">{{ row.order_date }}</span>
      </template>
      <template #column-body-_g_no="{ row }">
        <span :class="['co-type-badge', row.record_type === 'stockin' ? 'stockin' : 'order']">
          {{ row.record_type === 'stockin' ? '备货' : '订单' }}
        </span>
        <span class="co-cell-muted" style="margin-left: 4px;">{{ row.order_no }}</span>
      </template>
      <template #column-body-_g_cust="{ row }">
        <span class="co-cell-main">{{ row.customer }}</span>
      </template>

      <!-- 产品名称：一行一个 SKU -->
      <template #column-body-product_name="{ row }">
        <span class="co-cell-main">{{ row.product_name }}</span>
      </template>

      <!-- 数量：每个 SKU 自己的数量落在这里（不再是订单总量堆在产品名称格里） -->
      <template #column-body-quantity="{ row }">
        <span class="co-row-qty">{{ row.quantity }}</span>
      </template>

      <template #column-body-actions="{ row }">
        <!-- 订单行：查看详情（改单在详情弹窗内）+ 删除 -->
        <div v-if="row.record_type === 'order'" class="co-action-group">
          <button
            class="co-btn-icon co-btn-info"
            :aria-label="`查看 ${row.order_no} 的详情`"
            @click="emit('view-detail', row._source)"
          >
            <FontAwesomeIcon icon="eye" aria-hidden="true" />
          </button>
          <button
            v-if="canManage"
            class="co-btn-icon co-btn-danger"
            :aria-label="`删除订单 ${row.order_no}`"
            @click="emit('delete-record', row._source)"
          >
            <FontAwesomeIcon icon="trash-alt" aria-hidden="true" />
          </button>
        </div>
        <!--
          备货行：编辑 + 删除。
          没有「查看」：后端不存在备货详情端点，而查看走的是按订单 id 取详情的 openDetail。
          编辑/删除用 /stock/in/edit/{id} 与 /stock/in/delete/{id}，后端删除自带两道保护
          （已关联出库的拒绝删、会让库存变负的拒绝删），失败原因由后端消息回显。
        -->
        <div v-else-if="canManage" class="co-action-group">
          <button
            class="co-btn-icon co-btn-edit"
            :aria-label="`编辑备货 ${row.order_no}`"
            @click="emit('edit-stockin', row._source)"
          >
            <FontAwesomeIcon icon="pen-to-square" aria-hidden="true" />
          </button>
          <button
            class="co-btn-icon co-btn-danger"
            :aria-label="`删除备货 ${row.order_no}`"
            @click="emit('delete-stockin', row._source)"
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
import { flattenRecordRows } from '../composables/recordRows'
import type { OrderRecord } from '../composables/types'

const props = defineProps<{
  orderRecords: OrderRecord[]
  isLoadingRecords: boolean
  isFetchingRecords: boolean
  errorMessage: string
  totalPages: number
  totalRecords: number
  perPage: number
  /** 是否可增删改：订单与备货的写端点都认 order_manage（备货另认 stockin_manage，见下） */
  canManage: boolean
  fetchOrders: () => void
}>()

const emit = defineEmits<{
  'view-detail': [record: OrderRecord]
  'delete-record': [record: OrderRecord]
  'edit-stockin': [record: OrderRecord]
  'delete-stockin': [record: OrderRecord]
  'update:perPage': [value: number]
  'change-page': [page: number]
  retry: []
}>()

/**
 * 表格行 = 摊平后的「一行一 SKU」。
 * 摊平的动机：一行只能有一个数量格，而一张订单可含多个 SKU —— 原先把 SKU 名与数量一起
 * 堆在产品名称格里，数量就落在了产品名称列的中间，与「数量」列毫不相干。
 */
const recordRows = computed(() => flattenRecordRows(props.orderRecords))

/** 参与跨行合并的列（field 名；为什么是三列三个名见 recordRows.ts 的说明） */
const GROUP_FIELDS = ['_g_date', '_g_no', '_g_cust']

/**
 * 列固定：时间 / 编号 / 客户 / 产品名称 / 数量 / 操作。
 * 前三列的 field 指向分组字段（同订单恒等）——PrimeVue 的跨行合并是**按列 field 的值**比较的，
 * 三列各自与分组键比较就得到同一个跨行数；而真正的显示值从行上的 order_date/order_no/customer 取，
 * 这样既合并、又不会被相邻订单相同的日期或客户误导（生产数据里多笔订单日期都是同一天）。
 */
const orderColumns = computed<TableColumn[]>(() => [
  { field: '_g_date', header: '时间', align: 'center' },
  { field: '_g_no', header: '编号', align: 'center' },
  { field: '_g_cust', header: '客户', align: 'center' },
  { field: 'product_name', header: '产品名称', align: 'center' },
  { field: 'quantity', header: '数量', align: 'center' },
  { field: 'actions', header: '操作', align: 'left' },
])

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
/* UiDataTable 的容器自带 1px 边框 + 12px 圆角（共享组件，13 个视图共用）。
   本页的稿是表格直接铺满白色大卡片、没有内层盒子（2026-10-01 用户要求去掉那两处圆角），
   故在此抵消，不动共享组件——与 /stock 库存页同一做法。 */
.co-records-body :deep(.ui-data-table-wrapper) {
  border: 0;
  border-radius: 0;
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

/* 每个 SKU 自己的数量：等宽数字，便于上下比对 */
.co-row-qty {
  font-weight: 500;
  color: var(--color-text);
  font-variant-numeric: tabular-nums;
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
/* 备货行的编辑：暖色，与订单行的「查看」区分（两者不会出现在同一行，但扫读时
   蓝色=看、暖色=改 的对应关系更稳） */
.co-btn-edit {
  background: var(--color-warning-50);
  color: var(--color-warning-600);
}
.co-btn-edit:hover {
  background: var(--color-warning-100);
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
